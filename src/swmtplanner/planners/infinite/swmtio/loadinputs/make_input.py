#!/usr/bin/env python

"""`make_input_file` — the module's entry point and the `plan inputs`
command: name one of the planner's inputs, and it runs exactly the
queries and reads exactly the dated TSVs that input's function needs,
calls the function, and writes the result as JSON.

`InputName` lists the inputs; the mapping from a name to its loads and
its function is `_BUILDERS` below, mirroring the table in
`planners/infinite/swmtio/DESIGN.md` ("make_input_file"). The reports the
functions emit (the `loadinputs` logger at WARNING) are routed to stderr
so they reach the terminal.
"""

import json
import logging
import os
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Callable

import typer

from .. import queries, tables
from ..loaders import get_file_name, read_csv, run_query
from .common import log
from .doffed import gen_doffed
from .inventory import gen_inventory
from .machines import gen_machines
from .runout import compute_runout

__all__ = ['InputName', 'make_input_file']

TSV_EXT = 'tsv'
TSV_SEP = '\t'
DATE_FMT = '%Y-%m-%d'


class InputName(str, Enum):
    """The planner's input files, by the name `plan inputs` takes."""
    MACHINES = 'machines'
    BEAM_SETS = 'beam-sets'
    ASSIGNED_SETS = 'assigned-sets'
    DOFFED_ROLLS = 'doffed-rolls'
    RUNOUT = 'runout'


# --- loading ---------------------------------------------------------------

class _Loads:
    """The loaders bound to one call's arguments: `query(name, *dates)`
    runs the `SQLQuery` constant `name` into the `Table` of the same name;
    `file(stem)` reads the dated TSV `stem` into its table (`FLOOR_STATUS`
    for `floor_status`, and so on). Each load happens once per instance:
    a table two builders both need is queried or read a single time."""

    def __init__(self, since: date, files_dir: str | os.PathLike[str],
                 dt: date | None, cfgpath: str | os.PathLike[str] | None):
        self.since = since
        self.files_dir = Path(files_dir)
        self.dt = dt
        self.cfgpath = None if cfgpath is None else str(cfgpath)
        self._loaded: dict[tuple[str, tuple[date, ...]], Any] = {}

    def query(self, name: str, *dates: date) -> Any:
        key = (name, dates)
        if key not in self._loaded:
            q: queries.SQLQuery = getattr(queries, name)
            self._loaded[key] = run_query(q.get_query(*dates), getattr(tables, name),
                                          self.cfgpath)
        return self._loaded[key]

    def dated(self, name: str) -> Any:
        return self.query(name, self.since)

    def file(self, stem: str) -> Any:
        key = (stem, ())
        if key not in self._loaded:
            fpath = self.files_dir / get_file_name(stem, TSV_EXT, self.dt)
            self._loaded[key] = read_csv(str(fpath), getattr(tables, stem.upper()),
                                         sep=TSV_SEP)
        return self._loaded[key]


def _doffed(ld: _Loads) -> dict[str, list[dict[str, Any]]]:
    return gen_doffed(ld.dated('DOFFED'), ld.dated('TKTS_SINCE'))


def _runout(ld: _Loads) -> dict[str, dict[int, dict[str, Any]]]:
    return compute_runout(ld.dated('THREADINGS_SINCE'), _doffed(ld), ld.file('racks'),
                          ld.query('ALL_VARIANTS'), ld.query('LAST_TKT'),
                          ld.query('THREADED'))


def _machines(ld: _Loads) -> list[dict[str, Any]]:
    return gen_machines(_runout(ld), ld.file('machine_status'), ld.file('racks'),
                        ld.query('ALL_VARIANTS'))


def _inventory(ld: _Loads) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return gen_inventory(ld.query('ACTIVE'), ld.query('ASSIGNED'), ld.file('floor_status'))


_BUILDERS: dict[InputName, Callable[[_Loads], Any]] = {
    InputName.MACHINES: _machines,
    InputName.BEAM_SETS: lambda ld: _inventory(ld)[0],
    InputName.ASSIGNED_SETS: lambda ld: _inventory(ld)[1],
    InputName.DOFFED_ROLLS: _doffed,
    InputName.RUNOUT: _runout,
}


def _ensure_reporting() -> None:
    """Route the functions' reports to stderr once, unless the caller has
    already configured the logger (or a parent)."""
    if log.handlers or logging.getLogger().handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    log.addHandler(handler)
    log.setLevel(logging.WARNING)


# --- the command -----------------------------------------------------------

_Name = Annotated[InputName, typer.Argument(
    help='Which input to produce.',
)]
_Out = Annotated[Path, typer.Argument(
    dir_okay=False, help='The JSON file to write.',
)]
_Since = Annotated[datetime, typer.Option(
    '--since', formats=[DATE_FMT],
    help='Start of the window the dated queries cover (doffs, tickets, '
         'threadings). For machines/runout it must reach back past every '
         "running set's threading.",
)]
_FilesDir = Annotated[Path, typer.Option(
    '--files-dir', exists=True, file_okay=False,
    help='Directory holding the dated TSVs (racks_<date>.tsv, '
         'machine_status_<date>.tsv, floor_status_<date>.tsv).',
)]
_Date = Annotated[datetime | None, typer.Option(
    '--date', formats=[DATE_FMT],
    help="The TSVs' date stamp. Defaults to today.",
)]
_DbConfig = Annotated[Path | None, typer.Option(
    '--db-config', exists=True, dir_okay=False,
    help='SQL Server config file. Defaults to the SQLCONFIG environment variable.',
)]


def make_input_file(name: _Name, fpath: _Out, *, since: _Since, files_dir: _FilesDir,
                    dt: _Date = None, cfgpath: _DbConfig = None) -> None:
    """Produce one of the planner's input files from the plant's database
    and the day's status TSVs, and write it to FPATH as JSON."""
    name = InputName(name)
    if name not in _BUILDERS:
        raise ValueError(f'unknown input name {name!r}')
    _ensure_reporting()
    ld = _Loads(since, files_dir, dt, cfgpath)
    try:
        result = _BUILDERS[name](ld)
    except (OSError, ValueError, KeyError) as e:
        raise typer.BadParameter(str(e)) from e
    with open(fpath, 'w', encoding='utf-8') as fh:
        json.dump(result, fh, indent=4, ensure_ascii=False)
        fh.write('\n')
