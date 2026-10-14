#!/usr/bin/env python

"""Loaders: every source into a dataframe of a declared `Table` shape.

Two sources — the plant's SQL Server, reached over `pyodbc`
(`load_sql_config` + `run_query`), and local CSV files (`read_csv`) — and
one rule shared by both: **columns are matched by name, not by position**.
A loader reads the source's column names (the cursor description, the CSV
header), picks for each `Column` the source column named by its `source`
(`src_name`, else `name`), drops anything else, reorders the rows into the
table's declared order and hands them to `Table.from_tuples`. A declared
column the source lacks raises `SourceColumnError`.

The connection config is a `<key>=<value>` text file (comments start with
`#`; a value containing `=` is quoted), named explicitly or by the
`SQLCONFIG` environment variable. `HOST` / `PORT` / `DATABASE` / `UID` /
`PWD` are required; `TrustServerCertificate` / `Encrypt` are optional and
have **no** default — absent means not set. The ODBC driver is the fixed
`DRIVER` constant. `import pyodbc` is lazy so the module imports without the
driver installed.

`get_file_name` names a dated local file the way the planner's outputs are
named (`<stem>_<YYYYMMDD>.<ext>`).

See `planners/infinite/swmtio/DESIGN.md` ("Loading sources").
"""

import csv
import os
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd

from .translate import Table

# Environment variable naming the connection config file.
SQLCONFIG_ENV = 'SQLCONFIG'
# The ODBC driver the connection string names (not a config key).
DRIVER = 'ODBC Driver 17 for SQL Server'

REQUIRED_KEYS: tuple[str, ...] = ('HOST', 'PORT', 'DATABASE', 'UID', 'PWD')
OPTIONAL_KEYS: tuple[str, ...] = ('TrustServerCertificate', 'Encrypt')

DATE_STAMP_FMT = '%Y%m%d'

# Cell texts `read_csv` reads as null: empty, and the literal `None` the
# plant's status files write for a missing value.
NA_VALUES: tuple[str, ...] = ('', 'None')


class SQLConfigError(ValueError):
    """The connection config could not be read: no file named (no `fpath` and
    `SQLCONFIG` unset), a missing file, a malformed line, or a required key
    missing or empty."""


class SourceColumnError(ValueError):
    """A source (result set or file) lacks a column its `Table` declares."""


# --- the connection config -------------------------------------------------

