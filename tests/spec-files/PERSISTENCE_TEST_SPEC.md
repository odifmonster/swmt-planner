# Specification of coverage of debug-log persistence tests

Covers the infinite planner's debug-log persistence (`tests/persistence_tests.py`):
its concrete **manifest** (`planners/infinite/manifest.py`, checked against the
live `DebugLog`) and the **`sqldump` writer** (`persistence.py` — pure helpers +
a MySQL-gated end-to-end). The generic dashboard (config + read layer) is covered
by `DASHBOARD_TEST_SPEC.md`; the PyQt6 app is verified by running it.

## 1. Manifest ↔ live `DebugLog` consistency

The manifest is hand-maintained; these tests catch drift from the planner's
actual log (built via `run._build_debug_log()`, whose `.schema` /`.tables` are
the source of truth).

1. **Table set** — table names are identical to the `DebugLog`'s (the DB is
   dedicated to the planner), so the set of `manifest.TABLES` `name`s equals
   `debuglog.tables` (no missing/extra tables).
2. **Columns are identity** — each spec's `column_names` equals the live
   table's columns (`DebugLog.schema[name].columns`) as a set (order is the
   DB's; the writer projects by name).
3. **Primary keys** — each spec's `pk` is `(schema.pk,)` when the `DebugLog`
   table has a primary key, or `()` when it is key-less.
4. **Foreign keys ⊇ DebugLog's** — every `DebugLog` FK
   (`col -> ref_table.ref_col`) appears verbatim in the spec's `fks` (names
   match, so no mapping). The manifest may carry **extra** FKs not in
   `DebugLog.schema`.

## 2. Manifest structure

1. **Topological insert order** — for each spec in `TABLES`, every FK
   `ref_table` is either the run registry (`runs`) or a table appearing
   **earlier** in `TABLES` (so parents are inserted before children). This is
   what puts `demand` before `iteration_log` and `sched_cost_detail` before
   `production`.
2. **The extra production link** — `production`'s spec includes
   `ForeignKey('knit_id', 'sched_cost_detail', 'activity_id')` (a knit is a
   scheduled activity), which is **not** in `DebugLog.schema`.
3. **Run registry** — `manifest.RUNS` has `name == 'runs'`,
   `pk == ('run_id',)`; `ALL_TABLES` is `(RUNS, *TABLES)`.
4. **Lookups** — `spec_for_name` returns the matching spec (any detail table or
   `runs`) and raises `KeyError` on an unknown name.

## 3. Persistence pure helpers (`persistence.py`, no server)

Driven by a real populated `DebugLog`; no MySQL.

1. **`to_sql`** — `None` / float-NaN / numpy-NaN / `NaT` / `pd.NA` → `None`;
   python & numpy float → python `float` (non-NaN); numpy int → python `int`;
   `str` passes through unchanged; `pandas.Timestamp` (incl. a date-only one)
   → `datetime`.
2. **`insert_sql`** — for a spec, names `run_id` first then the spec's columns
   in order, every identifier backticked (checked on `sched_cost_detail`, which
   has reserved `desc`/`start`/`end`); placeholder count `== 1 + len(columns)`.
3. **`project_rows`** — yields one tuple per `get_df` row (count matches); each
   is `(run_id, *cells)` of width `1 + len(columns)` with `run_id` first; a
   keyed table's PK appears as a data column (`iteration_log.move_id`); an empty
   key-less table (`unmet_demand`) yields nothing.

## 4. `persist_run` end-to-end (MySQL-gated)

Gated on a reachable local test MySQL (`swmtinftest`, same schema as
production); the class **skips** when the server / driver is unavailable.
Connection details come from env vars with the project's test defaults
(host `127.0.0.1:3306`; roles `knitwritetest` / `knitreadtest`, password
`testpass`; admin `ktroot`). Each test **truncates all base tables** (via the
admin role, FK checks off) in `setUp`, so assertions use absolute counts.

1. **Round-trip** — `persist_run(debuglog, writer_conn, …)` returns an int
   `run_id`; `runs` then holds exactly one row, whose `total_score` /
   `n_unmet` / `start_date` match the arguments; and every manifest table's
   `COUNT(*) WHERE run_id = <id>` equals `len(get_df(name))`. (A successful
   insert also implicitly proves the FK-topological order, since the DB enforces
   the foreign keys.)
2. **Reconciled `role` column** — `iteration_log.role` round-trips: its distinct
   values are a subset of `{committed, rejected}`, `committed` is present, and
   the committed-row count matches the `DebugLog`'s.
3. **Run isolation** — a second `persist_run` returns a **distinct** `run_id`;
   `runs` holds two rows; each table has `n` rows per `run_id` and `2·n`
   total (clean slate).
4. **Read role can't write** — `persist_run(debuglog, reader_conn, …)` (the
   SELECT-only `knitreadtest` role) raises `PersistenceError` and leaves
   `runs` empty (rollback) — confirming the grant-level read-only guarantee.
5. **`run.py` wiring** — `_persist_debuglog(db_block, debuglog, report,
   start_date, label, notes)` resolves the writer config from a `database`
   block, persists, and round-trips the `PlanReport` metadata **plus the
   `label` and (multi-line) `notes`** into `runs`; with `db_block=None` it
   returns `None` and writes nothing.
