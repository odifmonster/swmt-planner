# Debug Investigation — Design

The debug-investigation feature for the infinite planner: persist a run's
verbose `DebugLog` to a **local MySQL** database (one row-set per run, tagged by
an auto-incremented `run_id`), and investigate it through a **PyQt6 desktop
app** that pulls from that database on demand.

Replaces the earlier in-memory-HTML / TSV dashboard, which couldn't scale to a
real log (~6.5M rows). MySQL is the store; the app queries it (filtered, paged)
so neither the planner nor the app ever holds a whole table in memory.

Lives in `planners/infinite/dashboard/` (co-located with the planner whose log
it reads — and **necessarily planner-specific**: the exact tables, columns, and
links are baked into a manifest both halves share). Two halves around the DB:

```
  planner run ──(write path)──▶  local MySQL  ◀──(read path)── PyQt6 app
   DebugLog → INSERTs            (db: swmtinfinite)        paged SELECTs, per
   (tool only inserts)          run-tagged row-sets        run_id, filtered
```

The database is **dedicated to the knitting planner** (`swmtinfinite`; the test
copy is `swmtinftest`), so the MySQL base tables share their names with the
`DebugLog` tables — no translation. The `dashboard/` package: shared `manifest`
+ `config` at the top; the write path in `sqldump/`; the read/pagination layer
in `sqlload/`; the GUI in `app/` (later).

## The shared manifest (source of truth)

The MySQL schema is **user-provisioned** (DDL below, already run). A
hand-maintained **manifest** (`manifest.py`) is the single source of truth for
the table set, column types, primary keys, the FK graph, and the FK-topological
insert order. Both halves import it: the writer to lay out INSERTs, the app to
drive FK navigation, typing, and the table list. It is **not** derived from
`DebugLog.schema` — it adds column *types*, the FK-topological order, and one FK
link `DebugLog.schema` doesn't carry (see below).

Per table the manifest records a `TableSpec`:

- **`name`** — the table name, **identical** in the `DebugLog` (the row source,
  for the 8 detail tables) and the database. So `get_df(name)` reads the rows
  and `INSERT INTO name` writes them — no debuglog↔db translation.
- **`columns`** — ordered `(name, type, nullable)`; `type` ∈
  `int/float/str/datetime` drives the app's per-column filter modes.
- **`pk`** — the primary-key column(s) after the implicit leading `run_id`
  (empty for a key-less table).
- **`fks`** — `(column → ref_table.ref_column)`, the **full DB FK graph** (incl.
  the extra link below), for the app's drill-down and the writer's insert order.
- **`order_by`** — the stable paging order for a **key-less** table (set iff `pk`
  is empty). A keyed table paginates by its `pk`; the `order_columns` accessor
  returns whichever applies. (`priority_detail` → `move_id, item, week_idx`;
  `unmet_demand` → `item, week_idx`.)

### Tables

The eight `DebugLog` tables persist under their own names — `iteration_log`,
`cost_summary`, `inv_cost_detail`, `sched_cost_detail`, `priority_detail`,
`production`, `demand`, `unmet_demand` — plus the **`runs`** registry (run
metadata; owns the auto-incremented `run_id`; not a `DebugLog` table).
`priority_detail` and `unmet_demand` are key-less (no PK in the DDL beyond the
`run_id` FK). Columns are name-for-name identical to the `DebugLog`'s.

The DB also defines two **views** — **`committed_sched`** and
**`committed_prod`** — the committed-move slices of `sched_cost_detail` /
`production` (the "committed-only" derivation, realized as DB views rather than
app-side queries). They are **read-only** (the writer never touches them); the
`sqlload`/app side reads them. Out of scope for the writer + manifest's writable
table set; folded into the `sqlload` design.

### FK graph (from the DDL)

```
demand.run_id                       → runs.run_id
iteration_log (run_id, order_id)    → demand (run_id, order_id)       # order_id may be NULL
cost_summary (run_id, move_id)      → iteration_log (run_id, move_id)
inv_cost_detail (run_id, move_id)   → iteration_log (run_id, move_id)
inv_cost_detail (run_id, summary_id)→ cost_summary (run_id, summary_id)
sched_cost_detail (run_id, move_id) → iteration_log (run_id, move_id)
priority_detail (run_id, move_id)   → iteration_log (run_id, move_id)
production (run_id, move_id)         → iteration_log (run_id, move_id)
production (run_id, knit_id)         → sched_cost_detail (run_id, activity_id)   # NEW link: a knit IS a scheduled activity
unmet_demand.run_id                 → runs.run_id
```

