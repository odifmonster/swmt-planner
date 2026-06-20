# Specification of coverage of debuglog module tests

Light white-box coverage of `swmtplanner.debuglog.DebugLog` — the generic,
config-driven table container. These tests **deliberately inspect the object's
internal state** (`_tables`, `_counters`, `_data`) because the schema/link
bookkeeping is the non-obvious part worth pinning down; the public read API is
the `tables` and `schema` properties (both covered below). The single-column
`get_df` rendering is **out of scope** for this pass (verified by running the
program); the **composite-PK** `get_df` shape is covered in §10, since it is new.

Shared fixtures: small tables built with `DebugLog(...)`, e.g. a keyed
`iteration_log=[('move_id', None), ('iteration_idx', None), ('role',
'rejected')]`, a keyed non-auto-PK `cost_summary=[('summary_id', None),
('move_id', None), ('cost', 0.0)]`, and a key-less `notes=[('text', None)]`.

## 1. Construction

`__init__(**tables)` builds the schema and nothing else.

1. For each declared table, `_tables[name]` has `'@pk_cols': ()` and one
   entry per declared column, in declared order, each
   `{'default': <given default>, 'key_type': None}` — no `'ctr_name'` /
   `'table_name'` yet.
2. `_counters.ctr_names == ()` (no counters created).
3. `_data == {}` (no row storage until the first `add_row`).
4. The `tables` property returns the declared table names as a tuple in
   declaration order (e.g. `('iteration_log', 'notes')`), and is unaffected by
   `set_pk` / `set_fk` / `add_row` (it reflects the registered tables, not
   their keys or row data).

## 2. `set_pk` / `set_fk` invalid inputs

Each raises and leaves the schema unchanged.

1. **`set_pk`**
    1. unknown `table`
    2. unknown `column`
    3. `ctr_name` already in use by an existing counter
    4. `column` is already a foreign key
    5. `table` already has a (different) primary key — second PK rejected
    6. `column` is already this table's primary key but with a different
       `ctr_name`, including switching counter <-> non-counter (e.g. it was
       declared with a counter, re-declared without one, and vice versa)
    7. **no columns** given (`set_pk(t)`)
    8. `ctr_name` given with **more than one** column (a composite key cannot
       be auto-incremented) — see §10
2. **`set_fk`**
    1. unknown `table` / `column`
    2. unknown `foreign_table` / `foreign_column`
    3. `foreign_column` is not `foreign_table`'s **single-column** primary key
       (not a PK at all, a different column is the PK, or the referent's PK is
       **composite** — see §10)
    4. `column` is already a primary key
    5. `column` is already a foreign key pointing at a different referent

## 3. Schema frozen once rows exist

After a single `add_row` on a table, **both** `set_pk` and `set_fk` raise when
called on that table — even with otherwise-valid arguments and even for an
identical re-declaration (the row-data guard fires before the no-op check).

## 4. Valid schema updates

The happy-path mutations land in the schema correctly.

1. `set_pk(t, c, ctr_name='k')`: `_tables[t]['@pk_cols'] == (c,)`; the column
   schema is `key_type == 'primary'` with `'ctr_name' == 'k'`; `'k'` is now in
   `_counters.ctr_names`.
2. `set_pk(t, c)` (no counter): `'@pk_cols' == (c,)`; `key_type == 'primary'`;
   the column has **no** `'ctr_name'`; no counter was created.
3. `set_fk(t, c, ft, fc)` where `ft.fc` is a **counter-backed** PK: the column
   is `key_type == 'foreign'` with `'ctr_name'` equal to the foreign PK's
   counter name and **no** `'table_name'`.
4. `set_fk(t, c, ft, fc)` where `ft.fc` is a **non-auto** PK: the column is
   `key_type == 'foreign'` with `'table_name' == ft` and **no** `'ctr_name'`.
5. Idempotent re-declaration: calling `set_pk` / `set_fk` again with identical
   arguments (before any rows) is a silent no-op and leaves the schema
   unchanged.

## 5. `add_row` and auto-increment

1. **Keyed, counter-backed PK** — successive `add_row(t, ...)` calls (without
   supplying the PK) mint `1, 2, 3, ...` and **return** the minted scalar; each
   row is stored in `_data[t]['rows']` under its **PK tuple** (`(1,)`, `(2,)`,
   …, even for a single-column key); `_data[t]['last_pk_key']` tracks the latest
   tuple; `get_last_pk_val(t)` returns the scalar.
