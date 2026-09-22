#!/usr/bin/env python

"""`plan manual` — replay a manual step file into a schedule JSON. See
`planners/manual/DESIGN.md`."""

from pathlib import Path
from typing import Annotated

import typer

from .manual import ManualSchedule

__all__ = ['manual']

_Config = Annotated[Path, typer.Argument(
    exists=True, dir_okay=False, help='Run-config JSON (as for `plan infinite`).',
)]
_Steps = Annotated[Path, typer.Argument(
    exists=True, dir_okay=False, help='Step file: a JSON list of manual moves.',
)]
_OutDir = Annotated[Path | None, typer.Option(
    '--output-dir', '-o', file_okay=False, dir_okay=True,
    help='Directory for manual_schedule_<start date>.json. Defaults to cwd.',
)]


def manual(config: _Config, steps: _Steps, output_dir: _OutDir = None) -> None:
    """Rebuild a hand-made schedule from a step file and write its schedule
    JSON (same format as `plan infinite`'s)."""
    out = output_dir or Path.cwd()
    out.mkdir(parents=True, exist_ok=True)
    typer.echo(f'Reading config from {config}')
    ms = ManualSchedule.from_config(config, quiet=False)
    step_list = ManualSchedule.load_steps(steps)
    typer.echo(f'Replaying {len(step_list)} step(s) from {steps}')
    for i, s in enumerate(step_list, start=1):
        try:
            ms.rolls(s.machine, s.item, s.rolls, s.at, s.top, s.btm)
            ms.commit()
        except (ValueError, KeyError) as e:
            raise typer.BadParameter(f'step {i} ({s.to_json()}): {e}') from e
    sd = ms.state.start_date
    path = out / f'manual_schedule_{sd.strftime("%Y%m%d")}.json'
    ms.write_json(path)
    n_jobs = sum(len(m.jobs) for m in ms.machines.values())
    typer.echo(f'  {n_jobs} job(s) on {len(ms.machines)} machine(s)')
    typer.echo(f'Wrote {path}')