The `production.knit_id → sched_cost_detail.activity_id` link is **not** in
`DebugLog.schema` (there `knit_id` is just `production`'s PK). The manifest adds
it, so the app can jump from a produced knit to its scheduled activity, and the
writer knows `production` must follow `sched_cost_detail`.

### Insert order (FK-topological)

Parents before children, so the real FK constraints hold:

```
runs → demand → iteration_log → cost_summary → inv_cost_detail
     → sched_cost_detail → production ; priority_detail , unmet_demand (after parents)
```

`demand` is built **last** in the `DebugLog` but must be inserted **before**
`iteration_log` (its `order_id` FK target). So the writer drives insertion from
the manifest's topological order, **not** `DebugLog.tables` declaration order.
Assumption the DDL bakes in: every non-NULL `iteration_log.order_id` appears in
`demand` (it does — `demand` has every regular + safety order; run-up jobs carry
`order_id = NULL`, allowed by the FK).

## Configuration — the `database` block

Both halves read MySQL settings from a **`database` block in the run-config
JSON** (the app takes the same file, or `--database` / env). The DB enforces a
**two-role separation** so the dashboard can't mutate data: one server-side user
has `SELECT, INSERT, UPDATE` (the **writer** — used by the planner to persist a
run), the other has only `SELECT` (the **reader** — used by the PyQt6 app).
Same host/port/name; different credentials. The block carries shared connection
fields plus a `writer` and a `reader` credential sub-block, with
**environment-variable fallback** for the passwords:

```json
"database": {
  "host": "127.0.0.1",
  "port": 3306,
  "name": "swmtinfinite",
  "writer": { "user": "swmt_writer", "password": null },   // null → SWMT_DB_WRITER_PASSWORD
  "reader": { "user": "swmt_reader", "password": null }     // null → SWMT_DB_READER_PASSWORD
}
```

- **Role separation is the guarantee.** The app connects as the reader, whose
  grant lacks `INSERT`/`UPDATE`/`DELETE`, so a UI bug or rogue query *cannot*
  alter the data — read-only is enforced by MySQL, not app discipline. The
  planner connects as the writer. (Run deletion / `label`/`notes` edits from the
  app would need the writer role; default app config carries only the reader, so
  those are off unless explicitly granted — revisit when the app adds them.)
- **Each side uses only its block.** The planner needs `writer` (+ host/port/
  name); the app needs `reader`. A side's block may be absent if that side never
  runs there.
- **Env fallback**: shared fields via `SWMT_DB_HOST` / `SWMT_DB_PORT` /
  `SWMT_DB_NAME`; per-role creds via `SWMT_DB_WRITER_USER` /
  `SWMT_DB_WRITER_PASSWORD` and `SWMT_DB_READER_USER` / `SWMT_DB_READER_PASSWORD`.
  Env wins over the file (so a committed config keeps non-secret defaults and
  leaves passwords to the environment).
- **Optional**: absent (and no `--verbose`) → the planner runs as today, no DB.
  Present + `--verbose` → the run is persisted (writer).
- **Driver**: **PyMySQL** (pure-python; a new dependency in `pyproject.toml`).
  PyQt6 is the other new dependency (app only).

## The MySQL schema (provided, user-owned)

The tool **only INSERTs** — never `CREATE`/`ALTER`. The schema below is the DDL
you ran (db `swmtinfinite`); the manifest mirrors it exactly. The writer fails
fast with a clear message if a table/column is missing.

- `runs` — `run_id BIGINT AUTO_INCREMENT PK`, `created_at DATETIME(6)
  DEFAULT CURRENT_TIMESTAMP(6)`, `start_date DATE`, `total_score DOUBLE`,
  `n_unmet INT`, `label VARCHAR(255)`, `notes TEXT`.
- Keyed detail tables carry `PRIMARY KEY (run_id, <pk>)`: `demand(order_id)`,
  `iteration_log(move_id)`, `cost_summary(summary_id)`, `inv_cost_detail(icost_id)`,
  `sched_cost_detail(activity_id)`, `production(knit_id)`.
- Key-less tables (`priority_detail`, `unmet_demand`) have only the `run_id` FK (no PK
  in the DDL — fine for INSERT-only).
- Reserved words backticked in the DDL: `iteration_log.rank`,
  `sched_cost_detail.desc`, `sched_cost_detail.start`/`end`, `production.start`/`end`,
  `inv_cost_detail.value`. The writer backticks **all** column names regardless.

## Write path — `persistence.py`

A single module under `planners/infinite/dashboard/` that persists a populated
`DebugLog` to MySQL using `DebugLog`'s read API + the `manifest`. It reuses
nothing planner-specific beyond the manifest and issues no `CREATE`/`ALTER`.

### Public API

```
persist_run(
    debuglog, conn,                       # ConnConfig for the WRITER role
    *, start_date, total_score, n_unmet, label=None,
) -> int                                  # the new run_id
```

`run.py` resolves the writer `ConnConfig` (`config.resolve_conn_config(
cfg['database'], 'writer')`) and pulls the three run-metadata scalars off the
`PlanReport`, so `persistence.py` stays decoupled from both the config-block
shape and the `PlanReport` type. `PersistenceError` is the module's error type.

### Algorithm

1. `conn = pymysql.connect(host, port, user, password, database=…,
   autocommit=False)`. **`import pymysql` is lazy** (inside this function) so the
   pure helpers below import without the driver installed.
2. INSERT the run row → `run_id` (auto-increment + `created_at` are
   server-filled; `start_date` truncated to its DATE column):
   `INSERT INTO runs (start_date, total_score, n_unmet, label) VALUES (…)`,
   then `run_id = cursor.lastrowid`.
3. For each `spec` in `manifest.TABLES` (already FK-topological), bulk-insert its
   run-tagged rows (see helpers) via chunked `executemany`.
4. `conn.commit()`. On any exception: `conn.rollback()` and raise
   `PersistenceError` naming the table; `conn.close()` in a `finally`. A failed
   run leaves nothing behind.

### Pure helpers (no DB — the unit-test surface)

- **`to_sql(value)`** — map one DataFrame cell to a PyMySQL value: `None` / NaN /
  `NaT` / `pd.NA` → SQL `NULL`; `pandas.Timestamp` → `datetime`
  (`.to_pydatetime()`); numpy scalar → native (`.item()`); else unchanged.
  (`pd.isna` is applied only to scalar cells, so it never returns an array.)
- **`insert_sql(spec)`** — the
  ``INSERT INTO `table` (`run_id`, `col`, …) VALUES (%s, …)`` string,
  **all identifiers backticked** (covers reserved `rank`/`desc`/`start`/`end`/`value`).
- **`project_rows(debuglog, spec, run_id)`** — read `get_df(spec.debuglog)`,
  expose a keyed table's PK (its index) as a column — `reset_index()` **only**
  when `index.name` is set, so a key-less table's RangeIndex isn't added —
  select the spec's columns **by name** (decoupled from `get_df`'s index/column
  split), and yield `(run_id, *map(to_sql, cells))` tuples. Empty tables yield
  nothing.

