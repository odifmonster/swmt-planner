#!/usr/bin/env python
"""CLI entry point for the Infinite Knitting greedy planner.

Glue layer: reads each input via its submodule's loader, builds `State`
and `Costing`, calls `plan(state, costing)`, and writes the resulting
`PlanReport` to a single Excel workbook in the chosen output directory.

Invoke as `python -m swmtplanner.planners.infinite.cli ...` or via a
console-script entry point (declared in `pyproject.toml` when the
project is packaged)."""

from datetime import datetime
from pathlib import Path

import typer

from swmtplanner.products import read_greige_styles
from swmtplanner.demand import read_rls_items
from swmtplanner.schedule import read_machines
from swmtplanner.support import load_workcal

from .costing import Costing, load_weights
from .loop import plan
from .report import write_plan_report_xlsx
from .state import State


def main(
    products: Path = typer.Option(
        ..., '--products', '-p',
        exists=True, readable=True, dir_okay=False,
        help='Path to the greige-styles JSON.',
    ),
    demand: Path = typer.Option(
        ..., '--demand', '-d',
        exists=True, readable=True, dir_okay=False,
        help='Path to the released-item demand JSON.',
    ),
    machines: Path = typer.Option(
        ..., '--machines', '-m',
        exists=True, readable=True, dir_okay=False,
        help='Path to the machines JSON.',
    ),
    weights: Path = typer.Option(
        ..., '--weights', '-w',
        exists=True, readable=True, dir_okay=False,
        help='Path to the cost-weights JSON.',
    ),
    workcal: Path = typer.Option(
        ..., '--workcal', '-c',
        exists=True, readable=True, dir_okay=False,
        help='Path to the workcal JSON.',
    ),
    start_date: datetime = typer.Option(
        ..., '--start-date', '-s',
        formats=['%Y-%m-%d'],
        help='Planning anchor date (YYYY-MM-DD). Week 0 is due on '
             'this date.',
    ),
    output_dir: Path = typer.Option(
        None, '--output-dir', '-o',
        file_okay=False, dir_okay=True,
        help='Directory to write the output xlsx to. Defaults to the '
             'current working directory. Created if it does not exist.',
    ),
) -> None:
    """Run the Infinite Knitting greedy planner end-to-end."""
    if output_dir is None:
        output_dir = Path.cwd()
    output_dir.mkdir(parents=True, exist_ok=True)

    # ---- Read inputs ----
    typer.echo(f'Reading products from {products}')
    greige_by_id = read_greige_styles(products)
    typer.echo(f'  loaded {len(greige_by_id)} greige(s)')

    typer.echo(f'Reading workcal from {workcal}')
    wc = load_workcal(workcal)

    typer.echo(f'Reading demand from {demand}')
    rls_items = read_rls_items(
        demand, start_date=start_date, greige_by_id=greige_by_id,
    )
    typer.echo(f'  loaded {len(rls_items)} rls item(s)')

    typer.echo(f'Reading machines from {machines}')
    machine_dict = read_machines(
        machines, start_date=start_date, workcal=wc,
        greige_by_id=greige_by_id,
    )
    typer.echo(f'  loaded {len(machine_dict)} machine(s)')

    typer.echo(f'Reading weights from {weights}')
    cost_weights = load_weights(weights)

    # ---- Plan ----
    state = State(
        machines=machine_dict, rls_items=rls_items,
        start_date=start_date, window_end=start_date,
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
    output_path = output_dir / f'knit_plan_{start_date.strftime('%Y%m%d')}.xlsx'
    typer.echo(f'Writing report to {output_path}')
    write_plan_report_xlsx(report, output_path)
    typer.echo('Done.')


if __name__ == '__main__':
    typer.run(main)
