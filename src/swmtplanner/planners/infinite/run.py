#!/usr/bin/env python
"""CLI entry point for the Infinite Knitting greedy planner.

Reads a run-config JSON (one required positional arg) that bundles
every input, optionally overridden by per-input CLI flags. See the
"CLI entry point" section in `planners/infinite/DESIGN.md` for the
config schema and override rules.

Invoke as `python -m swmtplanner.planners.infinite.run <config.json>
[overrides...]` or via a console-script entry point declared in
`pyproject.toml`."""

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Callable

import typer

from swmtplanner.products import (
    read_greige_styles, greige_styles_from_list,
)
from swmtplanner.demand import read_rls_items, rls_items_from_list
from swmtplanner.schedule import read_machines, machines_from_list
from swmtplanner.support import load_workcal, workcal_from_dict

from .costing import (
    Costing, load_weights, weights_from_dict,
)
from .loop import plan
from .report import write_plan_report_xlsx
from .state import State


_REQUIRED_KEYS = (
    'start_date', 'weights', 'products', 'workcal', 'machines', 'demand',
)


_Config = Annotated[Path, typer.Argument(
    exists=True, readable=True, dir_okay=False,
    help='Path to the run-config JSON.',
)]
_StartDate = Annotated[datetime | None, typer.Option(
    '--start-date', '-s',
    formats=['%Y-%m-%d'],
    help='Override the config\'s start_date. YYYY-MM-DD.',
)]
_Products = Annotated[str | None, typer.Option(
    '--products', '-p',
    help='Override greige-styles. A path to a JSON file, or — for '
         'testing — an inline JSON string starting with `[` or `{`.',
)]
_Workcal = Annotated[str | None, typer.Option(
    '--workcal', '-c',
    help='Override workcal. Path or inline JSON; if inline, the '
         'workcal\'s nested `holidays` field must also be inline.',
)]
_Machines = Annotated[str | None, typer.Option(
    '--machines', '-m',
    help='Override machines. Path or inline JSON.',
)]
_Demand = Annotated[str | None, typer.Option(
    '--demand', '-d',
    help='Override demand. Path or inline JSON.',
)]
_Weights = Annotated[str | None, typer.Option(
    '--weights', '-w',
    help='Override cost weights. Path or inline JSON.',
)]
_OutDir = Annotated[Path | None, typer.Option(
    '--output-dir', '-o',
    file_okay=False, dir_okay=True,
    help='Directory to write the output xlsx to. Defaults to the '
         'current working directory.',
)]


def run(
    config: _Config,
    start_date: _StartDate = None,
    products: _Products = None,
    workcal: _Workcal = None,
    machines: _Machines = None,
    demand: _Demand = None,
    weights: _Weights = None,
    output_dir: _OutDir = None,
) -> None:
    """Run the Infinite Knitting greedy planner end-to-end. The
    required `config` arg is a JSON file that holds every input either
    inline or by path; all other arguments are optional overrides. See
    the "CLI entry point" section of `planners/infinite/DESIGN.md`."""
    if output_dir is None:
        output_dir = Path.cwd()
    output_dir.mkdir(parents=True, exist_ok=True)

    typer.echo(f'Reading config from {config}')
    with open(config) as f:
        cfg = json.load(f)
    _validate_config(cfg, config)
    config_dir = config.parent

    sd = start_date or datetime.strptime(cfg['start_date'], '%Y-%m-%d')

    # ---- Resolve inputs ----
    greige_by_id = _resolve(
        cli_value=products, config_value=cfg['products'],
        config_dir=config_dir,
        file_loader=read_greige_styles,
        inline_loader=lambda d, source: greige_styles_from_list(
            d, source=source,
        ),
        label='products',
    )
    typer.echo(f'  loaded {len(greige_by_id)} greige(s)')

    wc = _resolve_workcal(
        cli_value=workcal, config_value=cfg['workcal'],
        config_dir=config_dir,
    )

    rls_items = _resolve(
        cli_value=demand, config_value=cfg['demand'],
        config_dir=config_dir,
        file_loader=lambda p: read_rls_items(
            p, start_date=sd, greige_by_id=greige_by_id,
        ),
        inline_loader=lambda d, source: rls_items_from_list(
            d, start_date=sd, greige_by_id=greige_by_id, source=source,
        ),
        label='demand',
    )
    typer.echo(f'  loaded {len(rls_items)} rls item(s)')

    machine_dict = _resolve(
        cli_value=machines, config_value=cfg['machines'],
        config_dir=config_dir,
        file_loader=lambda p: read_machines(
            p, start_date=sd, workcal=wc, greige_by_id=greige_by_id,
        ),
        inline_loader=lambda d, source: machines_from_list(
            d, start_date=sd, workcal=wc, greige_by_id=greige_by_id,
            source=source,
        ),
        label='machines',
    )
    typer.echo(f'  loaded {len(machine_dict)} machine(s)')

    cost_weights = _resolve(
        cli_value=weights, config_value=cfg['weights'],
        config_dir=config_dir,
        file_loader=load_weights,
        inline_loader=lambda d, source: weights_from_dict(
            d, source=source,
        ),
        label='weights',
    )

    # ---- Plan ----
    state = State(
        machines=machine_dict, rls_items=rls_items,
        start_date=sd, window_end=sd,
    )
    costing = Costing(cost_weights)

    typer.echo('Running planner...')
    report = plan(state, costing)
    typer.echo(f'  total_score: {report.total_score:.2f}')
    typer.echo(
        f'  unmet (item, week) pairs: '
        f'{len(report.unmet_lbs_by_item_week)}'
    )

    # ---- Write output ----
    output_path = (
        output_dir / f'knit_plan_{sd.strftime("%Y%m%d")}.xlsx'
    )
    typer.echo(f'Writing report to {output_path}')
    write_plan_report_xlsx(report, output_path)
    typer.echo('Done.')


