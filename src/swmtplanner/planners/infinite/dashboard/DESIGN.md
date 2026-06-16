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
   DebugLog → INSERTs            (db: swmtplanner)         paged SELECTs, per
   (tool only inserts)          run-tagged row-sets        run_id, filtered
```

## The shared manifest (source of truth)

The MySQL schema is **user-provisioned** (DDL given below, already run) and its
table/column names differ from the `DebugLog`'s. A hand-maintained
**manifest** — a small static module in this package (e.g.
`planners/infinite/dashboard/manifest.py`) — is the single source of truth that
maps the `DebugLog` to the database and records the link graph. Both halves
import it: the writer to lay out INSERTs, the app to drive FK navigation,
typing, and the table list. It is **not** derived from `DebugLog.schema`,
because the DB schema diverges from it (renamed tables/columns, an extra FK).

Per table the manifest records:

- **`debuglog`** — the in-memory `DebugLog` table name (source of rows).
- **`table`** — the MySQL table name.
- **`columns`** — ordered `(debuglog_col, db_col, type, nullable)`; `debuglog_col`
  is how the writer reads the value, `db_col` how it INSERTs / the app queries.
- **`pk`** — the DB primary-key column(s) after `run_id` (or none).
- **`fks`** — `(db_col → ref_table.ref_col)`, the **full DB FK graph** (incl.
  links not in `DebugLog.schema`), for the app's drill-down and the writer's
  insert ordering.

### DebugLog → MySQL mapping

| DebugLog table | MySQL table | notes |
|---|---|---|
| `iteration_log` | `knititerlog` | |
| `cost_summary` | `knitcostsum` | |
| `inv_cost_detail` | `knitinvcost` | |
| `sched_cost_detail` | `knitschedcost` | |
| `priority_detail` | `knitpriority` | no PK in DDL (FK on `run_id,move_id` only) |
| `production` | `knitprod` | |
| `demand` | `knitdmnd` | |
| `unmet_demand` | `knitunmet` | |
| *(run metadata)* | `knitruns` | not a `DebugLog` table; owns `run_id` |

Columns match **name-for-name** in every table — the DDL was reconciled to the
`DebugLog` (`knititerlog.role`, `knitunmet.unmet_lbs`). So the manifest's
`db_col` equals its `debuglog_col` throughout; the column mapping is kept in the
manifest structure (for generality + types) but is identity today. Only the
**table names** differ.

### FK graph (from the DDL)

```
knitdmnd.run_id                      → knitruns.run_id
knititerlog (run_id, order_id)       → knitdmnd (run_id, order_id)      # order_id may be NULL
knitcostsum (run_id, move_id)        → knititerlog (run_id, move_id)
knitinvcost (run_id, move_id)        → knititerlog (run_id, move_id)
knitinvcost (run_id, summary_id)     → knitcostsum (run_id, summary_id)
knitschedcost (run_id, move_id)      → knititerlog (run_id, move_id)
knitpriority (run_id, move_id)       → knititerlog (run_id, move_id)
knitprod (run_id, move_id)           → knititerlog (run_id, move_id)
knitprod (run_id, knit_id)           → knitschedcost (run_id, activity_id)   # NEW link: a knit IS a scheduled activity
knitunmet.run_id                     → knitruns.run_id
```

The `knitprod.knit_id → knitschedcost.activity_id` link is **not** in
`DebugLog.schema` (there `knit_id` is just `production`'s PK). The manifest adds
it, so the app can jump from a produced knit to its scheduled activity, and the
writer knows `knitprod` must follow `knitschedcost`.

### Insert order (FK-topological)

Parents before children, so the real FK constraints hold:

```
knitruns → knitdmnd → knititerlog → knitcostsum → knitinvcost
        → knitschedcost → knitprod ; knitpriority , knitunmet (anytime after their parents)
```

`demand` (`knitdmnd`) is built **last** in the `DebugLog` but must be inserted
**before** `iteration_log` (its `order_id` FK target). So the writer drives
insertion from the manifest's topological order, **not** `DebugLog.tables`
declaration order. Assumption the DDL bakes in: every non-NULL
`iteration_log.order_id` appears in `demand` (it does — `demand` has every
regular + safety order; run-up jobs carry `order_id = NULL`, allowed by the FK).

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
  "name": "swmtplanner",
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
you ran (db `swmtplanner`); the manifest mirrors it exactly. The writer fails
fast with a clear message if a table/column is missing.

- `knitruns` — `run_id BIGINT AUTO_INCREMENT PK`, `created_at DATETIME(6)
  DEFAULT CURRENT_TIMESTAMP(6)`, `start_date DATE`, `total_score DOUBLE`,
  `n_unmet INT`, `label VARCHAR(255)`, `notes TEXT`.
- Keyed detail tables carry `PRIMARY KEY (run_id, <pk>)`: `knitdmnd(order_id)`,
  `knititerlog(move_id)`, `knitcostsum(summary_id)`, `knitinvcost(icost_id)`,
  `knitschedcost(activity_id)`, `knitprod(knit_id)`.
- Key-less tables (`knitpriority`, `knitunmet`) have only the `run_id` FK (no PK
  in the DDL — fine for INSERT-only).
- Reserved words backticked in the DDL: `knititerlog.rank`,
  `knitschedcost.desc`, `knitschedcost.start`/`end`, `knitprod.start`/`end`,
  `knitinvcost.value`. The writer backticks **all** column names regardless.

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
   `INSERT INTO knitruns (start_date, total_score, n_unmet, label) VALUES (…)`,
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

## Read path — the PyQt6 app

A desktop app under `planners/infinite/dashboard/app/`, launched via the
`knit-debug` console entry point. It connects to the same MySQL as the
**reader** (`database.reader` creds — SELECT-only), and pulls everything with
`run_id`-scoped, **paged** SELECTs — **no query, filtered or not, is ever
unbounded.** Because the reader grant lacks write privileges, the app physically
cannot modify the data.

### Home — select a run

Queries `knitruns` (most recent first): `run_id`, `created_at`, `start_date`,
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
  Links come from the manifest's FK graph (incl. `knitprod.knit_id →
  knitschedcost.activity_id`).
- **Per-column filters** — pushed to SQL `WHERE`: **value select** (`IN`),
  **>/</range** on numeric & datetime columns, **starts-with/contains** (`LIKE`)
  on text columns; column types come from the manifest. Filters AND together and
  with the FK/PK filter; re-querying resets to page 1.
- **Committed-only** — a toggle, realized as a query (join `knitschedcost` /
  `knitprod` to `knititerlog` on `(run_id, move_id)` where `roll = 'committed'`)
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

(The DDL is reconciled to the `DebugLog`: `knititerlog.role` and
`knitunmet.unmet_lbs` are both present, so the manifest column mapping is pure
identity — only table names differ.)

## Open items

- **Dependencies** — add `pymysql` (planner + app); `pyqt6` is already in
  `requirements.txt`. Mirror into `pyproject.toml` (PyQt6 ideally an optional
  extra for headless installs).
- **Testing the DB layers** — pure pieces unit-tested without a server;
  end-to-end write/read gated on a local MySQL. PyQt6 UI verified by running the
  app, consistent with prior rendering decisions.
