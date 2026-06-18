#!/usr/bin/env python

"""The `Query` class: one run-scoped, bounded SELECT plus its chunk windowing.
See `planners/infinite/dashboard/DESIGN.md` (Read path — `sqlload/`).

A `Query` holds a complete SQL string with `{limit}`/`{offset}` placeholders and
fetches the result in **chunks** of up to `CHUNK_SIZE` rows. The window is a full
chunk wide but **advances in half-chunks** (`CHUNK_SIZE // 2`) so paging back and
forth across a chunk boundary doesn't thrash, and so a display page size that
doesn't divide `CHUNK_SIZE` still lands inside a held chunk. It also exposes the
total `nrows` and the precomputed per-column distinct values (`unique`).

Instances are produced by `Query.build` (added separately) — the constructor is
internal and not meant to be called directly.
"""

from typing import Any

from .. import manifest
from .helpers import Filter, FKLookup

__all__ = ['Query', 'CHUNK_SIZE']

# Max rows held in one chunk. Also the cutoff `build` uses for `unique`: a column
# with more than `CHUNK_SIZE` distinct values stores `None` instead of the set.
CHUNK_SIZE = 10000
# The window advances by half a chunk at a time (see module docstring).
_HALF = CHUNK_SIZE // 2


class Query:
    """A built SELECT over one table, scoped to a run and constrained by the
    table's current filters / FK lookups. Pages its result in half-chunk steps.

    Constructed by `Query.build` with: the reader `cursor`; the full SQL string
    (`{limit}`/`{offset}` placeholders, everything else resolved); the total
    `nrows`; and `uniques`, a map of column name -> its set of distinct values,
    or `None` when that count exceeds `CHUNK_SIZE`."""

    def __init__(
        self, cursor: Any, sql: str, nrows: int,
        uniques: dict[str, set | None],
    ) -> None:
        self._cursor = cursor
        self._sql = sql
        self._nrows = nrows
        self._uniques = uniques
        # Furthest half-chunk step whose window still reaches the last row: the
        # smallest s with s*_HALF + CHUNK_SIZE >= nrows. 0 when everything fits.
        deficit = nrows - CHUNK_SIZE
        self._max_step = 0 if deficit <= 0 else -(-deficit // _HALF)
        # Current window position, in half-chunk steps; -1 = nothing loaded yet.
        self._step = -1
        self._chunk: tuple[tuple, ...] | None = None

    @classmethod
    def build(
        cls, cursor: Any, run_id: int, table: str,
        **constraints: Filter | FKLookup,
    ) -> 'Query':
        """Build a `Query` for `table`, scoped to `run_id` and constrained by the
        per-column `constraints` — each a `Filter` (a `WHERE` term) or an
        `FKLookup` (an `INNER JOIN`). Runs the total-count query and then, per
        displayed column, a distinct-count query followed (only when that count
        is within `CHUNK_SIZE`) by a distinct-values query; columns above the
        cutoff store `None`. Returns the windowing `Query`.

        Columns are table-qualified (an `FKLookup`'s join sub-query exposes
        `run_id`/`ref_col`, which can otherwise collide). Pagination needs a
        stable order, so the SELECT is `ORDER BY` the table's `order_columns`
        (its primary key, or the manifest's `order_by` for a key-less table)."""
        spec = manifest.spec_for_name(table)
        display_cols = [c for c in spec.column_names if c != manifest.RUN_ID]
        col_set = set(display_cols)

        joins: list[str] = []
        conds = [f'`{table}`.`{manifest.RUN_ID}` = {int(run_id)}']
        for col, constraint in constraints.items():
            if col not in col_set:
                raise ValueError(f'{table!r} has no column {col!r} to constrain')
            if isinstance(constraint, FKLookup):
                joins.append(constraint.to_sql_str().format(
                    ftable=table, fcol=col, run_id=int(run_id)))
            elif isinstance(constraint, Filter):
                conds.append(constraint.to_sql_str().format(
                    colname=f'`{table}`.`{col}`'))
            else:
                raise TypeError(
                    f'constraint for {col!r} must be a Filter or FKLookup, got '
                    f'{type(constraint).__name__}')

        from_where = f'FROM `{table}`'
        if joins:
            from_where += ' ' + ' '.join(joins)
        from_where += ' WHERE ' + ' AND '.join(conds)

        cursor.execute('SELECT COUNT(*) ' + from_where)
        nrows = cursor.fetchone()[0]

        uniques: dict[str, set | None] = {}
        for col in display_cols:
            qcol = f'`{table}`.`{col}`'
            cursor.execute(f'SELECT COUNT(DISTINCT {qcol}) ' + from_where)
            if cursor.fetchone()[0] > CHUNK_SIZE:
                uniques[col] = None
            else:
                cursor.execute(f'SELECT DISTINCT {qcol} ' + from_where)
                uniques[col] = {row[0] for row in cursor.fetchall()}

        order_cols = spec.order_columns
        if not order_cols:
            raise ValueError(
                f'table {table!r} has no pk or order_by to paginate by'
            )
        order_sql = ', '.join(f'`{table}`.`{c}`' for c in order_cols)
        cols_sql = ', '.join(f'`{table}`.`{c}`' for c in display_cols)
        sql = (
            f'SELECT {cols_sql} ' + from_where +
            f' ORDER BY {order_sql} LIMIT {{limit}} OFFSET {{offset}}'
        )
        return cls(cursor, sql, nrows, uniques)

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
        exceeds `CHUNK_SIZE` (too many to enumerate up front)."""
        vals = self._uniques[colname]
        return None if vals is None else list(vals)

    def _load(self, step: int) -> tuple[tuple, ...]:
        """Clamp `step` to `[0, max_step]`, and (re-)fetch that window only when
        it differs from the one currently held."""
        target = max(0, min(step, self._max_step))
        if target != self._step or self._chunk is None:
            self._step = target
            self._cursor.execute(
                self._sql.format(limit=CHUNK_SIZE, offset=target * _HALF)
            )
            self._chunk = self._cursor.fetchall()
        return self._chunk
