#!/usr/bin/env python

"""Persist a populated `DebugLog` to the SQL Server store as one run-tagged
row-set. See `planners/infinite/DESIGN.md` (Debug-log persistence).

The writer **only INSERTs** — never `CREATE`/`ALTER`. It reads rows via the
`DebugLog` read API and lays them out per the `manifest` **and the dashboard's
storage mapping**: physical `knit_`-prefixed table names (`TableSpec.db_name`),
each `datetime` column stored as an INT `_date`/`_time` pair and each `date` as
a YYYYMMDD INT (`storage.to_storage`). Rows are inserted in FK-topological order
inside a single transaction. It connects through the dashboard's
`config.connect` (pyodbc), whose driver import is lazy, so the pure helpers here
import without the driver installed.
"""

import math
from datetime import datetime
from typing import TYPE_CHECKING, Any, Iterator

import pandas as pd

from swmtplanner.dashboard import storage
from swmtplanner.dashboard.config import connect

from .. import manifest
from ..manifest import TableSpec

if TYPE_CHECKING:
    from swmtplanner.debuglog import DebugLog
    from swmtplanner.dashboard.config import ConnConfig

__all__ = ['persist_run', 'PersistenceError']

# Rows per `executemany` call, so the multi-million-row tables never build one
# giant statement / parameter list.
_CHUNK = 5000


class PersistenceError(RuntimeError):
    """Writing the debug log to SQL Server failed — e.g. a missing table/column
    in the provisioned schema, a foreign-key violation, or a connection problem.
    The transaction is rolled back, so nothing is persisted."""


# ----- pure helpers (no DB) -----------------------------------------------

def to_sql(value: Any) -> Any:
    """Normalise one DataFrame cell to a plain Python value. Missing values
    (`None`, NaN, `NaT`, `pd.NA`) become `None` (SQL `NULL`); a
    `pandas.Timestamp` becomes a plain `datetime`; a numpy scalar becomes its
    native Python value; everything else passes through unchanged. The storage
    mapping (`storage.to_storage`) is applied *after* this, per column."""
    if value is None:
        return None
    if isinstance(value, float):                 # incl. numpy float64 (subclass)
        return None if math.isnan(value) else float(value)
    # pd.isna on a scalar returns a bool (never an array here).
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    item = getattr(value, 'item', None)          # numpy scalar -> native python
    if callable(item) and not isinstance(value, str):
        return item()
    return value


def _physical_columns(spec: TableSpec) -> list[str]:
    """`spec`'s store column names in order: each `datetime` expanded to its
    `_date`/`_time` pair, everything else as itself."""
    return [p for c in spec.columns for p in storage.physical_columns(c)]


def insert_sql(spec: TableSpec) -> str:
    """The `INSERT INTO [<db_name>] ([run_id], <physical columns…>) VALUES (?, …)`
    statement for `spec` — **`?` qmark placeholders**, every identifier
    bracket-quoted (reserved words such as `rank`, `desc`, `value` are safe),
    and each `datetime` column expanded to its `_date`/`_time` pair (a `date` is
    one INT column)."""
    cols = [manifest.RUN_ID] + _physical_columns(spec)
    collist = ', '.join(storage.quote(c) for c in cols)
    placeholders = ', '.join(['?'] * len(cols))
    return (
        f'INSERT INTO {storage.quote(spec.db_name)} ({collist}) '
        f'VALUES ({placeholders})'
    )


def project_rows(
    debuglog: 'DebugLog', spec: TableSpec, run_id: int,
) -> Iterator[tuple]:
    """Yield one `(run_id, *storage_cells)` tuple per row of `spec`'s source
    `DebugLog` table — cells in the spec's column order, each normalised by
    `to_sql` and then mapped through `storage.to_storage`, so a `datetime`
    contributes **two** INT cells and a `date` one; the tuple therefore matches
    `insert_sql`'s physical column list. A keyed table's primary key (its
    DataFrame index) is exposed as a column first, then columns are selected by
    name, so this is decoupled from `get_df`'s index/column split. Empty tables
    yield nothing."""
    df = debuglog.get_df(spec.name)
    if df.index.name is not None:                # keyed: expose the PK as a column
        df = df.reset_index()
    cols = list(spec.column_names)
    for row in df[cols].itertuples(index=False, name=None):
        cells: list = [run_id]
        for col, value in zip(spec.columns, row):
            cells.extend(storage.to_storage(col, to_sql(value)))
        yield tuple(cells)


