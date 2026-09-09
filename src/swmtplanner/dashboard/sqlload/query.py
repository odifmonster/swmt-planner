#!/usr/bin/env python

"""The `Query` class: one run-scoped, bounded T-SQL SELECT plus its chunk
windowing. See `swmtplanner/dashboard/DESIGN.md` (Read path — `sqlload/`).

A `Query` holds a complete SQL string with `{offset}`/`{limit}` placeholders
(`OFFSET … ROWS FETCH NEXT … ROWS ONLY`) and fetches the result in **chunks** of
up to `CHUNK_SIZE` rows. The window is a full chunk wide but **advances in
half-chunks** (`CHUNK_SIZE // 2`) so paging back and forth across a chunk
boundary doesn't thrash, and so a display page size that doesn't divide
`CHUNK_SIZE` still lands inside a held chunk. It also exposes the total `nrows`
and the lazily-computed per-column distinct values (`unique`).

**Physical -> logical.** The store keeps each `datetime` column as an INT
`_date`/`_time` pair and each `date` as a YYYYMMDD INT (see `storage.py`). The
SELECT lists the *physical* columns, so a fetched tuple is wider than the
display row; `Query` recombines each temporal column via `storage.from_storage`
as it loads a chunk, so the chunks it hands out — and everything above it — are
logical, display-shaped rows. Ordering and comparisons use
`storage.sort_expr`, and temporal filter values are encoded to the same
integers, so nothing here needs two-column logic.

Instances are produced by `Query.build` — the constructor is internal and not
meant to be called directly.
"""

from datetime import date, datetime
from typing import Any, Callable, Sequence

from ..manifest import RUN_ID, Column, TableSpec
from .. import storage
from .helpers import Filter, FKLookup

__all__ = ['Query', 'CHUNK_SIZE']

# Max rows held in one chunk. Also the cutoff `build` uses for `unique`: a column
# with more than `CHUNK_SIZE` distinct values stores `None` instead of the set.
CHUNK_SIZE = 10000
# The window advances by half a chunk at a time (see module docstring).
_HALF = CHUNK_SIZE // 2


def _identity(v: Any) -> Any:
    return v


def _decoder(col: Column) -> Callable[[Any], Any]:
    """How a distinct value read back for `col` becomes a logical value: the
    store's combined integer -> `datetime`, a YYYYMMDD INT -> `date`, else as-is.
    `NULL` stays `None`."""
    if col.type == 'datetime':
        return lambda v: None if v is None else storage.decode_datetime(v)
    if col.type == 'date':
        return lambda v: None if v is None else storage.decode_date(v)
    return _identity


def _encode_filter(f: Filter, col: Column) -> Filter:
    """`f` with any datetime / date values in its rule encoded to the integers
    the store compares by (so the filter text works against `sort_expr`).
    Non-temporal columns, already-encoded values (ints), `None`, and pattern
    rules pass through untouched; a malformed rule is left for `to_sql_str` to
    reject."""
    if col.type == 'datetime':
        enc = storage.encode_datetime
    elif col.type == 'date':
        enc = storage.encode_date
    else:
        return f

    def e(v: Any) -> Any:
        return enc(v) if isinstance(v, (datetime, date)) else v

    if f.kind in ('selection', 'exclusion') and isinstance(f.rule, (set, frozenset)):
        return Filter(f.kind, {e(v) for v in f.rule})
    if f.kind == 'range' and isinstance(f.rule, tuple) and len(f.rule) == 2:
        return Filter(f.kind, (e(f.rule[0]), e(f.rule[1])))
    return f


