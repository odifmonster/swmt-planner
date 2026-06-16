# Specification of coverage of dashboard (persistence) tests

Covers the pure, server-independent pieces of `planners/infinite/dashboard`
landed so far — the **manifest** (`manifest.py`) and **connection-config
resolution** (`config.py`). The PyMySQL writer and the PyQt6 app are out of
scope here (the writer's end-to-end behavior is gated on a live MySQL; the app
is verified by running it).

## 1. Manifest ↔ live `DebugLog` consistency

The manifest is hand-maintained; these tests catch drift from the planner's
actual log (built via `run._build_debug_log()`, whose `.schema` /`.tables` are
the source of truth).

1. **Table set** — every `manifest.TABLES` spec's `debuglog` name is a real
   `DebugLog` table, and the set of `debuglog` names equals `debuglog.tables`
   (no missing/extra tables).
2. **Columns are identity** — each spec's `column_names` equals the live
   table's columns (`DebugLog.schema[name].columns`) as a set (order is the
   DB's; the writer projects by name).
3. **Primary keys** — each spec's `pk` is `(schema.pk,)` when the `DebugLog`
   table has a primary key, or `()` when it is key-less.
4. **Foreign keys ⊇ DebugLog's** — every `DebugLog` FK
   (`col -> ref_debuglog_table.ref_col`), with `ref_debuglog_table` mapped to
   its MySQL table name, appears in the spec's `fks`. The manifest may carry
   **extra** FKs not in `DebugLog.schema`.

## 2. Manifest structure

1. **Topological insert order** — for each spec in `TABLES`, every FK
   `ref_table` is either the run registry (`knitruns`) or a table appearing
   **earlier** in `TABLES` (so parents are inserted before children). This is
   what puts `demand` before `iteration_log` and `sched_cost_detail` before
   `production`.
2. **The extra production link** — `production`'s spec includes
   `ForeignKey('knit_id', 'knitschedcost', 'activity_id')` (a knit is a
   scheduled activity), which is **not** in `DebugLog.schema`.
3. **Run registry** — `manifest.RUNS` has `table == 'knitruns'`,
   `pk == ('run_id',)`, `debuglog is None`; `ALL_TABLES` is `(RUNS, *TABLES)`.
4. **Lookups** — `spec_for_debuglog` / `spec_for_table` return the matching
   spec and raise `KeyError` on an unknown name.

## 3. Connection-config resolution (`resolve_conn_config`)

`env` is passed explicitly (never touching the process environment).

1. **From the block** — a full `database` block resolves the right per-role
   user/password (`writer` vs `reader`), shared host/port/database.
2. **Environment wins** — when both a file value and the matching `SWMT_DB_*`
   var are present, the env value is used (shared fields + per-role
   `SWMT_DB_{ROLE}_USER` / `_PASSWORD`).
3. **Env-only** — `block=None` with the required vars in `env` resolves; the
   role sub-block being absent is fine when env supplies the user.
4. **Password may be `None`** — a null password in the block (and no env)
   yields `password=None` without error.
5. **Defaults** — absent host/port default to `127.0.0.1` / `3306`.
6. **Errors** — unknown role, missing database name, missing role user, and an
   unparseable port each raise `DatabaseConfigError`.

## 4. Persistence pure helpers (`persistence.py`, no server)

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

## 5. `persist_run` end-to-end (MySQL-gated)

Gated on a reachable local test MySQL (`swmtplannertests`, same schema as
production); the class **skips** when the server / driver is unavailable.
Connection details come from env vars with the project's test defaults
(host `127.0.0.1:3306`; roles `swmtwritetests` / `swmtreadtests`; admin
`stroot`). Each test **truncates all `knit*` tables** (via the admin role, FK
checks off) in `setUp`, so assertions use absolute counts.

1. **Round-trip** — `persist_run(debuglog, writer_conn, …)` returns an int
   `run_id`; `knitruns` then holds exactly one row, whose `total_score` /
   `n_unmet` / `start_date` match the arguments; and every manifest table's
   `COUNT(*) WHERE run_id = <id>` equals `len(get_df(name))`. (A successful
   insert also implicitly proves the FK-topological order, since the DB enforces
   the foreign keys.)
2. **Reconciled `role` column** — `knititerlog.role` round-trips: its distinct
   values are a subset of `{committed, rejected}`, `committed` is present, and
   the committed-row count matches the `DebugLog`'s.
3. **Run isolation** — a second `persist_run` returns a **distinct** `run_id`;
   `knitruns` holds two rows; each table has `n` rows per `run_id` and `2·n`
   total (clean slate).
4. **Read role can't write** — `persist_run(debuglog, reader_conn, …)` (the
   SELECT-only `swmtreadtests` role) raises `PersistenceError` and leaves
   `knitruns` empty (rollback) — confirming the grant-level read-only guarantee.
5. **`run.py` wiring** — `_persist_debuglog(db_block, debuglog, report,
   start_date, label, notes)` resolves the writer config from a `database`
   block, persists, and round-trips the `PlanReport` metadata **plus the
   `label` and (multi-line) `notes`** into `knitruns`; with `db_block=None` it
   returns `None` and writes nothing.