2. **Row layout** — `_data[t]['col_map']` maps the non-PK columns to indices in
   declared order (PK excluded), and the stored row is a list of those columns'
   values; an unset non-key column takes its declared default.
3. **Lazy creation** — `_data` has no entry for a table until its first
   `add_row`.
4. **Key-less table** — `add_row` appends a dict to `_data[t]['rows']`
   (a list), returns `None`, and `last_pk_key` machinery is absent.

## 6. `update_row`

1. Patches only the columns named in `kwargs`; columns not named keep their
   prior values.
2. **Foreign-key fill rule**:
    1. an FK column **passed `None`** is re-linked (to its counter's current
       value, or the referenced table's last PK);
    2. an FK column **not named** keeps its original value (no re-link);
    3. an FK column passed a non-`None` value is set to that value.
3. Raises on: a table with no primary key; an unknown `pk_val`; an unknown
   column; attempting to update **any** primary-key column.

## 7. A foreign key does not advance its counter

With a counter-backed PK table linked to by an FK table: minting a PK row
advances the counter, but `add_row` on the FK table (FK left unset) fills the
FK from the counter's **current** value **without advancing it**. Concretely,
after one PK `add_row` the counter reads `1`; an FK `add_row` sets the FK to
`1` and the counter still reads `1` (the next PK `add_row` would mint `2`).

## 8. Multiple foreign keys to one primary key

Two distinct tables may each `set_fk` onto the **same** PK column. Both FK
columns inherit that PK's counter, and an `add_row` on each (FK unset) links
both to the same current PK value.

## 9. `schema` link metadata

The `schema` property returns `{table: TableSchema}` in declaration order,
exposing the PK / FK structure (`TableSchema(columns, pk, fks)` with
`ForeignKey(column, ref_table, ref_column)`), independent of row data.

1. For a counter-backed PK table linked to by an FK table (the `_linked_log`
   fixture: `il.move_id` counter PK, `cs.move_id` FK onto it): `schema['il']`
   has `pk == ('move_id',)`, `fks == ()`, and `columns` in declared order;
   `schema['cs']` has `pk == ('summary_id',)` and a single
   `ForeignKey('move_id', 'il', 'move_id')` — i.e. the counter-backed referent
   is resolved back to its owning table and PK column.
2. A foreign key onto a **non-auto** primary key resolves via the stored table
   name: e.g. a leaf table with `set_fk(leaf, 'summary_id', 'cs', 'summary_id')`
   yields `ForeignKey('summary_id', 'cs', 'summary_id')`.
3. A **key-less** table reports `pk == ()` and `fks == ()` (unless it carries
   a foreign key, which it still lists); `columns` is the declared list.
4. `schema` reflects only the schema, not rows — it is unchanged before and
   after `add_row`.

## 10. Composite primary keys

A primary key may span **two or more** columns (`set_pk(t, *columns)`); rows are
addressed by the **tuple** of their PK values. Fixture: a `cfg` table keyed by
`(kind, label)` over `value`, alongside a single-column counter PK for contrast.

1. **Declaration** — `set_pk('cfg', 'kind', 'label')` stores
   `_tables['cfg']['@pk_cols'] == ('kind', 'label')` and marks **each** PK
   column `key_type == 'primary'`; **no** counter is created for a composite
   key. `schema['cfg'].pk == ('kind', 'label')`.
2. **Rejected declarations** — `set_pk('cfg')` (no columns) raises; `set_pk(t,
   'a', 'b', ctr_name='x')` (counter + composite) raises and leaves the table
   unkeyed with no counter leaked.
3. **`add_row`** — returns the **tuple** of PK values, stores the row under that
   tuple in `_data['cfg']['rows']`, and `get_last_pk_val('cfg')` returns the
   tuple. **Every** PK column must be supplied (omitting one raises).
4. **`update_row`** — addressed by the PK tuple; patches non-PK columns;
   updating **any** PK column raises; an unknown PK tuple raises.
5. **`get_df`** — flat (no MultiIndex): the PK columns are ordinary **leading**
   columns in declared order with a default (unnamed) index; row values
   round-trip; an empty table yields the columns with zero rows.
6. **`set_fk` onto a composite PK raises** — a single FK column cannot reference
   a multi-column key (covered under §2.2.3).
