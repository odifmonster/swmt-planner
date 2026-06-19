#!/usr/bin/env python

"""The `Table` and `Row` classes: the stateful, app-facing read model.
See `swmtplanner/dashboard/DESIGN.md` (Read path — `sqlload/`).

A `Table` wraps one manifest table, owns its `Query`, and serves the app fixed
display pages (`next_page` / `prev_page`) of `Row` objects, repositioning the
`Query`'s chunk window underneath as paging crosses it. A `Row` is a thin view
over one record's value tuple that can read columns by name and (for a keyed
table) toggle its selection in the owning `Table`.
"""

from typing import Any

from ..manifest import RUN_ID, TableSpec
from .query import Query, CHUNK_SIZE
from .helpers import Filter, FKLookup, FilterKind

__all__ = ['Table', 'Row']

# A display page must fit inside a single chunk so the half-chunk stepping always
# contains it (see query.py); this is the largest page `set_page_size` allows.
_MAX_PAGE_SIZE = CHUNK_SIZE // 2


class Row:
    """One displayed record: the value tuple plus column-name access and, for a
    keyed table, selection toggling. Built by its `Table`; `data` columns are in
    the table's display order (the manifest columns, minus `run_id`)."""

    def __init__(self, table: 'Table', data: tuple) -> None:
        self._table = table
        self._data = data

    @property
    def data(self) -> tuple:
        """The row's values, in the table's display-column order."""
        return self._data

    @property
    def pk_col(self) -> str | None:
        """The table's primary-key column, or `None` for a key-less table."""
        pk = self._table.schema.pk
        return pk[0] if pk else None

    @property
    def selected(self) -> bool:
        """Whether this row is selected — always `False` for a key-less table."""
        col = self.pk_col
        if col is None:
            return False
        return self.get(col) in self._table._selected_keys

    def get(self, column: str) -> Any:
        """The value of `column` in this row (`KeyError` if not a column)."""
        return self._data[self._table._col_index(column)]

    def select(self) -> None:
        """Mark this row selected. Raises if the table is key-less."""
        self._table._add_selection(self._require_key())

    def deselect(self) -> None:
        """Clear this row's selection. Raises if the table is key-less."""
        self._table._remove_selection(self._require_key())

    def _require_key(self) -> Any:
        col = self.pk_col
        if col is None:
            raise TypeError(
                f'rows of key-less table {self._table.schema.name!r} '
                f'cannot be selected'
            )
        return self.get(col)


