#!/usr/bin/env python

from dataclasses import dataclass
from typing import Any

import pandas as pd

from swmtplanner.support import Counters


@dataclass(frozen=True)
class ForeignKey:
    """One foreign-key link out of a table: `column` points at
    `ref_table.ref_column` (the referenced table's primary key)."""
    column: str
    ref_table: str
    ref_column: str


@dataclass(frozen=True)
class TableSchema:
    """The key/link structure of one table, as exposed by `DebugLog.schema`:
    the declared columns (same order as `get_df`), the primary-key column (or
    `None` for a key-less table), and one `ForeignKey` per foreign-key column."""
    columns: tuple[str, ...]
    pk: str | None
    fks: tuple[ForeignKey, ...]


class DebugLog:
    """Generic, config-driven container of named tables for the planner's
    debug/audit log (see `debuglog/DESIGN.md`). Tables are declared at
    construction as `table_name=[(column, default), ...]`; `set_pk` / `set_fk`
    then describe the inter-table links. Row population and export (`add_row`,
    `update_row`, `get_last_pk_val`, `get_df`) are implemented.

    Each table's schema is a single flat dict that mixes table-level
    attributes with per-column schemas. Table-level attributes are prefixed
    with `'@'` so they cannot collide with column names (which are valid
    identifiers and so never start with `'@'`):

    - `'@pk_col_name'` — the primary-key column's name, or `None`.
    - one entry per column name -> that column's schema dict, `{'default',
      'key_type'}` (key_type is `'primary'` / `'foreign'` / `None`), to which
      `set_pk` / `set_fk` add a `'ctr_name'` or `'table_name'` link entry.
    """

    def __init__(self, **tables: list[tuple[str, Any]]) -> None:
        self._tables: dict[str, dict[str, Any]] = {}
        for table_name, columns in tables.items():
            schema: dict[str, Any] = {'@pk_col_name': None}
            for col, default in columns:
                schema[col] = {'default': default, 'key_type': None}
            self._tables[table_name] = schema
        # Auto-increment counters, one per counter-backed primary key.
        self._counters = Counters()
        # Per-table row data, created lazily on the first add_row. Its shape
        # depends on whether the table has a primary key (see _table_data).
        self._data: dict[str, dict[str, Any]] = {}

    # ----- public read API -----

    @property
    def tables(self) -> tuple[str, ...]:
        """The names of the tables registered with this log, in declaration
        order. Lets a caller enumerate the log (e.g. to dump each table via
        `get_df`) without knowing the schema up front."""
        return tuple(self._tables)

    @property
    def schema(self) -> dict[str, TableSchema]:
        """The PK / FK structure of every table, as `{table: TableSchema}` in
        declaration order — the inter-table link metadata the dashboard reads to
        document tables and render foreign-key links. Recomputed per access from
        the (small, fixed-once-rows-exist) schema. Each foreign key resolves to
        its `ref_table` / `ref_column`: a link onto a non-auto primary key stores
        the foreign table directly, while a link onto a counter-backed primary
        key stores only the counter name, which is mapped back here to the table
        whose primary key owns that counter."""
        # counter name -> (owning table, its pk column), for counter-backed PKs.
        ctr_owner: dict[str, tuple[str, str]] = {}
        for table, schema in self._tables.items():
            pk = schema['@pk_col_name']
            if pk is not None and 'ctr_name' in schema[pk]:
                ctr_owner[schema[pk]['ctr_name']] = (table, pk)

        result: dict[str, TableSchema] = {}
        for table, schema in self._tables.items():
            cols = tuple(c for c in schema if not c.startswith('@'))
            fks = []
            for col in cols:
                meta = schema[col]
                if meta['key_type'] != 'foreign':
                    continue
                if 'table_name' in meta:                     # onto a non-auto PK
                    ref_table = meta['table_name']
                    ref_column = self._tables[ref_table]['@pk_col_name']
                else:                                        # onto a counter PK
                    ref_table, ref_column = ctr_owner[meta['ctr_name']]
                fks.append(ForeignKey(col, ref_table, ref_column))
            result[table] = TableSchema(
                columns=cols, pk=schema['@pk_col_name'], fks=tuple(fks),
            )
        return result

    # ----- internal helpers -----

    def _column(self, table: str, column: str) -> dict[str, Any]:
        """The column schema dict for `table.column`; raises if either is
        unknown. Table-level `'@'`-prefixed attributes are not columns."""
        if table not in self._tables:
            raise KeyError(f'no table named {table!r}')
        schema = self._tables[table]
        if column.startswith('@') or column not in schema:
            raise KeyError(f'table {table!r} has no column {column!r}')
        return schema[column]

    # ----- key declarations -----

    def set_pk(
        self, table: str, column: str, ctr_name: str | None = None,
    ) -> None:
        """Declare `column` as `table`'s primary key.

        When `ctr_name` is given the key is **auto-incremented**: a fresh
        counter of that name is created (the name must not already exist) and
        the column gains a `'ctr_name'` entry. Omit `ctr_name` for a
        caller-supplied (non-auto) primary key. Either way `key_type` becomes
        `'primary'` and the table's `'@pk_col_name'` is set.

        Raises on: unknown `table` / `column`; `ctr_name` already in use;
        `column` already a foreign key; `table` already having a primary key;
        or `column` already being this table's primary key with a different
        counter (including switching counter <-> non-counter). Re-declaring the
        identical primary key is a silent no-op."""
        col = self._column(table, column)
        schema = self._tables[table]
        if table in self._data:
            raise ValueError(
                f'cannot change keys on {table!r}: it already holds row data'
            )
        if col['key_type'] == 'foreign':
            raise ValueError(
                f'{table}.{column} is already a foreign key; it cannot also '
                f'be a primary key'
            )
        if col['key_type'] == 'primary':
            if col.get('ctr_name') == ctr_name:
                return                          # identical re-declaration
            raise ValueError(
                f'{table}.{column} is already a primary key; it cannot be '
                f'redefined with a different counter ({ctr_name!r})'
            )
        if schema['@pk_col_name'] is not None:
            raise ValueError(
                f'table {table!r} already has a primary key '
                f'({schema["@pk_col_name"]!r}); only one is allowed'
            )
        if ctr_name is not None:
            if ctr_name in self._counters.ctr_names:
                raise ValueError(f'counter {ctr_name!r} already exists')
            self._counters.add_counter(ctr_name)
            col['ctr_name'] = ctr_name
        col['key_type'] = 'primary'
        schema['@pk_col_name'] = column

    def set_fk(
        self, table: str, column: str,
        foreign_table: str, foreign_column: str,
    ) -> None:
        """Declare `column` as a foreign key pointing at
        `foreign_table.foreign_column` (which must be that table's primary
        key). The method records how to populate the link: if the referenced
        primary key is counter-backed the column gains a `'ctr_name'` entry
        (the foreign counter's name); otherwise it gains a `'table_name'` entry
        (the foreign table's name, used to read that table's last primary-key
        value). Either way `key_type` becomes `'foreign'`.

        Raises on: any of the four names unknown; `foreign_column` not being the
        primary key of `foreign_table`; `column` already a primary key; or
        `column` already a foreign key pointing at a different referent.
        Re-declaring the identical foreign key is a silent no-op."""
        col = self._column(table, column)
        fcol = self._column(foreign_table, foreign_column)
        if table in self._data:
            raise ValueError(
                f'cannot change keys on {table!r}: it already holds row data'
            )
        if col['key_type'] == 'primary':
            raise ValueError(
                f'{table}.{column} is already a primary key; it cannot also '
                f'be a foreign key'
            )
        if self._tables[foreign_table]['@pk_col_name'] != foreign_column:
            raise ValueError(
                f'{foreign_table}.{foreign_column} is not the primary key of '
                f'{foreign_table!r}; a foreign key must reference one'
            )
        # Link by the foreign counter when the referenced key is
        # auto-incremented, else by the foreign table name.
        if 'ctr_name' in fcol:
            link = ('ctr_name', fcol['ctr_name'])
        else:
            link = ('table_name', foreign_table)
        if col['key_type'] == 'foreign':
            existing = (
                ('ctr_name', col['ctr_name']) if 'ctr_name' in col
                else ('table_name', col['table_name'])
            )
            if existing == link:
                return                          # identical re-declaration
            raise ValueError(
                f'{table}.{column} is already a foreign key referencing '
                f'elsewhere; it cannot be redefined'
            )
        col['key_type'] = 'foreign'
        col[link[0]] = link[1]

    # ----- row data -----

    def _ensure_table(self, table: str) -> None:
        if table not in self._tables:
            raise KeyError(f'no table named {table!r}')

    def _table_data(self, table: str) -> dict[str, Any]:
        """`table`'s row-data dict, created on first use from the (now-frozen)
        schema. A **keyed** table -> `{'rows'` (pk value -> row list),
        `'pk_col_name'`, `'last_pk_val'`, `'col_map'` (non-pk column -> its
        index in the row list, in constructor order)}`. A **key-less** table ->
        `{'rows'` (list of row dicts), `'columns'}`."""
        data = self._data.get(table)
        if data is not None:
            return data
        schema = self._tables[table]
        pk = schema['@pk_col_name']
        non_pk = [c for c in schema if not c.startswith('@') and c != pk]
        if pk is not None:
            data = {
                'rows': {},
                'pk_col_name': pk,
                'last_pk_val': None,
                'col_map': {c: i for i, c in enumerate(non_pk)},
            }
        else:
            data = {'rows': [], 'columns': non_pk}
        self._data[table] = data
        return data

    def _resolve(self, meta: dict, value: Any) -> Any:
        """Resolve a cell value against its column schema `meta`: a foreign key
        left **unset** (`value is None`) is auto-linked — to its counter's
        current value, or the referenced table's last primary key — while any
        other value (including a supplied non-None foreign key) is used as-is."""
        if meta['key_type'] == 'foreign' and value is None:
            if 'ctr_name' in meta:
                return self._counters(meta['ctr_name'])      # current value
            return self.get_last_pk_val(meta['table_name'])
        return value

    def _cell_value(self, table: str, column: str, kwargs: dict) -> Any:
        """Value for a non-primary-key `column` at add_row time: the supplied
        kwarg else the declared default, then `_resolve`d (so an unset foreign
        key auto-links)."""
        meta = self._tables[table][column]
        value = kwargs[column] if column in kwargs else meta['default']
        return self._resolve(meta, value)

    def add_row(self, table: str, **kwargs: Any) -> Any:
        """Append a row to `table` and return its primary-key value (or `None`
        when the table has no primary key; it also updates `last_pk_val`).
        Each non-key column not supplied takes its declared default; a
        foreign-key column left unset (`None`, whether by default or passed
        explicitly) is auto-linked. An auto-incremented primary key is minted
        from its counter (and must **not** be supplied); a non-auto primary key
        **must** be supplied. Unknown columns raise."""
        self._ensure_table(table)
        schema = self._tables[table]
        for k in kwargs:
            if k.startswith('@') or k not in schema:
                raise KeyError(f'table {table!r} has no column {k!r}')
        data = self._table_data(table)
        if 'col_map' not in data:                            # key-less table
            data['rows'].append(
                {c: self._cell_value(table, c, kwargs) for c in data['columns']}
            )
            return None
        pk = data['pk_col_name']
        pk_meta = schema[pk]
        if 'ctr_name' in pk_meta:                            # auto-incremented
            if pk in kwargs:
                raise ValueError(
                    f'{table}.{pk} is auto-incremented; do not supply it'
                )
            pk_val = self._counters.advance(pk_meta['ctr_name'])
        else:                                                # caller-supplied
            if pk not in kwargs:
                raise ValueError(
                    f'{table}.{pk} is a non-auto primary key and must be '
                    f'supplied'
                )
            pk_val = kwargs[pk]
        row = [None] * len(data['col_map'])
        for col, i in data['col_map'].items():
            row[i] = self._cell_value(table, col, kwargs)
        data['rows'][pk_val] = row
        data['last_pk_val'] = pk_val
        return pk_val

    def get_last_pk_val(self, table: str) -> Any:
        """The primary-key value of the most recently added row of `table`
        (`None` if none yet). Raises if the table has no primary key."""
        self._ensure_table(table)
        if self._tables[table]['@pk_col_name'] is None:
            raise ValueError(f'table {table!r} has no primary key')
        data = self._data.get(table)
        return None if data is None else data['last_pk_val']

    def update_row(self, table: str, pk_val: Any, **kwargs: Any) -> None:
        """Patch the columns named in `kwargs` on `table`'s row whose primary
        key is `pk_val`; columns not named are left untouched. A foreign-key
        column passed as `None` is auto-linked — the way to fill an unset FK
        here — while any other value is used as-is. Only valid on a keyed
        table — raises otherwise, if no such row exists, or if a kwarg names an
        unknown column (the primary key itself cannot be updated)."""
        self._ensure_table(table)
        if self._tables[table]['@pk_col_name'] is None:
            raise ValueError(
                f'update_row needs a primary key; table {table!r} has none'
            )
        data = self._data.get(table)
        if data is None or pk_val not in data['rows']:
            raise KeyError(
                f'table {table!r} has no row with primary key {pk_val!r}'
            )
        col_map = data['col_map']
        pk = data['pk_col_name']
        row = data['rows'][pk_val]
        for k, v in kwargs.items():
            if k == pk:
                raise ValueError(f'cannot update primary-key column {pk!r}')
            if k not in col_map:
                raise KeyError(f'table {table!r} has no column {k!r}')
            row[col_map[k]] = self._resolve(self._tables[table][k], v)

    def get_nrows(self, table: str) -> int:
        self._ensure_table(table)
        data = self._data.get(table)
        if data is None: return 0
        return len(data['rows'])

    def get_df(self, table: str, **kwargs: Any) -> pd.DataFrame:
        """Render `table` as a flat `pandas.DataFrame` (no MultiIndex). A keyed
        table uses its primary key as the index (built via
        `DataFrame.from_dict(orient='index')`); a key-less table is passed
        straight to the `DataFrame` constructor (default integer index). Extra
        `kwargs` are forwarded to whichever pandas call is used."""
        self._ensure_table(table)
        schema = self._tables[table]
        pk = schema['@pk_col_name']
        data = self._data.get(table)
        if pk is None:
            cols = (
                data['columns'] if data is not None
                else [c for c in schema if not c.startswith('@')]
            )
            rows = data['rows'] if data is not None else []
            return pd.DataFrame(rows, columns=cols, **kwargs)
        cols = (
            list(data['col_map']) if data is not None
            else [c for c in schema if not c.startswith('@') and c != pk]
        )
        rows = data['rows'] if data is not None else {}
        df = pd.DataFrame.from_dict(rows, orient='index', columns=cols, **kwargs)
        df.index.name = pk
        return df