# ----- the writer ----------------------------------------------------------

def persist_run(
    debuglog: 'DebugLog', conn: 'ConnConfig', *,
    start_date: Any, total_score: Any, n_unmet: Any,
    label: str | None = None, notes: str | None = None,
) -> int:
    """Persist `debuglog` to SQL Server as a new run and return its `run_id`.

    Connects with the **writer** `ConnConfig` `conn` (pyodbc, one transaction),
    inserts the `knit_runs` registry row — the server assigns `run_id`
    (`OUTPUT INSERTED`); `created_at` is supplied from the wall clock as its
    `_date`/`_time` pair and `start_date` as a YYYYMMDD int — then bulk-inserts
    every manifest table's run-tagged rows in FK-topological order with
    `fast_executemany`; committed on success and rolled back on any failure.
    Raises `PersistenceError` on a connection problem, schema mismatch, or FK
    violation; nothing is persisted in that case."""
    try:
        connection = connect(conn, autocommit=False)
    except Exception as exc:
        raise PersistenceError(f'could not connect to SQL Server: {exc}') from exc

    try:
        cur = connection.cursor()
        try:
            if hasattr(cur, 'fast_executemany'):
                cur.fast_executemany = True
            run_id = _insert_run(
                cur, start_date=start_date, total_score=total_score,
                n_unmet=n_unmet, label=label, notes=notes,
            )
            for spec in manifest.TABLES:
                print(f'Dumping {spec.name}...')
                _insert_table(cur, debuglog, spec, run_id)
        finally:
            cur.close()
        connection.commit()
        return run_id
    except PersistenceError:
        connection.rollback()
        raise
    except Exception as exc:
        connection.rollback()
        raise PersistenceError(f'failed to persist debug log: {exc}') from exc
    finally:
        connection.close()


def _insert_run(
    cur, *, start_date: Any, total_score: Any, n_unmet: Any,
    label: str | None, notes: str | None,
) -> int:
    """INSERT the registry row for a new run and return its server-assigned
    `run_id` via `OUTPUT INSERTED`. Built from the `runs` spec so the storage
    mapping applies: `created_at` (the wall clock now) becomes its `_date`/`_time`
    pair, `start_date` a YYYYMMDD int; `run_id` is the IDENTITY and is not
    supplied."""
    spec = manifest.RUNS
    values = {
        'created_at': datetime.now(),
        'start_date': to_sql(start_date),
        'total_score': to_sql(total_score),
        'n_unmet': to_sql(n_unmet),
        'label': label,
        'notes': notes,
    }
    cols = [c for c in spec.columns if c.name != 'run_id']
    physical = [p for c in cols for p in storage.physical_columns(c)]
    cells = [cell for c in cols for cell in storage.to_storage(c, values[c.name])]
    sql = (
        f'INSERT INTO {storage.quote(spec.db_name)} ('
        + ', '.join(storage.quote(p) for p in physical)
        + f') OUTPUT INSERTED.{storage.quote("run_id")} VALUES ('
        + ', '.join(['?'] * len(physical)) + ')'
    )
    cur.execute(sql, cells)
    return int(cur.fetchone()[0])


def _insert_table(cur, debuglog: 'DebugLog', spec: TableSpec, run_id: int) -> None:
    """Bulk-insert `spec`'s run-tagged rows in chunks via `executemany`. Wraps
    any failure in `PersistenceError` naming the table."""
    sql = insert_sql(spec)
    chunk: list[tuple] = []
    nrows = debuglog.get_nrows(spec.name)
    i = 0
    try:
        for row in project_rows(debuglog, spec, run_id):
            print(f'{i+1} of {nrows} loaded', end='\r')
            i += 1
            chunk.append(row)
            if len(chunk) >= _CHUNK:
                cur.executemany(sql, chunk)
                chunk = []
        if chunk:
            cur.executemany(sql, chunk)
        print()
    except PersistenceError:
        raise
    except Exception as exc:
        raise PersistenceError(
            f'failed writing table {spec.name!r} (physical {spec.db_name!r} — '
            f'is the schema provisioned as DESIGN.md specifies?): {exc}'
        ) from exc