class Table:
    """The app-facing view of one manifest table for a run: owns the `Query`,
    holds one fetched chunk and the in-chunk offset of the displayed page, and
    tracks the set of selected primary keys. Constructed with the table's
    `schema` (the only public attribute), a reader `cursor`, and the `run_id`."""

    # Rows per display page — the app's visible page size. A private class
    # attribute: universal across tables, changed only through `set_page_size`
    # (e.g. on a window resize), which validates the new value.
    _page_size: int = 100

    @classmethod
    def set_page_size(cls, n: int) -> None:
        """Set the display page size for **all** tables (e.g. on a window
        resize). Raises `ValueError` unless `n` is an int in
        `[1, CHUNK_SIZE // 2]` — the upper bound keeps a page inside a single
        chunk so paging never outruns the held window."""
        if not isinstance(n, int) or n < 1 or n > _MAX_PAGE_SIZE:
            raise ValueError(
                f'page size must be an int in [1, {_MAX_PAGE_SIZE}], got {n!r}'
            )
        cls._page_size = n

    @property
    def page_size(self) -> int:
        """The current display page size (set via `set_page_size`)."""
        return self._page_size

    def __init__(self, schema: TableSpec, cursor: Any, run_id: int) -> None:
        self._schema = schema
        self._cursor = cursor
        self._run_id = run_id
        self._display_cols = [
            c for c in schema.column_names if c != RUN_ID
        ]
        self._col_pos = {c: i for i, c in enumerate(self._display_cols)}
        self._fk_map = {fk.column: fk for fk in schema.fks}
        self._selected_keys: set = set()
        self._conds = {c: None for c in self._display_cols}
        self._query = Query.build(cursor, run_id, schema)
        # The currently-held chunk (None until the first page is loaded) and the
        # offset, within that chunk, of the first displayed row.
        self._chunk: tuple[tuple, ...] | None = None
        self._offset = 0

    @property
    def schema(self) -> TableSpec:
        return self._schema

    @property
    def nrows(self) -> int:
        """Total rows the current query matches."""
        return self._query.nrows

    def unique(self, colname: str) -> list | None:
        """The distinct values in `colname` for the current query (lazy + cached
        by the `Query`), or `None` when there are too many (> `CHUNK_SIZE`) to
        enumerate — for a filter UI's selection/exclusion options."""
        return self._query.unique(colname)

    @property
    def selected_keys(self) -> set:
        """A copy of the selected primary-key values (mutated via
        `Row.select` / `Row.deselect`)."""
        return set(self._selected_keys)

    @property
    def displayed_range(self) -> tuple[int, int]:
        """The absolute `[start, end)` row indices currently displayed (`(0, 0)`
        before the first page is loaded)."""
        if self._chunk is None:
            return (0, 0)
        start = self._query.row_offset + self._offset
        count = len(self._chunk[self._offset:self._offset + self.page_size])
        return (start, start + count)

    def next_page(self) -> list[Row]:
        """The next display page (the first page if none is loaded yet); holds
        on the last page at the end."""
        target = 0 if self._chunk is None else self._page_start() + self.page_size
        return self._goto(target)

    def prev_page(self) -> list[Row]:
        """The previous display page (the first page if none is loaded yet);
        holds on the first page at the start."""
        target = 0 if self._chunk is None else self._page_start() - self.page_size
        return self._goto(target)

    def reload_page(self) -> list[Row]:
        """Re-display the current page **from the same first row**, re-sized to
        the current `page_size`. Use after `set_page_size` (e.g. a window
        resize): the start holds, only the displayed range changes."""
        if self._chunk is None:
            return self._goto(0)
        if self._query.nrows == 0:
            self._offset = 0
            return []
        return self._render(self._page_start())

    def apply_filter_to(self, col: str, kind: FilterKind, rule: Any) -> None:
        self._ensure_col(col)
        self._conds[col] = Filter(kind, rule)
        self._rebuild_query()
    
    def remove_filter(self, col: str) -> None:
        self._ensure_col(col)
        self._conds[col] = None
        self._rebuild_query()
    
    def apply_fk_lookup(self, fkcol: str, values: set) -> None:
        self._ensure_col(fkcol)
        if fkcol not in self._fk_map:
            raise KeyError(f'column {fkcol!r} is not a foreign key')
        self._conds[fkcol] = FKLookup(self._fk_map[fkcol].ref_table,
                                      self._fk_map[fkcol].ref_column,
                                      values)
        self._rebuild_query()
    
    # ----- query re-building --------------------------------------------
    
    def _ensure_col(self, col: str) -> None:
        if col not in self._conds:
            raise KeyError(f'table {self.schema.name!r} has no column {col!r}')

    def _rebuild_query(self) -> None:
        used_conds = {k: v for k, v in self._conds.items() if v is not None}
        self._query = Query.build(self._cursor, self._run_id, self._schema,
                                  **used_conds)
        self._chunk = None
        self._offset = 0
        self._selected_keys = set()

    # ----- selection (called by Row) ------------------------------------

    def _add_selection(self, key: Any) -> None:
        self._selected_keys.add(key)

    def _remove_selection(self, key: Any) -> None:
        self._selected_keys.discard(key)

    # ----- paging internals ---------------------------------------------

    def _col_index(self, column: str) -> int:
        return self._col_pos[column]

    def _page_start(self) -> int:
        """Absolute index of the current page's first row."""
        return self._query.row_offset + self._offset

    def _goto(self, abs_start: int) -> list[Row]:
        """Display the page-aligned window starting at `abs_start` (clamped to a
        valid page boundary), repositioning the query's chunk to contain it."""
        if self._chunk is None:
            self._chunk = self._query.next_chunk()       # load the first chunk
        nrows = self._query.nrows
        if nrows == 0:
            self._offset = 0
            return []
        page = self.page_size
        max_start = ((nrows - 1) // page) * page
        return self._render(max(0, min(abs_start, max_start)))

    def _render(self, abs_start: int) -> list[Row]:
        """Position the chunk on `abs_start` (assumed a valid in-range row) and
        return that page's rows; the page may be partial near the end."""
        page = self.page_size
        page_len = min(page, self._query.nrows - abs_start)
        self._contain(abs_start, page_len)
        self._offset = abs_start - self._query.row_offset
        return [Row(self, r) for r in
                self._chunk[self._offset:self._offset + page]]

    def _contain(self, abs_start: int, page_len: int) -> None:
        """Step the query's chunk window until it fully holds
        `[abs_start, abs_start + page_len)`. Each step changes `row_offset` by a
        half-chunk; the change-detection guard stops at either end."""
        q = self._query
        while q.row_offset > abs_start:
            before = q.row_offset
            self._chunk = q.prev_chunk()
            if q.row_offset == before:
                break
        while abs_start + page_len > q.row_offset + len(self._chunk):
            before = q.row_offset
            self._chunk = q.next_chunk()
            if q.row_offset == before:
                break
