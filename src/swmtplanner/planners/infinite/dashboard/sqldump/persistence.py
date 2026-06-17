#!/usr/bin/env python

"""Persist a populated `DebugLog` to the MySQL store as one run-tagged row-set.
See `planners/infinite/dashboard/DESIGN.md` (Write path).

The writer **only INSERTs** — never `CREATE`/`ALTER`. It reads rows via the
`DebugLog` read API, lays them out per the `manifest`, and inserts in
FK-topological order inside a single transaction. `import pymysql` is **lazy**
(inside `persist_run`) so the pure helpers here import without the driver
installed.
"""

import math
from typing import TYPE_CHECKING, Any, Iterator

import pandas as pd

from .. import manifest
from ..manifest import TableSpec

if TYPE_CHECKING:
    from swmtplanner.debuglog import DebugLog
    from ..config import ConnConfig

__all__ = ['persist_run', 'PersistenceError']

# Rows per `executemany` call, so the multi-million-row tables never build one
# giant statement / parameter list.
_CHUNK = 5000


class PersistenceError(RuntimeError):
    """Writing the debug log to MySQL failed — e.g. a missing table/column in
    the provisioned schema, a foreign-key violation, or a connection problem.
    The transaction is rolled back, so nothing is persisted."""


# ----- pure helpers (no DB) -----------------------------------------------

def to_sql(value: Any) -> Any:
    """Map one DataFrame cell to a value PyMySQL will store. Missing values
    (`None`, NaN, `NaT`, `pd.NA`) become SQL `NULL`; a `pandas.Timestamp`
    becomes a plain `datetime`; a numpy scalar becomes its native Python value;
    everything else passes through unchanged."""
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


def insert_sql(spec: TableSpec) -> str:
    """The `INSERT INTO <table> (run_id, <cols…>) VALUES (%s, …)` statement for
    `spec`, every identifier backticked so reserved words (`rank`, `desc`,
    `start`, `end`, `value`) are safe."""
    cols = (manifest.RUN_ID,) + spec.column_names
    collist = ', '.join(f'`{c}`' for c in cols)
    placeholders = ', '.join(['%s'] * len(cols))
    return f'INSERT INTO `{spec.name}` ({collist}) VALUES ({placeholders})'


def project_rows(
    debuglog: 'DebugLog', spec: TableSpec, run_id: int,
) -> Iterator[tuple]:
    """Yield one `(run_id, *cells)` tuple per row of `spec`'s source `DebugLog`
    table — cells in the spec's column order, mapped via `to_sql`. A keyed
    table's primary key (its DataFrame index) is exposed as a column first, then
    columns are selected by name, so this is decoupled from `get_df`'s
    index/column split. Empty tables yield nothing."""
    df = debuglog.get_df(spec.name)
    if df.index.name is not None:                # keyed: expose the PK as a column
        df = df.reset_index()
    cols = list(spec.column_names)
    for row in df[cols].itertuples(index=False, name=None):
        yield (run_id,) + tuple(to_sql(v) for v in row)


# ----- the writer ----------------------------------------------------------

def persist_run(
    debuglog: 'DebugLog', conn: 'ConnConfig', *,
    start_date: Any, total_score: Any, n_unmet: Any,
    label: str | None = None, notes: str | None = None,
) -> int:
    """Persist `debuglog` to MySQL as a new run and return its `run_id`.

    Connects with the **writer** `ConnConfig` `conn`, inserts the `runs`
    metadata row (the server assigns `run_id` and `created_at`), then
    bulk-inserts every manifest table's run-tagged rows in FK-topological order —
    all in one transaction, committed on success and rolled back on any failure.
    Raises `PersistenceError` on a connection problem, schema mismatch, or FK
    violation; nothing is persisted in that case."""
    import pymysql                                # lazy: only needed to persist

    try:
        connection = pymysql.connect(
            host=conn.host, port=conn.port, user=conn.user,
            password=conn.password, database=conn.database, autocommit=False,
        )
    except Exception as exc:
        raise PersistenceError(f'could not connect to MySQL: {exc}') from exc

    try:
        with connection.cursor() as cur:
            cur.execute(
                'INSERT INTO `runs` '
                '(`start_date`, `total_score`, `n_unmet`, `label`, `notes`) '
                'VALUES (%s, %s, %s, %s, %s)',
                (to_sql(start_date), to_sql(total_score),
                 to_sql(n_unmet), label, notes),
            )
            run_id = cur.lastrowid
            for spec in manifest.TABLES:
                print(f'Dumping {spec.name}...')
                _insert_table(cur, debuglog, spec, run_id)
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
            f'failed writing table {spec.name!r} (is the schema '
            f'provisioned as DESIGN.md specifies?): {exc}'
        ) from exc