def _unquote(value: str) -> str:
    """Strip one matching pair of surrounding quotes (`"…"` or `'…'`)."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def parse_sql_config(lines: Iterable[str], source: str = '<config>') -> dict[str, str]:
    """Parse `<key>=<value>` lines into a dict. Blank lines and lines whose
    first non-blank character is `#` are skipped; whitespace around the key
    and value is stripped; the value is everything after the first `=`,
    with one pair of surrounding quotes removed. A line with no `=` or an
    empty key raises `SQLConfigError`. Keys are kept as written."""
    out: dict[str, str] = {}
    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            raise SQLConfigError(f'{source}:{lineno}: expected <key>=<value>, got {raw!r}')
        key, _, value = line.partition('=')
        key = key.strip()
        if not key:
            raise SQLConfigError(f'{source}:{lineno}: empty key in {raw!r}')
        out[key] = _unquote(value.strip())
    return out


def load_sql_config(fpath: str | None = None) -> dict[str, str]:
    """Read the connection config at `fpath` (default: the file named by
    `SQLCONFIG`) and verify every required key is present and non-empty.
    Optional keys pass through when present; other keys are returned
    untouched."""
    if fpath is None:
        fpath = os.environ.get(SQLCONFIG_ENV)
        if not fpath:
            raise SQLConfigError(
                f'no config path given and {SQLCONFIG_ENV} is not set')
    path = Path(fpath)
    if not path.is_file():
        raise SQLConfigError(f'SQL config file not found: {fpath}')
    with path.open(encoding='utf-8') as fh:
        cfg = parse_sql_config(fh, source=str(path))
    missing = [k for k in REQUIRED_KEYS if not cfg.get(k)]
    if missing:
        raise SQLConfigError(
            f'{path}: missing or empty required key(s): {", ".join(missing)}')
    return cfg


def connection_string(cfg: dict[str, str]) -> str:
    """The pyodbc connection string for a verified config: the fixed
    `DRIVER`, `SERVER=<HOST>,<PORT>`, the database and login, and the
    optional ODBC settings only when the config names them."""
    parts = [
        f'DRIVER={{{DRIVER}}}',
        f'SERVER={cfg["HOST"]},{cfg["PORT"]}',
        f'DATABASE={cfg["DATABASE"]}',
        f'UID={cfg["UID"]}',
        f'PWD={cfg["PWD"]}',
    ]
    for key in OPTIONAL_KEYS:
        if key in cfg:
            parts.append(f'{key}={cfg[key]}')
    return ';'.join(parts) + ';'


def _connect(conn_str: str) -> Any:
    """Open the pyodbc connection (lazy import; patched in tests)."""
    import pyodbc
    return pyodbc.connect(conn_str)


# --- matching a source to a table -----------------------------------------

def align_rows(
    source_names: Sequence[str],
    rows: Iterable[Sequence[Any]],
    tbl: Table,
    source: str,
) -> list[tuple]:
    """Reorder `rows` (each positionally matching `source_names`) into
    `tbl`'s declared column order, picking each column by its source name
    and dropping the rest. A declared column absent from `source_names`
    raises `SourceColumnError`."""
    index = {name: i for i, name in enumerate(source_names)}
    missing = [s for s in tbl.sources if s not in index]
    if missing:
        raise SourceColumnError(
            f'{source}: table {tbl.name!r} declares column(s) not in the source: '
            f'{", ".join(repr(m) for m in missing)}; source has '
            f'{", ".join(repr(n) for n in source_names)}')
    picks = [index[s] for s in tbl.sources]
    return [tuple(row[i] for i in picks) for row in rows]


# --- the loaders -----------------------------------------------------------

def run_query(query_str: str, tbl: Table, cfgpath: str | None = None) -> pd.DataFrame:
    """Run `query_str` — a complete statement, dates already rendered by
    `SQLQuery.get_query` — against the database named by the config at
    `cfgpath` (default: `SQLCONFIG`), match the result's columns to `tbl`
    by name, and return `tbl.from_tuples` over the reordered rows. pyodbc
    errors propagate as they are."""
    conn = _connect(connection_string(load_sql_config(cfgpath)))
    try:
        cursor = conn.cursor()
        cursor.execute(query_str)
        names = [d[0] for d in cursor.description]
        rows = [tuple(r) for r in cursor.fetchall()]
    finally:
        conn.close()
    return tbl.from_tuples(align_rows(names, rows, tbl, source='query'))


def read_csv(fpath: str, tbl: Table, sep: str = ',',
             na_values: Sequence[str] = NA_VALUES) -> pd.DataFrame:
    """Read the delimited file at `fpath`, its first row the header, match
    the header to `tbl` by name and return `tbl.from_tuples` over the data
    rows in file order. No type inference: every cell reaches the table as
    the string in the file, except a cell equal to one of `na_values`
    (default: empty, or the literal `None` the plant's status files write),
    which becomes `None`. A file with no header row has no columns, so any
    declared column raises `SourceColumnError`."""
    na = set(na_values)
    with open(fpath, newline='', encoding='utf-8-sig') as fh:
        reader = csv.reader(fh, delimiter=sep)
        header = next(reader, None)
        names = [] if header is None else [h.strip() for h in header]
        rows = [tuple(None if cell in na else cell for cell in row)
                for row in reader if row]
    return tbl.from_tuples(align_rows(names, rows, tbl, source=str(fpath)))


# --- file names ------------------------------------------------------------

def get_file_name(stem: str, ext: str, dt: date | None = None,
                  is_dated: bool = True) -> str:
    """`<stem>_<YYYYMMDD>.<ext>` for `dt` (default today) when `is_dated`,
    else `<stem>.<ext>`. `ext` is given without its dot. Builds the bare
    name only — no directory, no file."""
    if not is_dated:
        return f'{stem}.{ext}'
    stamp = (date.today() if dt is None else dt).strftime(DATE_STAMP_FMT)
    return f'{stem}_{stamp}.{ext}'
