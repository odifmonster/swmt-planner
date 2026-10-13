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
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field
from typing import Annotated, Any, Callable, Mapping

import typer

from swmtplanner.products import (
    read_greige_styles, greige_styles_from_list, read_variant_masters,
    read_variant_map, read_beam_sets, beam_sets_from_list, normalize_blacklist,
)
from swmtplanner.demand import read_rls_items, rls_items_from_list
from swmtplanner.schedule import (
    read_machines, machines_from_list, build_inventory,
    capacity_from_dict,
)
from swmtplanner.support import load_workcal, workcal_from_dict, planning_mode
from swmtplanner.debuglog import DebugLog

from .costing import (
    Costing, load_weights, weights_from_dict,
)
from swmtplanner.dashboard import DatabaseConfigError, resolve_conn_config
from .sqldump import PersistenceError, persist_run
from .loop import plan, PlanReport
from .report import write_plan_report_xlsx
from .schedule_json import write_schedule_json
from .state import PriorCommit, State


_REQUIRED_KEYS = (
    'start_date', 'weights', 'products', 'workcal', 'machines', 'demand',
)


def _build_debug_log() -> DebugLog:
    """Construct the `DebugLog`: all tables with their keys / links configured
    (see `swmtplanner/debuglog/DESIGN.md`). The planner populates the
    `iteration_log` / `cost_summary` tables as it runs (phase 1); the cost
    detail and output tables (phase 2) are set up here but not yet populated.
    This just sets up the empty, schema-fixed log."""
    dl = DebugLog(
        run_configs=[
            ('kind', None),
            ('label', None),
            ('value', None),
        ],
        iteration_states=[
            ('iteration_idx', None),
            ('window_end', None),
            ('reference_week', None),
        ],
        iteration_log=[
            ('iteration_idx', None),
            ('move_id', None),
            ('order_id', None),
            ('order_remaining_lbs', None),
            ('machine', None),
            ('decision_point', None),
            ('role', 'rejected'),
            ('rank', None),
            ('total_cost', None),
        ],
        cost_summary=[
            ('summary_id', None),
            ('move_id', None),
            ('label', None),
            ('kind', None),
            ('raw', 0.0),
            ('cost', 0.0),
        ],
        inv_cost_detail=[
            ('icost_id', None),
            ('summary_id', None),
            ('move_id', None),
            ('label', None),
            ('item', None),
            ('days', None),
            ('qty', 0.0),
            ('weight', 0.0),
            ('value', 0.0),
        ],
        sched_cost_detail=[
            ('activity_id', None),
            ('move_id', None),
            ('machine', None),
            ('start', None),
            ('end', None),
            ('desc', None),
            ('weight', None),                       # blank for cost-free types
            ('cost', None),
        ],
        priority_detail=[                           # key-less
            ('move_id', None),
            ('item', None),
            ('week_idx', None),
            ('remaining_lbs', 0.0),
            ('late_day', None),
            ('weight', 0.0),
            ('cost', 0.0),
        ],
        production=[
            ('knit_id', None),
            ('move_id', None),
            ('roll_id', None),
            ('job_id', None),
            ('item', None),
            ('start', None),
            ('end', None),
            ('lbs', 0.0),
        ],
        demand=[
            ('order_id', None),
            ('item', None),
            ('due_date', None),
            ('demand', 0.0),
            ('covered_on_hand', 0.0),
            ('remaining', 0.0),
        ],
        unmet_demand=[                              # key-less
            ('item', None),
            ('week_idx', None),
            ('unmet_lbs', 0.0),
        ],
    )
    # Primary keys (set before the foreign keys that reference them).
    dl.set_pk('run_configs', 'kind', 'label')              # composite, non-auto
    dl.set_pk('iteration_states', 'iteration_idx')          # non-auto
    dl.set_pk('iteration_log', 'move_id', ctr_name='move_id')
    dl.set_pk('cost_summary', 'summary_id')                 # non-auto, caller-built
    dl.set_pk('inv_cost_detail', 'icost_id', ctr_name='icost_id')
    dl.set_pk('sched_cost_detail', 'activity_id')           # the Activity's id
    dl.set_pk('production', 'knit_id')                      # the Knit's id
    dl.set_pk('demand', 'order_id')

    # Foreign keys.
    dl.set_fk('iteration_log', 'order_id', 'demand', 'order_id')
    dl.set_fk('iteration_log', 'iteration_idx',
              'iteration_states', 'iteration_idx')
    dl.set_fk('cost_summary', 'move_id', 'iteration_log', 'move_id')
    dl.set_fk('inv_cost_detail', 'summary_id', 'cost_summary', 'summary_id')
    dl.set_fk('inv_cost_detail', 'move_id', 'iteration_log', 'move_id')
    dl.set_fk('sched_cost_detail', 'move_id', 'iteration_log', 'move_id')
    dl.set_fk('priority_detail', 'move_id', 'iteration_log', 'move_id')
    dl.set_fk('production', 'move_id', 'iteration_log', 'move_id')
    return dl