### Chunking

The per-table insert loop feeds `executemany` in chunks (e.g. 5 000 rows) so the
4.8M-row table never builds one giant statement / parameter list. The
`DebugLog` already holds every row in memory (built during the run), so this
adds no new peak; streaming straight to the DB during population stays a later
option if peak memory ever matters.

### Errors

Missing table / column (`pymysql` `ProgrammingError` 1146 / 1054) and FK
violations (`IntegrityError`) are caught and re-raised as `PersistenceError`
with a message naming the offending table and pointing at the provisioned-schema
contract (the DDL in this doc). The transaction rollback (step 4) ensures
partial writes never persist.

### Test split (next steps — paused here per request)

- **Pure (no server):** `to_sql` (each value kind → NULL / datetime / native /
  passthrough), `insert_sql` (backticking + column order), and `project_rows`
  (run-tag prepend, PK-as-column, NULL mapping, key-less + empty tables, row
  counts vs `get_df`) — all driven by a real `DebugLog`.
- **MySQL-gated (skipped when unreachable):** `persist_run` end-to-end on a
  local MySQL — round-trip row counts/values, `run_id` tagging across tables,
  and a second `persist_run` getting a distinct `run_id`.

### `run.py` wiring (separate step)

The `--verbose` block resolves the writer `ConnConfig` from `cfg['database']`
(skip when absent), calls `persist_run(debuglog, conn, start_date=sd.date(),
total_score=report.total_score, n_unmet=len(report.unmet_lbs_by_item_week))`,
and echoes the new `run_id`.

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
  a stable order, so the table's `order_columns` (its PK, or the manifest's
  `order_by` for a key-less table) drives it.

  The trailing `LIMIT`/`OFFSET` are filled per chunk via
  `query_str.format(limit=…, offset=…)`.

  At build time, `Query.build` uses the cursor to: (1) execute a query for the
  **total row count**; then (2) for each column, first query its **count of
  distinct values**, and — only when that count does **not** exceed `CHUNK_SIZE`
  — execute a second query to grab the actual **set of distinct values**. For
  columns whose distinct-value count exceeds `CHUNK_SIZE`, no values query runs
  and the column maps to `None`. These feed `nrows` and `unique(col)`.
