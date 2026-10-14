#!/usr/bin/env python

"""The `Table` declaration of every input — the one place each input's shape
lives. A database input's `Table` shares its name with its `SQLQuery` in
`.queries`; a file-borne input has only its `Table` here.

Every table takes each column exactly as its query labels it, in the query's
order, and forces each column to one of four kinds so a value's type never
depends on whether the rows came from pyodbc or a CSV:

- **string** (`STRING_DTYPE`): identifiers, names, codes — set / ticket /
  machine / style / variant / merge / vendor / luster / yarn type / stitch /
  thread pattern, comments. A merge code looks numeric but is a code.
- **count** (`COUNT_DTYPE`, nullable integer): the bar on a machine,
  beams / nbeams, ends.
- **number** (`NUMBER_DTYPE`, float): weights and quantities (lbs, rem_lbs,
  rack_wt, racks), denier, pct, gauge, width, rl.
- **timestamp**: the plant's systems store timestamps in UTC and the
  planner's clock is plant-local, so every timestamp column is converted to
  `PLANT_TZ` (`utc_to_plant`) and left naive.

Nulls stay null in every kind (`<NA>` / `NaN` / `NaT`).

See `planners/infinite/swmtio/DESIGN.md` ("The queries and their tables").
"""

import re
from datetime import datetime, timezone
from typing import Any

from ..schedule_json import PLANT_TZ
from .translate import Column, Table

STRING_DTYPE = 'string'
COUNT_DTYPE = 'Int64'
NUMBER_DTYPE = 'float64'


def utc_to_plant(value: Any) -> datetime | None:
    """A UTC timestamp → the same instant on the plant's clock, naive.
    Accepts a naive `datetime` (taken as UTC), an aware one (converted from
    its own zone), or an ISO string of either; `None` passes through."""
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(PLANT_TZ).replace(tzinfo=None)


def to_number(value: Any) -> float | None:
    """A numeric cell → `float` (`int`, `Decimal`, numeric string …);
    `None` passes through. A string that is not a number raises
    `ValueError`, as `float` does."""
    if value is None:
        return None
    return float(value)


def to_string(value: Any) -> str | None:
    """A cell → `str` (a numeric code becomes its text, with no trailing
    `.0` for an integral float); `None` passes through."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _s(name: str) -> Column:
    """A string column."""
    return Column(name, dtype=STRING_DTYPE, converter=to_string)


def _i(name: str) -> Column:
    """A count column (nullable integer); the value must be integral."""
    return Column(name, dtype=COUNT_DTYPE, converter=to_number)


def _n(name: str) -> Column:
    """A number column (float)."""
    return Column(name, dtype=NUMBER_DTYPE, converter=to_number)


def _ts(name: str) -> Column:
    """A UTC timestamp column, converted to the plant's clock."""
    return Column(name, converter=utc_to_plant)


# Field suffix → column kind, for the per-bar groups.
_BAR_KINDS = {
    'set_no': _s, 'merge': _s, 'vendor': _s, 'luster': _s, 'desc': _s,
    'stitch': _s, 'thread': _s,
    'ends': _i,
    'denier': _n, 'pct': _n, 'rl': _n,
}


def _bars(*fields: str) -> tuple[Column, ...]:
    """`bar1_<f> … bar4_<f>`, grouped by bar, each of its field's kind."""
    return tuple(_BAR_KINDS[f](f'bar{n}_{f}') for n in range(1, 5) for f in fields)


ACTIVE = Table('ACTIVE', (
    _s('set_no'), _ts('rcv_date'), _ts('assign_date'),
    _n('lbs'), _i('beams'), _i('ends'),
    _s('merge'), _s('vendor'), _n('denier'), _s('luster'), _s('yarn_type'),
    _s('comments'),
))

ASSIGNED = Table('ASSIGNED', (
    _s('machine'), _i('bar'), _ts('assn_ts'),
    _s('set_no'), _n('lbs'), _i('beams'), _i('ends'),
    _s('merge'), _n('denier'), _s('vendor'), _s('luster'), _s('yarn_type'),
))

DOFFED = Table('DOFFED', (
    _s('machine'), _s('ticket'), _ts('start_ts'), _ts('end_ts'),
    _s('style'), _n('rack_wt'), _n('racks'),
))

THREADED = Table('THREADED', (
    _s('machine'), _i('bar'), _n('rem_lbs'), _i('nbeams'),
    _s('set_no'), _s('merge'), _s('vendor'), _n('denier'),
))

LAST_TKT = Table('LAST_TKT', (
    _s('machine'), _s('ticket'), _ts('scan_ts'),
    _s('style'), _i('nbeams'),
    *_bars('set_no', 'merge', 'vendor', 'denier', 'pct'),
    _n('rack_wt'), _n('racks'),
))

SCANNED = Table('SCANNED', (
    _s('ticket'), _s('kind'), _ts('scan_ts'),
))

ALL_VARIANTS = Table('ALL_VARIANTS', (
    _s('variant'), _n('width'), _n('rack_wt'), _n('gauge'), _i('beams'),
    *_bars('ends', 'merge', 'vendor', 'denier', 'luster', 'desc'),
    *_bars('pct', 'rl', 'stitch', 'thread'),
))

# --- the file-borne inputs (dated TSVs) ------------------------------------

_MACHINE_RE = re.compile(r'^([A-Za-z])0*(\d{1,2})$')


def norm_machine(value: Any) -> str | None:
    """A machine id as the database writes it: one upper-case letter and a
    zero-padded two-digit number (`b8` / `B8` / `B08` → `B08`). Surrounding
    whitespace is dropped; `None` passes through; anything else raises
    `ValueError`."""
    if value is None:
        return None
    text = str(value).strip()
    m = _MACHINE_RE.match(text)
    if m is None:
        raise ValueError(f'not a machine id: {value!r}')
    return f'{m[1].upper()}{int(m[2]):02d}'


def _m(name: str) -> Column:
    """A machine-id column, normalised to the database's form."""
    return Column(name, dtype=STRING_DTYPE, converter=norm_machine)


# The floor's per-bar status notes: `bar` is text because a note can cover
# two bars (`1/2`); machine ids are normalised as the racks file's are.
FLOOR_STATUS = Table('FLOOR_STATUS', (
    _m('machine'), _s('bar'), _s('status'),
))

# The reconciled machine status — the same columns as `LAST_TKT`, as the
# reconcile skill writes them (timestamps still UTC).
MACHINE_STATUS = Table('MACHINE_STATUS', LAST_TKT.columns)

# Rack counts per machine; the source's `MC` / `Racks` headers, its machine
# ids normalised to the database's form.
RACKS = Table('RACKS', (
    Column('machine', src_name='MC', dtype=STRING_DTYPE, converter=norm_machine),
    Column('racks', src_name='Racks', dtype=NUMBER_DTYPE, converter=to_number),
))

__all__ = [
    'STRING_DTYPE', 'COUNT_DTYPE', 'NUMBER_DTYPE',
    'utc_to_plant', 'to_number', 'to_string', 'norm_machine',
    'ACTIVE', 'ASSIGNED', 'DOFFED', 'THREADED', 'LAST_TKT', 'SCANNED',
    'ALL_VARIANTS',
    'FLOOR_STATUS', 'MACHINE_STATUS', 'RACKS',
]