class Query:
    """A built SELECT over one table, scoped to a run and constrained by the
    table's current filters / FK lookups. Pages its result in half-chunk steps
    and recombines the store's physical temporal columns into logical values.

    Constructed by `Query.build` with: the reader `cursor`; the full SQL string
    (`{offset}`/`{limit}` placeholders, everything else resolved); the total
    `nrows`; `distinct_queries`, a map of column name -> its `(count-distinct
    SQL, distinct-values SQL, decoder)` triple, run **lazily** by `unique`; and
    `columns`, the display `Column` specs in logical order (drives the
    physical -> logical recombination of fetched rows)."""

    def __init__(
        self, cursor: Any, sql: str, nrows: int,
        distinct_queries: dict[str, tuple[str, str, Callable[[Any], Any]]],
        columns: Sequence[Column],
    ) -> None:
        self._cursor = cursor
        self._sql = sql
        self._nrows = nrows
        # column -> (count-distinct SQL, distinct-values SQL, decoder): on demand.
        self._distinct_q = distinct_queries
        # column -> resolved distinct set (or None if over CHUNK_SIZE): cached
        # after the first `unique` call.
        self._uniques: dict[str, set | None] = {}
        # Display columns and, per column, how many physical cells it occupies.
        self._columns = tuple(columns)
        self._widths = [len(storage.physical_columns(c)) for c in self._columns]
        # Furthest half-chunk step whose window still reaches the last row: the
        # smallest s with s*_HALF + CHUNK_SIZE >= nrows. 0 when everything fits.
        deficit = nrows - CHUNK_SIZE
        self._max_step = 0 if deficit <= 0 else -(-deficit // _HALF)
        # Current window position, in half-chunk steps; -1 = nothing loaded yet.
        self._step = -1
        self._chunk: tuple[tuple, ...] | None = None

    @classmethod
    def build(
        cls, cursor: Any, run_id: int, spec: TableSpec,
        **constraints: Filter | FKLookup,
    ) -> 'Query':
        """Build a `Query` for the table described by `spec`, scoped to `run_id`
        and constrained by the per-column `constraints` — each a `Filter` (a
        `WHERE` term) or an `FKLookup` (an `INNER JOIN`). Runs **only** the
        total-count query; the per-column distinct queries are *prepared as SQL
        strings* and run lazily by `unique` (so opening a table is cheap).
        Returns the windowing `Query`.

        The `spec` is supplied by the caller (which holds the planner's manifest),
        so this stays schema-agnostic. SQL text uses the spec's **physical**
        `db_name` and bracket-quotes every identifier. Columns are
        table-qualified (an `FKLookup`'s join sub-query exposes
        `run_id`/`ref_col`, which can otherwise collide). The SELECT lists each
        display column's **physical** column(s) (a `datetime`'s `_date`/`_time`
        pair); ordering, filtering and distinct-counting go through
        `storage.sort_expr`, and temporal filter values are encoded first, so a
        temporal column is always compared as one integer. Pagination needs a
        stable order, so the SELECT is `ORDER BY` the table's `order_columns`
        (its `order_by` if set, else its primary key) with `OFFSET … ROWS FETCH
        NEXT … ROWS ONLY`."""
        table = spec.db_name
        qt = storage.quote(table)
        display = [c for c in spec.columns if c.name != RUN_ID]
        by_name = {c.name: c for c in display}

        def cmp_expr(col: Column) -> str:
            return storage.sort_expr(col, table)

        joins: list[str] = []
        conds = [f'{qt}.{storage.quote(RUN_ID)} = {int(run_id)}']
        for col, constraint in constraints.items():
            if col not in by_name:
                raise ValueError(f'{spec.name!r} has no column {col!r} to constrain')
            if isinstance(constraint, FKLookup):
                joins.append(constraint.to_sql_str().format(
                    ftable=table, fcol=col, run_id=int(run_id)))
            elif isinstance(constraint, Filter):
                encoded = _encode_filter(constraint, by_name[col])
                conds.append(
                    encoded.to_sql_str().format(colname=cmp_expr(by_name[col])))
            else:
                raise TypeError(
                    f'constraint for {col!r} must be a Filter or FKLookup, got '
                    f'{type(constraint).__name__}')

        from_where = f'FROM {qt}'
        if joins:
            from_where += ' ' + ' '.join(joins)
        from_where += ' WHERE ' + ' AND '.join(conds)

        cursor.execute('SELECT COUNT(*) ' + from_where)
        nrows = cursor.fetchone()[0]

        # Prepare (don't run) the per-column distinct queries; `unique` runs them
        # on demand, decodes the values, and caches the result.
        distinct_q: dict[str, tuple[str, str, Callable[[Any], Any]]] = {}
        for c in display:
            expr = cmp_expr(c)
            distinct_q[c.name] = (
                f'SELECT COUNT(DISTINCT {expr}) ' + from_where,
                f'SELECT DISTINCT {expr} ' + from_where,
                _decoder(c),
            )

        order_cols = spec.order_columns
        if not order_cols:
            raise ValueError(
                f'table {spec.name!r} has no pk or order_by to paginate by'
            )
        order_sql = ', '.join(cmp_expr(by_name[c]) for c in order_cols)
        cols_sql = ', '.join(
            f'{qt}.{storage.quote(p)}'
            for c in display for p in storage.physical_columns(c)
        )
        sql = (
            f'SELECT {cols_sql} ' + from_where
            + f' ORDER BY {order_sql}'
            + ' OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY'
        )
        return cls(cursor, sql, nrows, distinct_q, display)

    @property
    def nrows(self) -> int:
        """Total rows the query returns with no limit applied."""
        return self._nrows

    @property
    def row_offset(self) -> int:
        """Absolute offset (in rows, not half-chunks) of the current chunk's
        first row from the start of the unbounded result, so a `Table` can place
        a displayed row absolutely. 0 before the first chunk is loaded."""
        return max(self._step, 0) * _HALF

    def next_chunk(self) -> tuple[tuple, ...]:
        """Advance the window one half-chunk and return the chunk's rows. The
        first call (nothing loaded yet) returns the first chunk; at the end the
        window holds and the same rows are returned."""
        return self._load(self._step + 1)

    def prev_chunk(self) -> tuple[tuple, ...]:
        """Retreat the window one half-chunk and return the chunk's rows. At the
        start the window holds at offset 0."""
        return self._load(self._step - 1)

    def unique(self, colname: str) -> list | None:
        """The distinct values in `colname` as a list, or `None` if that count
        exceeds `CHUNK_SIZE`. Computed **lazily** on the first call (a
        count-distinct query, then a distinct-values query only when within the
        cutoff), decoded to logical values (a temporal column's combined integer
        -> `datetime` / `date`), and cached thereafter — so building a `Query`
        runs no per-column queries. Raises `KeyError` for a non-column."""
        if colname not in self._uniques:
            count_sql, values_sql, decode = self._distinct_q[colname]
            self._cursor.execute(count_sql)
            if self._cursor.fetchone()[0] > CHUNK_SIZE:
                self._uniques[colname] = None
            else:
                self._cursor.execute(values_sql)
                self._uniques[colname] = {
                    decode(r[0]) for r in self._cursor.fetchall()
                }
        vals = self._uniques[colname]
        return None if vals is None else list(vals)

    def _to_logical(self, row: Sequence[Any]) -> tuple:
        """One fetched (physical) row -> the logical display row: each column
        takes its physical cell(s) in order and recombines via `from_storage`."""
        row = tuple(row)                              # pyodbc.Row -> plain tuple
        out, i = [], 0
        for col, width in zip(self._columns, self._widths):
            out.append(storage.from_storage(col, *row[i:i + width]))
            i += width
        return tuple(out)

    def _load(self, step: int) -> tuple[tuple, ...]:
        """Clamp `step` to `[0, max_step]`, and (re-)fetch that window only when
        it differs from the one currently held; fetched rows are recombined to
        logical rows."""
        target = max(0, min(step, self._max_step))
        if target != self._step or self._chunk is None:
            self._step = target
            self._cursor.execute(
                self._sql.format(limit=CHUNK_SIZE, offset=target * _HALF)
            )
            self._chunk = tuple(
                self._to_logical(r) for r in self._cursor.fetchall()
            )
        return self._chunk
