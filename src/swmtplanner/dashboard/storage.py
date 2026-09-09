#!/usr/bin/env python

"""Storage mapping — how the logical manifest is laid out in SQL Server.

The store differs from the logical `TableSpec`s in two ways, and this module owns
the whole translation so nothing above SQL sees it — the `DebugLog`, the
manifest's logical names, the GUI, and every pure test stay datetime-native and
prefix-free:

- **Table names** — SQL text uses a spec's physical `db_name`; everything else
  keys on `name`.
- **Temporal columns are INTs** — a `datetime` column is stored as an INT pair
  `<stem>_date` (YYYYMMDD) / `<stem>_time` (HHMMSS) at **second precision**,
  where the stem is the logical name minus a trailing `_date` (so `start` ->
  `start_date`/`start_time`, but `due_date` -> `due_date`/`due_time`); a `date`
  column is a single YYYYMMDD INT under its own name.

Pure — no driver, no server. Callers hand `to_storage` clean Python values
(`datetime` / `date` / scalars / `None`); pandas `NaT`/`Timestamp` normalisation
happens upstream (the writer's `to_sql`). See `swmtplanner/dashboard/DESIGN.md`,
"Storage mapping".
"""

from datetime import date, datetime
from typing import Any

from .manifest import Column

__all__ = [
    'quote', 'stem', 'physical_columns', 'to_storage', 'from_storage',
    'sort_expr', 'encode_date', 'decode_date', 'encode_time', 'decode_time',
    'encode_datetime', 'decode_datetime',
]

_DATE_SUFFIX = '_date'
_TIME_SUFFIX = '_time'
# A datetime's combined YYYYMMDDHHMMSS integer is `date_int * _DATE_SCALE + time_int`.
_DATE_SCALE = 1_000_000


def quote(ident: str) -> str:
    """T-SQL bracket-quote `ident` (an embedded `]` is doubled)."""
    return '[' + ident.replace(']', ']]') + ']'


def stem(name: str) -> str:
    """The pair stem of a logical `datetime` column name: the name minus a
    trailing `_date` (`'due_date'` -> `'due'`; `'start'` -> `'start'`)."""
    if name.endswith(_DATE_SUFFIX):
        return name[:-len(_DATE_SUFFIX)]
    return name


def physical_columns(col: Column) -> tuple[str, ...]:
    """The store's column name(s) for logical `col`: the `_date`/`_time` pair for
    a `datetime`; otherwise the column's own name (a `date` included)."""
    if col.type == 'datetime':
        s = stem(col.name)
        return (s + _DATE_SUFFIX, s + _TIME_SUFFIX)
    return (col.name,)


# ----- scalar encodings ------------------------------------------------------

def encode_date(d: Any) -> int:
    """A `date` (or `datetime`, whose date part is used) -> YYYYMMDD."""
    return d.year * 10000 + d.month * 100 + d.day


def decode_date(n: int) -> date:
    """YYYYMMDD -> `date` (`ValueError` on an impossible date)."""
    return date(n // 10000, (n // 100) % 100, n % 100)


def encode_time(t: Any) -> int:
    """A `datetime`/`time` -> HHMMSS (sub-seconds dropped)."""
    return t.hour * 10000 + t.minute * 100 + t.second


def decode_time(n: int) -> tuple[int, int, int]:
    """HHMMSS -> `(hour, minute, second)`."""
    return n // 10000, (n // 100) % 100, n % 100


def encode_datetime(dt: Any) -> int:
    """A datetime as the monotonic YYYYMMDDHHMMSS integer the store orders and
    compares by (see `sort_expr`) — also how a datetime filter value is inlined."""
    return encode_date(dt) * _DATE_SCALE + encode_time(dt)


def decode_datetime(n: int) -> datetime:
    """Inverse of `encode_datetime` (second precision)."""
    return _combine(decode_date(n // _DATE_SCALE), decode_time(n % _DATE_SCALE))


def _combine(d: date, hms: tuple[int, int, int]) -> datetime:
    h, m, s = hms
    return datetime(d.year, d.month, d.day, h, m, s)


# ----- per-column cell mapping ----------------------------------------------

def to_storage(col: Column, value: Any) -> tuple:
    """The **cell tuple** to INSERT for logical `col` = `value` — always one cell
    per `physical_columns(col)`, so a row's cells can be built by extension: a
    datetime -> `(YYYYMMDD, HHMMSS)` (`None` -> `(None, None)`); a date ->
    `(YYYYMMDD,)` (`None` -> `(None,)`); anything else -> `(value,)` unchanged."""
    if col.type == 'datetime':
        if value is None:
            return (None, None)
        return (encode_date(value), encode_time(value))
    if col.type == 'date':
        return (None,) if value is None else (encode_date(value),)
    return (value,)


def from_storage(col: Column, *cells: Any) -> Any:
    """The logical value read back from `col`'s stored cell(s) — the inverse of
    `to_storage`: a `_date`/`_time` pair -> `datetime` (either cell `None` ->
    `None`); a date INT -> `date` (`None` -> `None`); anything else the single
    cell unchanged."""
    if col.type == 'datetime':
        d, t = cells
        if d is None or t is None:
            return None
        return _combine(decode_date(d), decode_time(t))
    if col.type == 'date':
        (d,) = cells
        return None if d is None else decode_date(d)
    (v,) = cells
    return v


def sort_expr(col: Column, table: str) -> str:
    """The SQL expression to ORDER BY / compare `col` of the physical table
    `table` (a `db_name`): for a `datetime`, the combined
    `CAST([t].[<stem>_date] AS BIGINT) * 1000000 + [t].[<stem>_time]` (BIGINT —
    YYYYMMDDHHMMSS overflows INT); for every other type the quoted `[t].[col]`."""
    q = quote(table)
    if col.type == 'datetime':
        d, t = physical_columns(col)
        return (
            f'CAST({q}.{quote(d)} AS BIGINT) * {_DATE_SCALE} + {q}.{quote(t)}'
        )
    return f'{q}.{quote(col.name)}'
