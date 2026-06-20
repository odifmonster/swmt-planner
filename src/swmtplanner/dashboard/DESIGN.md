# Debug Dashboard — Design

The **PyQt6 desktop app** for investigating a planner's verbose debug log. A
planner persists a run-tagged debug log to a **local MySQL** store (one row-set
per run, tagged by an auto-incremented `run_id`); the dashboard reads it on
demand. Its **data layer and raw view are planner-agnostic** — driven by a
*manifest* of `TableSpec`s the planner hands in, hard-coding no schema — while
its richer **"pretty" views are planner-specific** and live here too: the
dashboard **owns all GUI** for viewing planner debug output, generic and
bespoke alike.

Replaces an earlier in-memory-HTML / TSV dashboard, which couldn't scale to a
real log (~6.5M rows). MySQL is the store; the app queries it (filtered, paged)
so the app never holds a whole table in memory.

Lives at top-level **`swmtplanner/dashboard/`** — a sibling of the planners, not
inside any one of them: a planner's debug output is *data*, and viewing it is a
concern of its own. The dependency runs one way — the dashboard reads a planner's
schema (and builds bespoke views for it), never the reverse.

## Boundary with the planner

The **planner owns** its concrete debug schema (the actual tables, columns, FK
graph, and the MySQL DDL) and the **write path** that persists its debug log to
the store — see that planner's own DESIGN.md (for the infinite knitting planner,
`planners/infinite/DESIGN.md`). The **dashboard owns all viewing** — the generic
data layer + raw view (driven by the planner's manifest) *and* the planner-
specific "pretty" views built on top of it:

```
  planner run ──(write path, planner-owned)──▶  local MySQL  ◀──(read path, here)── PyQt6 app
   debug log → INSERTs                          run-tagged          paged SELECTs, per
                                                row-sets            run_id, filtered
```

### The run model (universal)

Every persisted table is tagged by an integer **`run_id`**. A **`runs` registry**
table (its own `run_id` primary key plus per-run metadata) lets the app list and
pick a run; everything downstream is **scoped to the chosen `run_id`**. This much
is universal and owned by the dashboard; the *columns* of a planner's `runs`
table (beyond `run_id`) are part of that planner's manifest.

The dashboard package: the generic `manifest` dataclasses + reader `config` at
the top; the read/pagination layer in `sqlload/`; the GUI in `app/` (later).

## The manifest (schema description — passed in)

The dashboard is driven by a **manifest**: a set of `TableSpec`s describing the
planner's tables. The **dataclasses are generic and defined here**; the
**concrete instance is built and owned by the planner** and handed to the
dashboard, which reads it to drive the table list, column typing, FK navigation,
and pagination order. It hard-codes no schema.

Per table the manifest records a `TableSpec`:

- **`name`** — the table name (identical in the planner's debug log and the DB).
- **`columns`** — ordered `(name, type, nullable)`; `type` ∈
  `int/float/str/datetime` drives the app's per-column filter modes.
- **`pk`** — the primary-key column(s) after the implicit leading `run_id`
  (empty for a key-less table).
- **`fks`** — `(column → ref_table.ref_column)`, the full DB FK graph, for the
  app's drill-down navigation.
- **`order_by`** — an explicit stable paging/display order. When set it
  **overrides** the `pk` (for a key-less table, or a keyed table shown in a
  non-key order — e.g. a keyed view ordered by its base table's sort); a keyed
  table without it paginates by its `pk`. The `order_columns` accessor returns
  `order_by` if set, else `pk`.

The dataclasses carry only *structure* — no concrete tables. The planner builds
the instance (its table set, FK graph, and FK-topological insert order) and the
DDL it mirrors; those live in the planner's DESIGN.md.

## Reader configuration — `config.py`

The dashboard connects **read-only**. Connection settings come from a **separate
JSON config file** pointed to by the **`SWMT_DASHBOARD_CONFIG`** environment
variable — deliberately decoupled from any planner's run-config (the planner's
*writer* config is the planner's concern; the dashboard only ever needs the
reader). The file names a single connection directly — `host` / `port` / `name`
/ `user` / `password` (the reader user) — with environment-variable fallback:

```json
{
  "host": "127.0.0.1",
  "port": 3306,
  "name": "swmtinfinite",
  "user": "swmt_reader",
  "password": null            // null → SWMT_DASHBOARD_PASSWORD
}
```

- **Read-only is enforced at the grant level.** The configured reader user has
  only `SELECT`, so a UI bug or rogue query *physically cannot* mutate the data —
  read-only is a MySQL guarantee, not app discipline. (Run deletion or
  `label`/`notes` edits would need a writer connection and are out of scope for
  the reader-only app; revisit if the app ever adds them.)
- **Env fallback**: `SWMT_DASHBOARD_HOST` / `_PORT` / `_NAME` / `_USER` /
  `_PASSWORD`. Env wins over the file (so a committed config keeps non-secret
  defaults and leaves the password to the environment). The reader's
  `SWMT_DASHBOARD_*` namespace is **distinct** from the writer's `SWMT_DB_*`, so
  neither side can pick up the other's credentials.
- **`read_reader_config(env)`** reads the `SWMT_DASHBOARD_CONFIG` file (when set)
  as the connection block and resolves it via
  **`resolve_conn_config(block, env, prefix='SWMT_DASHBOARD')`** (the generic
  resolver; `ConnConfig` is defined here and reused by the planner's writer with
  the default `SWMT_DB` prefix). Either raises `DatabaseConfigError` on an
  unreadable file, a missing database name / user, or an unparseable port.
- **Driver**: **PyMySQL** (pure-python). PyQt6 is the app's dependency.

## Read path — `sqlload/` (data layer)

The read/pagination data layer, **separate from the GUI** (`app/` sits on top of
it). It turns a table's current display state — active filters, ordering, which
chunk of rows is in hand — into run-scoped, **bounded** SQL and feeds the app
pages of rows. No query it issues is ever unbounded. Two main classes:

### Query inputs — `Filter` and `FKLookup` (dataclasses)

Two dataclasses (in `sqlload/helpers.py`) describe how a single column
constrains a query. Both own a `to_sql_str` convenience method that returns a
**format string** (with named fields) the `Query` fills in to build the SQL.
Neither validates at construction — a malformed value passes silently; the
**`rule` type/value is validated on the first `to_sql_str()` call** (a bad rule
raises `FilterError` there, not in `__init__`).

- **`Filter`** — a per-column value filter. Constructed with:
  - **`kind`** — one of `selection`, `exclusion`, `range`, `pattern`.
  - **`rule`** — the filter payload, whose type/value depends on `kind`:
    - `selection` / `exclusion` — a **set of values** (rows whose column value
      is in / not in the set).
    - `range` — a **2-tuple `(low, high)`** of bounds; at most **one** may be
      `None` (the range is then unbounded on that end).
    - `pattern` — a **MySQL `LIKE` pattern string** (`%` / `_` wildcards).
  - **`to_sql_str()`** → a string `s` such that `s.format(colname=<column>)`
    yields the text that goes in the `WHERE` clause to apply the filter.

- **`FKLookup`** — a foreign-key navigation constraint (drill from one table to
  the rows of a referenced table). Constructed with:
  - **`ref_table`** — the referenced table.
  - **`ref_col`** — the referenced column (the reference table's own PK column).
  - **`vals`** — the selected key values to look up.
  - **`to_sql_str()`** → a string `s` such that
    `s.format(ftable=<table with fk>, fcol=<fk colname>, run_id=<selected run_id>)`
    yields an **`INNER JOIN`** statement. The join target is a **sub-query**
    selecting `(run_id, ref_col)` from the indexed reference table for the
    chosen `run_id` and `vals`; the join then matches the main table's
    `(run_id, fcol)` against the sub-query's `(run_id, ref_col)`.

### `Query`

Translates the current state of a table into a single SQL query, and manages
the limit/offset windowing. The internal load limit/offset are **distinct from
the display row limit** (the app's visible page size) — the query fetches in its
own **chunks** of up to a global **`CHUNK_SIZE`** records, and advancing to the
next chunk after a limit is handled **internally** by the class (not by building
a new `Query`).

- **`Query.build(<cursor>, <run_id>, <table name>, <col1>=<Filter or FKLookup>,
  …)`** — the factory for a *new* query: a MySQL **cursor** (used to run the
  queries), the currently-targeted **`run_id`** (scopes the main query and every
  build-time count/distinct query, and fills the `{run_id}` field of each
  `FKLookup.to_sql_str()`), a table name, plus per-column `Filter` / `FKLookup`
  keyword args. Called whenever the query itself changes (new filters, new
  ordering, a new FK/PK navigation, a new table). **Not** called to load the
  next chunk of rows past the current limit — that windowing is internal to an
  existing `Query`.
- **The held SQL string** — a `Query` instance holds the complete SQL query with
  **placeholders for `LIMIT` and `OFFSET`**, so loading the next/previous chunk
  only requires injecting the current offset and the global limit into the
  string and re-executing on the cursor. Construction:

  ```
  SELECT <table-qualified columns, excluding run_id, comma-joined>
  FROM <table>
  <one INNER JOIN per FKLookup>
  WHERE <table>.run_id = <run_id> [AND <each Filter.to_sql_str()> …]
  ORDER BY <spec.order_columns>                 -- stable LIMIT/OFFSET paging
  LIMIT {limit} OFFSET {offset}
  ```

  Columns are **table-qualified** because an `FKLookup`'s join sub-query exposes
  `run_id`/`ref_col`, which can otherwise collide with the main table's columns.
  The `ORDER BY` is required: `LIMIT`/`OFFSET` paging is only well-defined under
  a stable order, so the table's `order_columns` (its `order_by` if set, else its
  PK) drives it.

  The trailing `LIMIT`/`OFFSET` are filled per chunk via
  `query_str.format(limit=…, offset=…)`.

  At build time, `Query.build` runs **only one** query — the **total row count**
  (`nrows`). The per-column distinct work is **not** run eagerly (it can be
  expensive); instead `build` *prepares the SQL strings* for each column's
  count-distinct and distinct-values queries, and `unique(col)` runs them lazily
  on demand (see below). So opening a table is cheap.
- **Constructor (private)** — `Query` accepts the **cursor**, the **full SQL
  string**, the **row count**, and a **map of column name →
  `(count-distinct SQL, distinct-values SQL)`** (the prepared, not-yet-run
  queries). It is **only ever called by `Query.build`**; the class is **not**
  instantiated directly.
- **`nrows`** — total rows the query returns with no limit applied.
- **`next_chunk` / `prev_chunk`** — load in and return chunks of data on demand
  as the user navigates to a page outside the currently-held chunk. The instance
  **internally tracks its current offset from the start of the table, in
  chunks**, so successive `next_chunk` / `prev_chunk` calls advance/retreat as
  expected. The query **always retains a full chunk's worth of records, but
  advances in half-chunks** — each `next_chunk` / `prev_chunk` step moves the
  window by `CHUNK_SIZE / 2`. This prevents excessive back-to-back reloads when
  the user navigates back and forth between two pages that straddle a chunk
  boundary, and handles the case where the display limit does not evenly divide
  `CHUNK_SIZE`.
- **`unique(<colname>)`** — the list of unique values in that column, or `None`
  if it exceeds the max chunk size (`CHUNK_SIZE`). **Lazy**: on the first call it
  runs the prepared count-distinct query and, only when within the cutoff, the
  distinct-values query; the result (set or `None`) is **cached** so repeat
  calls and the other columns cost nothing until asked for. This is what keeps
  `Query.build` cheap — the per-column queries fire only when a filter UI needs
  a column's values.
- **`row_offset`** — exposes the current chunk's **offset, in rows** (not
  half-chunks), from the first record the unbounded query would return, so a
  `Table` can map a displayed row back to its absolute position.

### `Row`

A convenience wrapper around one displayed record. Instantiated with a `Table`
and a **tuple** of the row's data.

- **`data`** — the row's value tuple.
- **`pk_col`** — the row's primary-key column, or `None` for a table with no PK.
- **`selected`** — whether the row is selected; **always `False`** when
  `pk_col` is `None`.
- **`get(column)`** — the value for a column.
- **`select()` / `deselect()`** — toggle selection (driving the owning
  `Table.selected_keys`); both **raise** if called on a row from a non-keyed
  table.

### `Table`

The stateful object the app drives: it stores a table's schema and current
state and exposes methods for filtering columns and paging through rows. A
`Query` is built (via `Query.build`) from the table's state when that state
changes.

- **Construction** — instantiated with a **`TableSpec`**, a **cursor**, and a
  **`run_id`**; only the **`schema`** is publicly exposed.
- **`page_size`** — the display page size: a **private class attribute**
  (universal across all tables) read via the `page_size` property and changed
  only through the **`set_page_size(n)` classmethod** (e.g. on a window resize),
  which validates `n ∈ [1, CHUNK_SIZE // 2]` and raises otherwise. The upper
  bound keeps a page within a half-chunk so it always fits inside one chunk.
- **Internal state** — the current `Query` object; the currently-loaded **data
  chunk** as a list of tuples (or `None` before the first `next_page()`, i.e.
  immediately after instantiation); and the **offset of the first displayed row
  from the start of the data chunk** (combined with the `Query`'s row offset to
  locate the displayed window absolutely); plus the **current per-column filters
  and FK lookups** (the active `Filter` / `FKLookup` per column), retained so
  that every `apply_filter_to` / `remove_filter` call can **fully rebuild** the
  `Query` from the complete current constraint set.
- **`apply_filter_to(colname, filter)`** — apply a `Filter` to a column, which
  rebuilds the `Query` via `Query.build`. Rebuilding **resets the display window
  to page 1 and clears `selected_keys`**.
- **`remove_filter(column)`** — drop the column's active filter and rebuild
  (same page-1 / cleared-selection reset).
- **`apply_fk_lookup(fkcol, values)`** — apply an `FKLookup` constraint; called
  on the table **being linked to** (the FK's owning table), where `fkcol` is its
  FK column and `values` the looked-up reference values. Rebuilds like the
  filter methods.
- **`selected_keys`** (property) — the set of selected PK values, modified via
  `Row.select` / `Row.deselect`.
- **`next_page()` / `prev_page()`** — advance/retreat the displayed window and
  return a list of `Row` objects (pulling the next/previous chunk from the
  `Query` as needed).
- **`reload_page()`** — re-display the current page from the **same first row**,
  re-sized to the current `page_size`; used after `set_page_size` (the start
  holds, only the displayed range changes).
- **`displayed_range: tuple[int, int]`** (computed) — the absolute row range
  currently displayed.
- **`nrows`** — read off the internal `Query` object.

## Read path — the PyQt6 app

A desktop app under `swmtplanner/dashboard/app/`. It connects to MySQL as the
**reader** (`config.py`, SELECT-only) and pulls everything with `run_id`-scoped,
**paged** SELECTs through the `sqlload` layer — **no query, filtered or not, is
ever unbounded.** Because the reader grant lacks write privileges, the app
physically cannot modify the data. A console entry point (`knit-debug`) launches
the app with the knitting planner's **manifest**; the entry point and the
planner-specific views all live in the dashboard.

The GUI's detailed design and its fine-grained phasing live in
`app/DESIGN.md`; the sketch below is the target shape.

### Home — select a run

Queries the `runs` registry (most recent first), showing its columns from the
manifest (`run_id`, `created_at`, and the planner's per-run metadata). You pick
one to investigate; everything downstream is scoped to the chosen `run_id`.

### Investigation — raw, paged grids

The **planner-agnostic raw view**, SQL-backed and run-scoped, driven entirely by
the manifest:

- **Table list** — the manifest's tables, each opening a grid.
- **Grid** — a `QTableView` over a `Table`/`Row` model that fetches **one page
  at a time** (`next_page` / `prev_page`), plus the total from `nrows`. **Every
  large result is handled this way — including foreign-key lookups.** A 1-row
  lookup and a 100k-row lookup page identically; the app never asks for "all
  matching rows."
- **Foreign-key / PK navigation** — clicking a FK cell opens the referenced
  table with an added constraint (`apply_fk_lookup`) — then paged like any grid.
  PK cells offer a "show only this row" filter. Links come from the manifest's
  FK graph.
- **Per-column filters** — pushed to SQL `WHERE` via `apply_filter_to`: value
  select (`IN`), range on numeric & datetime columns, starts-with/contains
  (`LIKE`) on text columns; column types come from the manifest. Filters AND
  together and with the FK/PK constraint; re-querying resets to page 1.
- **Schema view** — the FK graph from the manifest, documenting the tables and
  links.

The app holds the manifest in memory (table/column/type/FK metadata); the DB
holds only data.

### The pretty view (planner-specific)

Beyond the generic raw view, the dashboard houses an elaborate **planner-specific
"pretty" view** designed to be navigable by **non-technical users** — so a plant
manager or floor supervisor can walk a run and raise concerns/changes. It is
built from a dedicated set of **custom `QtWidget` subclasses** and lives in the
dashboard's `app/` (alongside the generic pieces), **not** supplied by the
planner. Schema-aware affordances like a "committed-only" toggle (which rows
count as committed is a planner concept) are part of it. This deliberately makes
parts of the dashboard planner-specific — reasonable, since the dashboard already
owns all GUI. Its layout will be specified in this DESIGN.md once that view is
designed.

## Phasing

1. **App shell + Home** — connect as the reader (via `SWMT_DASHBOARD_CONFIG`);
   list / select runs from the `runs` registry. Add `PyQt6` (consider an
   optional extra so headless installs skip it). A planner entry point
   (`knit-debug`) launches the app with its manifest.
2. **Raw grids + FK navigation** — run-scoped paged grids over `Table`/`Row`,
   FK/PK drill, schema view.
3. **Per-column filters** — the SQL-backed `Filter` modes wired to the grid UI.
4. **Planner-specific pretty view** — the non-technical, navigable view built
   from custom `QtWidget` subclasses (incl. the committed-only toggle), living in
   the dashboard's `app/`.

## Open items

- **Dependencies** — `pymysql` (reader) and `PyQt6` (app); mirror into
  `pyproject.toml` (PyQt6 ideally an optional extra for headless installs).
- **Testing** — the `sqlload` data layer is unit-tested (pure `Filter`/`FKLookup`;
  MySQL-gated `Query`/`Table`/`Row`); the PyQt6 UI is verified by running the app.
- **Planner binding** — how the app entry point resolves a planner's manifest and
  its pretty-view module within the dashboard (firm up when the app is built).