- **Constructor (private)** — `Query` accepts the **cursor**, the **full SQL
  string**, the **row count**, and a **map of column name → distinct-value set
  (or `None`** when it exceeds `CHUNK_SIZE`). It is **only ever called by
  `Query.build`**; the class is **not** instantiated directly.
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
  if it exceeds the max chunk size (`CHUNK_SIZE`).
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

- **Construction** — instantiated with a **`TableSchema`**, a **cursor**, and a
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

A desktop app under `planners/infinite/dashboard/app/`, launched via the
`knit-debug` console entry point. It connects to the same MySQL as the
**reader** (`database.reader` creds — SELECT-only), and pulls everything with
`run_id`-scoped, **paged** SELECTs — **no query, filtered or not, is ever
unbounded.** Because the reader grant lacks write privileges, the app physically
cannot modify the data.

### Home — select a run

Queries `runs` (most recent first): `run_id`, `created_at`, `start_date`,
`total_score`, `n_unmet`, `label`. You pick one to investigate. (Annotating
`label`/`notes` or deleting a run are writes — out of scope for the read-only
reader role; if wanted later, they'd need a writer connection, kept off by
default.) Everything downstream is scoped to the chosen `run_id`.

### Investigation — raw, paged grids

Carries over the proven "raw view" concepts, SQL-backed and run-scoped:

- **Table list** — the nine tables (from the manifest), each opening a grid.
- **Grid** — a `QTableView` over a model that fetches **one page at a time**:
  `SELECT … WHERE run_id = :rid [AND <filters>] ORDER BY <pk> LIMIT :n OFFSET
  :o`, plus a `SELECT COUNT(*)` for the total; scrolling/paging fetches the next
  page on demand. **This is how every large result is handled — including
  foreign-key lookups.** A 1-row lookup and a 100k-row lookup page identically;
  the app never asks for "all matching rows."
- **Foreign-key / PK navigation** — clicking a FK cell opens the referenced
  table with an added filter (`WHERE run_id = :rid AND ref_col = :val`) — then
  paged like any grid. PK cells offer the same "show only this row" filter.
  Links come from the manifest's FK graph (incl. `production.knit_id →
  sched_cost_detail.activity_id`).
- **Per-column filters** — pushed to SQL `WHERE`: **value select** (`IN`),
  **>/</range** on numeric & datetime columns, **starts-with/contains** (`LIKE`)
  on text columns; column types come from the manifest. Filters AND together and
  with the FK/PK filter; re-querying resets to page 1.
- **Committed-only** — a toggle, realized as a query (join `sched_cost_detail` /
  `production` to `iteration_log` on `(run_id, move_id)` where `roll = 'committed'`)
  — **not** a stored table.
- **Schema view** — the FK graph from the manifest, documenting the tables and
  links (like the old Home schema cards).

The app holds the manifest statically (table/column/type/FK metadata); the DB
holds only data.

## Phasing

1. **Persistence** — the `database` config block (+ env, `writer`/`reader`
   roles), the manifest, the PyMySQL writer (connect as writer, topological
   INSERTs, run-tagging), `run.py` wiring. Add `pymysql`. Unit-test the pure
   pieces (config resolution incl. env + roles, row→SQL incl. NULL/NaT,
   INSERT/column construction, the topological order); gate end-to-end write
   tests on a reachable local MySQL (skip otherwise).
2. **App shell + Home** — connect as the reader; list / select runs. Add
   `PyQt6` (consider an optional extra so headless installs skip it). Entry
   point `knit-debug`.
3. **Raw grids + FK navigation** — run-scoped paged grids, FK/PK drill, schema
   view.
4. **Per-column filters + committed-only** — the SQL-backed filters and toggle.

(The DDL is reconciled to the `DebugLog`: `iteration_log.role` and
`unmet_demand.unmet_lbs` are both present, so the manifest column mapping is pure
identity — only table names differ.)

## Open items

- **Dependencies** — add `pymysql` (planner + app); `pyqt6` is already in
  `requirements.txt`. Mirror into `pyproject.toml` (PyQt6 ideally an optional
  extra for headless installs).
- **Testing the DB layers** — pure pieces unit-tested without a server;
  end-to-end write/read gated on a local MySQL. PyQt6 UI verified by running the
  app, consistent with prior rendering decisions.