_Config = Annotated[Path, typer.Argument(
    exists=True, readable=True, dir_okay=False,
    help='Path to the run-config JSON.',
)]
_StartDate = Annotated[datetime | None, typer.Option(
    '--start-date', '-s',
    formats=['%Y-%m-%d'],
    help='Override the config\'s start_date. YYYY-MM-DD.',
)]
_ChangeDate = Annotated[datetime | None, typer.Option(
    '--change-date',
    formats=['%Y-%m-%d', '%Y-%m-%d %H:%M:%S'],
    help='Override the config\'s change_date: when the plant can first '
         'change a machine over. Defaults to start_date.',
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
_StateCfg = Annotated[str | None, typer.Option(
    '--state-cfg', '-g',
    help='Override state configuration variables. Path or inline JSON.'
)]
_DBConnect = Annotated[str | None, typer.Option(
    '--db-conn', '-b',
    help='Override database connection information. Path or inline JSON.'
)]
_Label = Annotated[str | None, typer.Option(
    '--label', '-l',
    help='Set this run\'s label. Only used in verbose mode.'
)]
_OutDir = Annotated[Path | None, typer.Option(
    '--output-dir', '-o',
    file_okay=False, dir_okay=True,
    help='Directory to write the output xlsx to. Defaults to the '
         'current working directory.',
)]
_Verbose = Annotated[bool, typer.Option(
    '--verbose', '-v',
    help='Persist the full per-iteration debug log to the configured SQL Server '
         'database (a run-tagged row-set for the knit-debug investigation '
         'app). Requires --label and prompts for run notes in vi.',
)]


def run(
    config: _Config,
    start_date: _StartDate = None,
    change_date: _ChangeDate = None,
    products: _Products = None,
    workcal: _Workcal = None,
    machines: _Machines = None,
    demand: _Demand = None,
    weights: _Weights = None,
    scfg: _StateCfg = None,
    dbconn: _DBConnect = None,
    label: _Label = None,
    output_dir: _OutDir = None,
    verbose: _Verbose = False,
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

    sd = start_date or _parse_date(cfg['start_date'], 'start_date')
    cd = change_date or _parse_date(cfg.get('change_date'), 'change_date', default=sd)

    # ---- Verbose-mode prerequisites (gathered up front) ----
    # A verbose run is persisted to SQL Server as a labelled, annotated run, so both
    # a --label and (interactively-entered) notes are required before the work
    # begins — fail fast, and collect the notes immediately via the editor.
    db_block = _resolve_db_block(dbconn, cfg.get('database'))
    notes = None
    if verbose:
        if not label:
            raise typer.BadParameter(
                '--label is required when running with --verbose',
                param_hint='--label',
            )
        notes = _gather_notes()

    # ---- Resolve inputs ----
    inputs = load_inputs(
        cfg, config_dir, start_date=sd, change_date=cd,
        overrides={'products': products, 'workcal': workcal, 'demand': demand,
                   'machines': machines, 'weights': weights},
    )
    greige_by_id = inputs.greige_by_id
    rls_items = inputs.rls_items
    machine_dict = inputs.machines
    inventory = inputs.inventory
    cost_weights = inputs.weights

    # ---- Plan ----
    def _read_json_file(fpath: str | None) -> dict:
        if fpath is None:
            return {}
        with open(fpath) as infile:
            ret = json.load(infile)
        return ret
    statecfg = _resolve(
        cli_value=scfg, config_value=cfg.get('state'),
        config_dir=config_dir,
        file_loader=_read_json_file,
        inline_loader=lambda x, _: {} if x is None else x,
        label='state',
    )
    statecfg = _parse_state_block(statecfg)
    prior = prior_commits(inputs.prior_jobs)
    if inputs.prior_jobs:
        typer.echo(f'  starting from {sum(len(v) for v in prior.values())} prior job(s); '
                   f'those filling urgent demand are recommitted first')
    state = State(
        machines=machine_dict,
        rls_items=rls_items,
        start_date=sd,
        window_end=sd,
        inventory=inventory,
        capacity=inputs.capacity,
        prior=prior,
        **statecfg
    )
    costing = Costing(cost_weights)

    debuglog = _build_debug_log() if verbose else None

    # ---- Output names ----
    # `knit_plan_<date>.xlsx` (and `.json`), or `knit_plan_<date>_<n>.xlsx`
    # when that already exists; the tape-out report takes the same suffix
    # (`tape_outs_<date>[_<n>].txt`) so one run's three files match.
    stamp = sd.strftime('%Y%m%d')
    output_path = output_dir / f'knit_plan_{stamp}.xlsx'
    idx = 1
    while output_path.exists():
        idx += 1
        stamp = f'{sd.strftime("%Y%m%d")}_{idx}'
        output_path = output_dir / f'knit_plan_{stamp}.xlsx'
    tape_out_report = output_dir / f'tape_outs_{stamp}.txt'
    tape_out_report.unlink(missing_ok=True)     # the planner appends per decision

    typer.echo('Running planner...')
    report = plan(state, costing, debuglog=debuglog, tape_out_report=tape_out_report)
    typer.echo(f'Tape-out decisions (alternatives + scores) in {tape_out_report}')
    typer.echo(f'  total_score: {report.total_score:.2f}')
    typer.echo(
        f'  unmet (item, week) pairs: '
        f'{len(report.unmet_lbs_by_item_week)}'
    )
    for line in passed_over_lines(report):
        typer.echo(line)
    if report.prior:
        by = {k: sum(1 for f in report.prior if f.status == k) for k in ('consumed', 'dropped', 'open')}
        typer.echo(f'  prior jobs: {by["consumed"]} recommitted, {by["dropped"]} dropped, '
                   f'{by["open"]} left to the loop')
    filled = [j for jobs in report.jobs_by_machine.values() for j in jobs if j.fill]
    if filled:
        typer.echo(f'  slot waits filled: {len(filled)} jobs knit the current item '
                   f'while waiting ({sum(j.total_rolls for j in filled)} rolls on them)')

    # ---- Write output ----
    typer.echo(f'Writing report to {output_path}')
    write_plan_report_xlsx(report, output_path)
    json_path = output_path.with_suffix('.json')
    typer.echo(f'Writing schedule JSON to {json_path}')
    write_schedule_json(report, json_path)

    if verbose:
        _persist_debuglog(db_block, debuglog, report, sd, label, notes)

    typer.echo('Done.')


def _persist_debuglog(
    db_block, debuglog, report, start_date, label, notes,
) -> int | None:
    """Persist the verbose `debuglog` to the SQL Server store when a
    `database` connection block is configured, returning the new `run_id` (or
    `None` when not persisted). Resolves the writer `ConnConfig` from `db_block`
    and writes the run tagged with its metadata (`start_date`, `total_score`,
    `n_unmet`, `label`, `notes`).

    Non-fatal: the schedule output (XLSX) has already been written, so a missing
    block or a config/persistence error is reported as a warning, not a crash."""
    if db_block is None:
        typer.echo(
            '  (--verbose) no database connection configured; debug log '
            'not persisted'
        )
        return None
    try:
        conn = resolve_conn_config(db_block)
        run_id = persist_run(
            debuglog, conn,
            start_date=start_date.date(),
            total_score=report.total_score,
            n_unmet=len(report.unmet_lbs_by_item_week),
            label=label, notes=notes,
        )
        typer.echo(
            f'  (--verbose) persisted debug log to SQL Server as run_id {run_id}'
        )
        return run_id
    except (DatabaseConfigError, PersistenceError) as exc:
        typer.echo(
            f'  (--verbose) WARNING: debug log not persisted: {exc}', err=True,
        )
        return None


@dataclass
class Inputs:
    """Everything a run-config resolves to (see "Run-config JSON" in
    DESIGN.md) — shared by `plan infinite` and the manual scheduler
    (`planners/manual`), so both load a config identically."""
    start_date: datetime
    change_date: datetime
    """When the plant can first change a machine over (>= `start_date`); the
    machines are already run up to it on their current items."""
    greige_by_id: dict[str, Any]
    variant_masters: dict[str, str] | None
    variant_map: Any
    inventory: dict
    workcal: Any
    rls_items: dict[str, Any]
    machines: dict[str, Any]
    weights: Any
    capacity: Any
    """The plant's changeover ration (`schedule.ChangeoverCapacity`), from
    the config's `changeover_capacity` block; constrains nothing without
    one."""
    prior_jobs: dict[str, list[Any]] = field(default_factory=dict)
    """The config's `prior_plan` (a retimed schedule JSON) as
    `retime.PriorJob`s per machine, in start order; empty without one.
    `prior_commits` turns them into the planner's `PriorCommit`s."""
    blacklist: frozenset[str] = frozenset()
    """The config's `blacklist` of yarn merges flagged for quality, normalised
    (`products.normalize_blacklist`); the loaded sets carrying one are
    stamped `blacklisted` (see "Blacklisted merges" in schedule/DESIGN.md)."""


def prior_commits(prior_jobs: 'Mapping[str, list[Any]]') -> 'dict[str, list[PriorCommit]]':
    """The prior plan's jobs as `PriorCommit`s for the pre-pass (see
    "Sticking to the prior plan" in DESIGN.md): per machine in start
    order, every job with a target order and rolls left; run-up jobs are
    left out."""
    out: dict[str, list[PriorCommit]] = {}
    for mid, jobs in prior_jobs.items():
        kept = [PriorCommit(machine=mid, prior_job=j.job_id, item=j.item, rolls=j.rolls,
                            order=j.order, due_date=j.due_date, start=j.start)
                for j in sorted(jobs, key=lambda j: j.start)
                if j.order is not None and j.rolls > 0]
        if kept:
            out[mid] = kept
    return out


def load_config(config: Path, *, start_date: datetime | None = None,
                change_date: datetime | None = None,
                echo: Callable[[str], Any] = typer.echo) -> tuple[dict, Inputs]:
    """Read + validate a run-config JSON and resolve every input in it. Returns
    the raw config (for its `state` / `database` blocks) and the `Inputs`."""
    with open(config) as f:
        cfg = json.load(f)
    _validate_config(cfg, config)
    sd = start_date or _parse_date(cfg['start_date'], 'start_date')
    cd = change_date or _parse_date(cfg.get('change_date'), 'change_date', default=sd)
    return cfg, load_inputs(cfg, config.parent, start_date=sd, change_date=cd,
                            echo=echo)


def _parse_date(value: Any, key: str, default: datetime | None = None) -> datetime:
    """A config date (`start_date`, `change_date`): a date (`YYYY-MM-DD`,
    midnight) or a date-time (`YYYY-MM-DD HH:MM[:SS]` / ISO 8601), in plant
    local time like every timestamp the planner handles. `default` when the
    key is absent."""
    if value is None and default is not None:
        return default
    try:
        return datetime.fromisoformat(str(value).strip())
    except ValueError as e:
        raise typer.BadParameter(
            f"config[{key!r}] must be YYYY-MM-DD or YYYY-MM-DD HH:MM:SS, "
            f'got {value!r}'
        ) from e


_MODES = ('exact', 'planning')


def load_inputs(
    cfg: dict, config_dir: Path, *, start_date: datetime,
    change_date: datetime | None = None,
    overrides: Mapping[str, str | None] | None = None,
    echo: Callable[[str], Any] = typer.echo,
) -> Inputs:
    """Resolve a run-config's inputs (products, the optional variant files and
    beam-set inventory, workcal, demand, machines, weights). `overrides` maps
    an input key to a CLI override (path or inline JSON) — see `_resolve`.

    Two things happen here beyond loading. The config's `mode` (`exact`, the
    default, or `planning`) is applied process-wide **before** any input is
    read (`support.planning_mode` — the loaders and the machine model consult
    it). And once the machines and the inventory exist, every machine is
    **run up to `change_date`** on its current item (`Machine.run_until`),
    committing those rolls to the machine, to its item's demand and to the
    inventory, so the planner's first changeover on any machine can be no
    earlier than the plant can act on it."""
    overrides = overrides or {}
    sd = start_date
    cd = change_date or sd
    if cd < sd:
        raise typer.BadParameter(
            f'change_date ({cd}) must not be before start_date ({sd})')
    mode = str(cfg.get('mode', 'exact')).lower()
    if mode not in _MODES:
        raise typer.BadParameter(f"config['mode'] must be one of {_MODES}, got {mode!r}")
    planning_mode.enable(mode == 'planning')
    if mode == 'planning':
        echo('Planning mode: handling times 0.01 h, every beam set at '
             f'{planning_mode.BEAM_LBS:,.0f} lbs')
    greige_by_id = _resolve(
        cli_value=overrides.get('products'), config_value=cfg['products'],
        config_dir=config_dir,
        file_loader=read_greige_styles,
        inline_loader=lambda d, source: greige_styles_from_list(
            d, source=source,
        ),
        label='products', echo=echo,
    )
    echo(f'  loaded {len(greige_by_id)} greige(s)')

    # Optional: the variant-name -> master translation, so a machines file may
    # name the plant's variants in `init_item` (see `schedule/DESIGN.md`).
    variant_masters = None
    if cfg.get('variant_masters') is not None:
        variant_masters = _resolve(
            cli_value=None, config_value=cfg['variant_masters'],
            config_dir=config_dir,
            file_loader=read_variant_masters,
            inline_loader=lambda d, source: dict(d),
            label='variant_masters', echo=echo,
        )
        echo(f'  loaded {len(variant_masters)} variant name(s)')

    # Optional: the per-master merge-combination -> variant map. Supplies the
    # merges on each machine's initial bars and lets knits name their variant;
    # also labels the beam-set inventory (path only — it is a generated file).
    variant_map = None
    if cfg.get('variant_masters') is not None and cfg.get('variant_map') is not None:
        vm_path = Path(cfg['variant_map'])
        if not vm_path.is_absolute():
            vm_path = config_dir / vm_path
        echo('Resolving variant_map')
        variant_map = read_variant_map(vm_path)
        echo(f'  loaded {len(variant_map.masters)} master(s), '
                   f'{len(variant_map.merges)} merge(s)')

    # Optional: yarn merges flagged for quality. A set carrying one is never
    # hung: it is kept out of stock, passed over in a queue, taped out off a
    # bar (see "Blacklisted merges" in schedule/DESIGN.md).
    blacklist: frozenset[str] = frozenset()
    if cfg.get('blacklist') is not None:
        codes = _resolve(
            cli_value=None, config_value=cfg['blacklist'],
            config_dir=config_dir,
            file_loader=lambda p: json.load(open(p)),
            inline_loader=lambda d, source: d,
            label='blacklist', echo=echo,
        )
        if not isinstance(codes, list):
            raise TypeError("config['blacklist'] must be a list of merge codes")
        blacklist = normalize_blacklist(codes)
        echo(f'  {len(blacklist)} blacklisted merge(s)')

    # Optional: the plant's beam-set export, available from the start date.
    # Becomes the stock inventory below, once the machines say which sets
    # are mounted (and so not in stock).
    # Planning mode has no stock and no queues: every set a changeover needs
    # is invented (at BEAM_LBS), and nothing taped out comes back.
    beam_sets = None
    if mode == 'planning' and (cfg.get('beam_sets') is not None
                               or cfg.get('assigned_sets') is not None):
        echo('  planning mode: beam_sets / assigned_sets ignored — changeovers '
             'invent their sets')
    if cfg.get('beam_sets') is not None and mode != 'planning':
        if variant_map is None:
            raise ValueError(
                "config['beam_sets'] requires config['variant_map'] (and "
                "'variant_masters') to label the sets",
            )
        beam_sets = _resolve(
            cli_value=None, config_value=cfg['beam_sets'],
            config_dir=config_dir,
            file_loader=lambda p: read_beam_sets(p, variant_map, sd, blacklist),
            inline_loader=lambda d, source: beam_sets_from_list(
                d, variant_map, sd, source=source, blacklist=blacklist,
            ),
            label='beam_sets', echo=echo,
        )
        n_black = sum(1 for b in beam_sets.values() if b.blacklisted)
        echo(f'  loaded {len(beam_sets)} beam set(s)'
             + (f', {n_black} blacklisted' if n_black else ''))

    # Optional: sets the plant has assigned to a machine bar but not yet
    # threaded — each machine bar's queue (schedule/DESIGN.md, "Beam-set
    # inventory"). Also flagged `assigned` in the export, which keeps them
    # out of free stock.
    assigned_sets = None
    if cfg.get('assigned_sets') is not None and mode != 'planning':
        assigned_sets = _resolve(
            cli_value=None, config_value=cfg['assigned_sets'],
            config_dir=config_dir,
            file_loader=lambda p: json.load(open(p)),
            inline_loader=lambda d, source: d,
            label='assigned_sets', echo=echo,
        )
        echo(f'  loaded {len(assigned_sets)} assigned set(s)')

    wc = _resolve_workcal(
        cli_value=overrides.get('workcal'), config_value=cfg['workcal'],
        config_dir=config_dir, echo=echo,
    )

    rls_items = _resolve(
        cli_value=overrides.get('demand'), config_value=cfg['demand'],
        config_dir=config_dir,
        file_loader=lambda p: read_rls_items(
            p, start_date=sd, greige_by_id=greige_by_id,
        ),
        inline_loader=lambda d, source: rls_items_from_list(
            d, start_date=sd, greige_by_id=greige_by_id, source=source,
        ),
        label='demand', echo=echo,
    )
    echo(f'  loaded {len(rls_items)} rls item(s)')

    machine_dict = _resolve(
        cli_value=overrides.get('machines'), config_value=cfg['machines'],
        config_dir=config_dir,
        file_loader=lambda p: read_machines(
            p, start_date=sd, workcal=wc, greige_by_id=greige_by_id,
            variant_masters=variant_masters, variant_map=variant_map,
            beam_sets=beam_sets, assigned_sets=assigned_sets, blacklist=blacklist,
        ),
        inline_loader=lambda d, source: machines_from_list(
            d, start_date=sd, workcal=wc, greige_by_id=greige_by_id,
            variant_masters=variant_masters, variant_map=variant_map,
            beam_sets=beam_sets, assigned_sets=assigned_sets, source=source,
            blacklist=blacklist,
        ),
        label='machines', echo=echo,
    )
    echo(f'  loaded {len(machine_dict)} machine(s)')
    for line in blacklisted_on_machines(machine_dict):
        echo(line)

    # Stock = the export minus the sets the machines report as mounted.
    inventory = {}
    if beam_sets is not None:
        mounted = {
            m.initial_status.beam(bar).id
            for m in machine_dict.values() for bar in ('top', 'btm')
            if m.initial_status.beam(bar) is not None
        }
        inventory = build_inventory(
            b for b in beam_sets.values() if b.id not in mounted
        )
        n_stock = sum(len(v) for v in inventory.values())
        n_mounted = len(mounted & set(beam_sets))
        n_assigned = sum(1 for b in beam_sets.values() if b.assigned)
        n_queued = sum(len(m.initial_status.queue(bar))
                       for m in machine_dict.values() for bar in ('top', 'btm'))
        n_later = sum(1 for v in inventory.values() for b in v
                      if not b.available_at(sd))
        echo(f'  {n_stock} beam set(s) stocked under {len(inventory)} '
             f'description(s), {n_later} received after the start date; '
             f'{n_mounted} on machines; {n_assigned} assigned '
             f'({n_queued} queued on these machines)')

    cost_weights = _resolve(
        cli_value=overrides.get('weights'), config_value=cfg['weights'],
        config_dir=config_dir,
        file_loader=load_weights,
        inline_loader=lambda d, source: weights_from_dict(
            d, source=source,
        ),
        label='weights', echo=echo,
    )

    cap_spec = cfg.get('changeover_capacity')
    if isinstance(cap_spec, str):
        with open(config_dir / cap_spec) as fh:
            cap_spec = json.load(fh)
    capacity = capacity_from_dict(cap_spec, wc)
    if capacity.resources:
        echo('Changeover ration: ' + ', '.join(
            f'{k} {r.units_per_period}/day {r.window[0]:g}-{r.window[1]:g}h'
            for k, r in capacity.resources.items()))
    else:
        echo('No changeover_capacity block: changes, tape-outs and pattern changes unrationed')

    if cd > sd:
        _advance_machines(machine_dict, rls_items, inventory, sd, cd, echo)

    # Optional: the previous plan, already retimed to this status, whose
    # jobs filling urgent demand the planner recommits before planning.
    prior: dict[str, list[Any]] = {}
    if cfg.get('prior_plan') is not None:
        from swmtplanner.planners.retime import prior_jobs as _prior_jobs  # (retime imports this module)
        prior_path = Path(cfg['prior_plan'])
        if not prior_path.is_absolute():
            prior_path = config_dir / prior_path
        with open(prior_path) as fh:
            plan_json = json.load(fh)
        if not isinstance(plan_json, list):
            raise typer.BadParameter(f'prior_plan {prior_path!r}: expected a schedule JSON list')
        prior = _prior_jobs(plan_json, machine_dict)
        n_jobs = sum(len(v) for v in prior.values())
        n_dated = sum(1 for v in prior.values() for j in v if j.due_date is not None)
        echo(f'  loaded prior plan: {n_jobs} job(s) on {sum(1 for v in prior.values() if v)} '
             f'machine(s), {n_dated} with an order due date')

    return Inputs(
        start_date=sd, change_date=cd, greige_by_id=greige_by_id,
        variant_masters=variant_masters, variant_map=variant_map,
        inventory=inventory, workcal=wc, rls_items=rls_items,
        machines=machine_dict, weights=cost_weights, capacity=capacity,
        prior_jobs=prior, blacklist=blacklist,
    )


def blacklisted_on_machines(machines: 'Mapping[str, Any]') -> list[str]:
    """The load's listing of blacklisted sets found at the machines: one
    line per set mounted on a bar (the bar is foreign — the machine's first
    plan tapes it out) or queued at one (passed over at the hang). Empty
    when there are none."""
    lines = []
    for mid, m in sorted(machines.items()):
        s = m.initial_status
        for bar in ('top', 'btm'):
            beam = s.beam(bar)
            if beam is not None and beam.blacklisted:
                lines.append(f'  {mid:4} {bar:3} mounted set {beam.set_no} (merge {beam.merge}) '
                             f'is blacklisted: the first plan tapes it out')
            for q in s.queue(bar):
                if q.blacklisted:
                    lines.append(f'  {mid:4} {bar:3} queued set {q.set_no} (merge {q.merge}) '
                                 f'is blacklisted: passed over at the hang')
    return lines


def passed_over_lines(report: 'PlanReport') -> list[str]:
    """The run's listing of plant-assigned sets the plan passed over (see
    "Assigned sets and bar queues" in schedule/DESIGN.md): a header and one
    line per set — machine, bar, hang time, the set and its yarn, the
    requirement it failed, the reason. Empty when nothing was passed over."""
    rows = [(mid, p) for mid, ps in sorted(report.queue_passed_over.items()) for p in ps]
    if not rows:
        return []
    lines = [f'  assigned sets passed over (did not fit the bar at the hang, or blacklisted): {len(rows)}']
    for mid, p in rows:
        lines.append(f'    {mid:4} {p.bar:3} {p.at:%m-%d %H:%M}  set {p.beam_set.set_no} '
                     f'({p.beam_set.desc.id}, merge {p.beam_set.merge or "?"})  '
                     f'bar needed {p.wanted.physical.id}  {p.reason}')
    return lines


def _advance_machines(machines: dict, rls_items: dict, inventory: dict,
                      start_date: datetime, change_date: datetime,
                      echo: Callable[[str], Any]) -> None:
    """Run every machine up to `change_date` on its current item (see
    `Machine.run_until`), committing the rolls exactly as the planner would
    (`State.commit_move`: machine schedule, the item's demand, the beam-set
    inventory)."""
    from .state import Move, State
    state = State(machines=machines, rls_items=rls_items, start_date=start_date,
                  window_end=change_date, inventory=inventory)
    echo(f'Running machines up to change_date {change_date}')
    for m_id, m in machines.items():
        plan = m.run_until(change_date, inventory=inventory)
        if plan is None:
            continue
        item = m.current_status.current_item
        lbs = sum(j.total_lbs for j in plan.jobs)
        state.commit_move(Move(machine_id=m_id, item=item, lbs=lbs,
                               start_at='schedule_tail', idle_for=timedelta(0),
                               plan=plan))
        rolls = sum(len(j.rolls) for j in plan.jobs)
        what = f'{rolls} roll(s) of {item.id}' if rolls else 'idle'
        echo(f'  {m_id:3} {what} until {m.schedule_tail}')


def _resolve_db_block(cli_value: str | None, config_value: Any) -> Any:
    """The `database` connection block: the `--db-conn` override (inline JSON
    when it starts with `{`/`[`, else a path to a JSON file) when given, else
    the config's `database` value (a dict, or `None` when absent)."""
    if cli_value is not None:
        if _looks_like_inline_json(cli_value):
            return json.loads(cli_value)
        return json.loads(Path(cli_value).read_text())
    return config_value


def _next_temp_path() -> Path:
    """`temp.txt`, or the first `tempN.txt` (N = 1, 2, …) not already present in
    the current working directory."""
    candidate = Path('temp.txt')
    n = 1
    while candidate.exists():
        candidate = Path(f'temp{n}.txt')
        n += 1
    return candidate


def _gather_notes() -> str:
    """Collect this run's notes interactively: open `vi` on a fresh temp file,
    wait for the user to write and quit, return the file's contents, and delete
    the file. The notes must contain non-whitespace text — exits with an error
    otherwise."""
    path = _next_temp_path()
    path.touch()
    try:
        try:
            subprocess.Popen(['vi', str(path)]).wait()
        except FileNotFoundError:
            typer.echo(
                "Aborted: could not launch 'vi' to collect run notes.",
                err=True,
            )
            raise typer.Exit(code=1)
        notes = path.read_text()
    finally:
        path.unlink(missing_ok=True)
    if not notes.strip():
        typer.echo('Aborted: run notes must not be empty.', err=True)
        raise typer.Exit(code=1)
    return notes


# ----- helpers ------------------------------------------------------------


# `State` fields that are durations. In the config's `state` block they are
# written as a number of hours or as a string with a unit (`"48h"`, `"3d"`,
# `"2w"`, `"90m"`, or `"HH:MM"`); JSON has no duration type.
_STATE_DURATIONS = (
    'window_advance_amount', 'carrying_avoidance_margin',
    'planning_horizon_buffer', 'frozen_window',
)
_DURATION_UNITS = {'m': 1 / 60, 'h': 1.0, 'd': 24.0, 'w': 24.0 * 7}


def _parse_duration(value: Any, key: str) -> timedelta:
    """A `state` duration from its config spelling: a number is hours; a
    string is `<n><unit>` with unit `m`/`h`/`d`/`w`, or `HH:MM`. Negative
    values are allowed."""
    if isinstance(value, timedelta):
        return value
    if isinstance(value, bool):
        raise typer.BadParameter(f'state.{key}: a duration, not a boolean')
    if isinstance(value, (int, float)):
        return timedelta(hours=float(value))
    if isinstance(value, str):
        text = value.strip().lower()
        m = re.fullmatch(r'(-?)(\d+):(\d{1,2})', text)
        if m:
            sign = -1 if m.group(1) else 1
            return sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3)))
        m = re.fullmatch(r'(-?\d+(?:\.\d+)?)\s*([mhdw])', text)
        if m:
            return timedelta(hours=float(m.group(1)) * _DURATION_UNITS[m.group(2)])
    raise typer.BadParameter(
        f'state.{key}: cannot read {value!r} as a duration — use hours as a '
        f'number, "<n>h" / "<n>d" / "<n>w" / "<n>m", or "HH:MM"')


def _parse_state_block(statecfg: dict) -> dict:
    """The config's `state` block with its duration fields converted to
    `timedelta` (see `_parse_duration`); other fields pass through."""
    out = dict(statecfg)
    for key in _STATE_DURATIONS:
        if key in out:
            out[key] = _parse_duration(out[key], key)
    return out

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
    echo: Callable[[str], Any] = typer.echo,
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
    echo(f'Resolving {label}')
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
    echo: Callable[[str], Any] = typer.echo,
):
    """Workcal resolution. Adds the `holidays_base_dir` argument used
    by `workcal_from_dict` to resolve a nested string `holidays` path
    relative to the right directory: the config's directory for a
    config-inlined workcal, or `None` (forces fully-inlined holidays)
    for a CLI-inlined workcal."""
    echo('Resolving workcal')
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