# ----- helpers ------------------------------------------------------------

def _validate_config(cfg: Any, config_path: Path) -> None:
    """Cheap up-front shape check on the config JSON. Catches the
    common mistakes (non-object root, missing required keys) with a
    typer-formatted error before the per-input loaders get involved."""
    if not isinstance(cfg, dict):
        raise typer.BadParameter(
            f'config at {config_path!r} must be a top-level JSON object'
        )
    missing = set(_REQUIRED_KEYS) - set(cfg.keys())
    if missing:
        raise typer.BadParameter(
            f'config at {config_path!r} is missing required keys: '
            f'{sorted(missing)}'
        )


def _looks_like_inline_json(value: str) -> bool:
    """A CLI override starts with `{` or `[` (after whitespace) when
    the user means inline JSON, else it's interpreted as a path."""
    stripped = value.lstrip()
    return bool(stripped) and stripped[0] in '{['


def _resolve(
    *,
    cli_value: str | None,
    config_value: Any,
    config_dir: Path,
    file_loader: Callable[[Path], Any],
    inline_loader: Callable[[Any, str], Any],
    label: str,
) -> Any:
    """Resolve one input value from CLI override or config field.

    Precedence (highest to lowest):
      1. `cli_value` — when set, parsed as inline JSON if it starts
         with `{` / `[`, else as a path (relative to cwd).
      2. `config_value` — a string is a path (relative to `config_dir`
         if relative), any other type is the already-parsed value.

    `label` is the input's config key name. The inline-loader callable
    is invoked as `inline_loader(parsed_value, source)` so the source
    string flows into the loader's error messages for context.

    Workcal has a sibling helper (`_resolve_workcal`) because its
    inline loader takes an extra `holidays_base_dir` argument."""
    typer.echo(f'Resolving {label}')
    if cli_value is not None:
        if _looks_like_inline_json(cli_value):
            return inline_loader(
                json.loads(cli_value), f'--{label} inline JSON',
            )
        return file_loader(Path(cli_value))

    if isinstance(config_value, str):
        path = Path(config_value)
        if not path.is_absolute():
            path = config_dir / path
        return file_loader(path)

    return inline_loader(config_value, f"config['{label}']")


def _resolve_workcal(
    *,
    cli_value: str | None,
    config_value: Any,
    config_dir: Path,
):
    """Workcal resolution. Adds the `holidays_base_dir` argument used
    by `workcal_from_dict` to resolve a nested string `holidays` path
    relative to the right directory: the config's directory for a
    config-inlined workcal, or `None` (forces fully-inlined holidays)
    for a CLI-inlined workcal."""
    typer.echo('Resolving workcal')
    if cli_value is not None:
        if _looks_like_inline_json(cli_value):
            return workcal_from_dict(
                json.loads(cli_value),
                source='--workcal inline JSON',
            )
        return load_workcal(Path(cli_value))

    if isinstance(config_value, str):
        path = Path(config_value)
        if not path.is_absolute():
            path = config_dir / path
        return load_workcal(path)

    return workcal_from_dict(
        config_value,
        holidays_base_dir=config_dir,
        source="config['workcal']",
    )


if __name__ == '__main__':
    typer.run(run)
