#!/usr/bin/env python

"""`plan retime` — carry an existing plan forward to the plant's current
position (see `planners/retime/DESIGN.md`)."""

from pathlib import Path
from typing import Annotated

import typer

from .retime import retime
from .retime.retime import write_outputs

__all__ = ['retime_cmd']

_Config = Annotated[Path, typer.Argument(
    exists=True, dir_okay=False, readable=True,
    help='Run-config JSON with the NEW start/change dates, machine status and inventory.',
)]
_Prior = Annotated[Path, typer.Argument(
    exists=True, dir_okay=False, readable=True,
    help='The prior plan (schedule JSON written by `plan infinite` or a previous retime).',
)]
_Tickets = Annotated[Path, typer.Argument(
    exists=True, dir_okay=False, readable=True,
    help='The doffed-rolls JSON: an object keyed by machine, each a list of '
         '{"ticket_no", "style", "lbs", "doff_ts"} since the prior plan started.',
)]
_OutDir = Annotated[Path | None, typer.Option(
    '--output-dir', '-o', file_okay=False, dir_okay=True,
    help='Directory for knit_plan_<date>.xlsx/.json and retime_<date>.txt. Defaults to cwd.',
)]
_KeepSets = Annotated[bool, typer.Option(
    '--keep-sets',
    help="Keep the prior plan's set assignments where they still hold and fill only "
         'its NEW… placeholders; by default every set is re-decided in runout order.',
)]


def retime_cmd(config: _Config, prior_plan: _Prior, tickets: _Tickets,
               output_dir: _OutDir = None, keep_sets: _KeepSets = False) -> None:
    """Retime an existing plan: same jobs, rolls and order per machine, the
    times moved to the current machine status and the sets handed out from
    the current inventory in runout order (or kept, with --keep-sets)."""
    out = output_dir or Path.cwd()
    typer.echo(f'Reading config from {config}')
    try:
        result = retime(config, prior_plan, tickets, keep_sets=keep_sets, echo=typer.echo)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e
    p = result.positions
    typer.echo(f'Replayed {len(result.steps)} step(s) on '
               f'{len({m for m, *_ in result.steps})} machine(s) in {result.rounds} re-timing round(s); '
               f'{sum(1 for x in p.values() if x.wrong_style)} on a wrong style, '
               f'{sum(1 for x in p.values() if x.finished)} finished their plan, '
               f'{sum(1 for h in result.hangs if h.source == 'assigned')} prior set(s) kept, {sum(1 for h in result.hangs if h.source == 'stock')} set(s) assigned from stock, {sum(1 for h in result.hangs if h.short_by > 0)} short, '
               f'{len(result.failures)} failure(s)')
    write_outputs(result, out, result.start_date, echo=typer.echo)
