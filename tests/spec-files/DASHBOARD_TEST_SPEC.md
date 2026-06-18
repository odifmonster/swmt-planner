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

## 6. Read layer (`sqlload`) — query inputs (`helpers.py`, no server)

The `Filter` / `FKLookup` dataclasses that compile a single column's constraint
into a SQL **format string** (`Filter` → a `{colname}` `WHERE` fragment;
`FKLookup` → an `{ftable}`/`{fcol}`/`{run_id}` `INNER JOIN`). All pure — no DB.
Validation is **lazy**: a malformed value is accepted by the constructor and
only rejected when `to_sql_str()` is first called. (The run-scoped, paginated
behavior of `Query` / `Table` — sections to follow — is MySQL-gated and will run
against a fake run of generated rows large enough to exercise chunking, the
half-chunk window, and lazy loading.)

### 6.1 `Filter.to_sql_str`

1. **Lazy validation** — constructing a `Filter` with a mismatched `kind`/`rule`
   does **not** raise; the error surfaces only on `to_sql_str()`.
2. **Error — bad kind** — an unrecognized `kind` raises `FilterError`.
3. **Error — bad rule per kind**, each raising `FilterError`:
   - `selection` / `exclusion` with a non-set `rule`, and with an **empty** set.
   - `range` with a non-tuple / wrong-length `rule`, and with `(None, None)`
     (unbounded on both ends).
   - `pattern` with a non-`str` `rule`.
4. **`selection`** — `{colname} IN (…)`: the rule's values rendered as SQL
   literals (strings single-quoted, numbers bare), comma-joined in sorted order;
   `format(colname=…)` substitutes the column.
5. **`exclusion`** — as selection but `{colname} NOT IN (…)`.
6. **`range` — low only** — `(low, None)` → `{colname} >= <low>` (single term).
7. **`range` — high only** — `(None, high)` → `{colname} <= <high>`.
8. **`range` — both bounds** — `(low, high)` →
   `{colname} >= <low> AND {colname} <= <high>`.
9. **`pattern`** — `{colname} LIKE '<pattern>'` (the LIKE pattern quoted as a
   string literal).

### 6.2 `FKLookup.to_sql_str`

1. **Error — empty `vals`** — `to_sql_str()` on an `FKLookup` with no values
   raises `FilterError`.
2. **Valid output** — for a concrete `(ref_table, ref_col, vals)`,
   `format(ftable=…, fcol=…, run_id=…)` yields the expected `INNER JOIN` against
   a sub-query: `SELECT run_id, <ref_col> FROM <ref_table> WHERE run_id =
   <run_id> AND <ref_col> IN (<sorted literals>)`, aliased `fk_<fcol>` and joined
   on the main table's `(run_id, <fcol>)` matching the sub-query's
   `(run_id, <ref_col>)` — all identifiers backticked.

## 7. Read layer (`sqlload`) — `Query` (MySQL-gated)

Gated on the same reachable local test MySQL as §5 (skips when unavailable).
`setUp` persists a populated run (a real `DebugLog` via `persist_run`, as in §5)
and connects a cursor scoped to that `run_id`; **`query.CHUNK_SIZE` (and
`query._HALF`) are reduced** so the larger tables (e.g. `cost_summary`,
`inv_cost_detail`) span several chunks, exercising chunking, the half-chunk
window, and lazy loading without millions of rows. Expected rows are derived
from each table's contents ordered by its `order_columns` (the same `ORDER BY`
`build` emits).

### 7.1 `Query.build` — column validation

1. **Unknown column** — a constraint keyed on a column not in the table spec
   raises `ValueError`. (Raised before any SQL runs, so a dummy cursor suffices —
   no populated DB needed for this check.)
2. **Wrong constraint type** — a constraint value that is neither a `Filter` nor
   an `FKLookup` raises `TypeError`.

### 7.2 `nrows`

1. **Within a chunk** — for a table whose matched count is **≤ `CHUNK_SIZE`**,
   `nrows` equals the true row count for the run.
2. **Across chunks** — for a table whose count **exceeds `CHUNK_SIZE`**, `nrows`
   still equals the full count (the total, not one chunk's worth).
3. **Filtered** — with a `Filter` applied, `nrows` reflects the **filtered**
   count, matching a direct `COUNT(*)` under the same predicate.

### 7.3 `unique`

1. **All columns** — for each displayed column whose distinct count is within
   `CHUNK_SIZE`, `unique(col)` returns exactly that column's set of distinct
   values for the run.
2. **Over the cutoff → `None`** — a column with **more than `CHUNK_SIZE`**
   distinct values (e.g. the PK of a table exceeding `CHUNK_SIZE` rows) yields
   `None` rather than a set.

### 7.4 `next_chunk` / `prev_chunk` (chunk windowing)

1. **Expected chunks** — starting from the first `next_chunk`, each call returns
   the rows of the window at the next half-chunk step — i.e. the ordered result
   sliced `[step·(CHUNK_SIZE/2), … + CHUNK_SIZE)`; `prev_chunk` returns the
   preceding window. `row_offset` reports the window's absolute row offset.
2. **Lazy loading** — the chunk is fetched only when the window actually moves;
   the first `next_chunk` loads the first chunk, and a step that doesn't change
   the window re-uses the held chunk (no new fetch).
3. **Clamp at the end** — once the window covers the last rows, a further
   `next_chunk` returns the **same** final chunk (no advance past the end).
4. **Clamp at the start** — at the first window, `prev_chunk` returns the
   **same** first chunk (no retreat before row 0).

## 8. Read layer (`sqlload`) — `Table` / `Row` (MySQL-gated)

Same gated, populated run as §7 with `CHUNK_SIZE` reduced; tests set a known
`page_size` via `Table.set_page_size` (restoring it and `CHUNK_SIZE` afterward,
since both are shared state). Expected rows are the table's contents ordered by
its `order_columns` (matching `build`'s `ORDER BY`); a page's expected `Row`
`data` is that ordered slice.

### 8.1 Initial state (constructed, before the first page)

1. **`nrows`** — equals the table's row count for the run.
2. **`selected_keys`** — empty.
3. **`displayed_range`** — `(0, 0)` (nothing displayed yet).
4. **`_chunk`** — `None` (no fetch until the first page).
5. **`_conds`** — every displayed column maps to `None` (no constraints).
6. **`_offset`** — `0`.

### 8.2 After the first `next_page()`

1. **`nrows`** — unchanged.
2. **`selected_keys`** — still empty.
3. **`_chunk`** — no longer `None` (the first chunk is loaded).
4. **Returned rows** — the `Row`s' `data` match the expected first page (the
   ordered rows `[0 : page_size]`), in order.

### 8.3 `next_page()` then `prev_page()` round-trip

1. From the first page, `next_page()` (to page 2) then `prev_page()` returns
   `displayed_range` to its original first-page value; the returned `Row`s again
   match the first page; `nrows` unchanged and `selected_keys` still empty.

### 8.4 `next_page()` on the last page

1. Paging to the last page and then calling `next_page()` again leaves
   everything unchanged: same `displayed_range`, same returned rows, and the
   same `_chunk` window / `_offset` (idempotent at the end).

### 8.5 `prev_page()`

1. **Moves back** — from a later page (after several `next_page()` calls),
   `prev_page()` shifts `displayed_range` back by one `page_size`; the returned
   `Row`s match the previous page's ordered slice; `nrows` unchanged and
   `selected_keys` still empty.
2. **Idempotent on the first page** — `prev_page()` while on the first page
   leaves everything unchanged: same `displayed_range` (`(0, …)`), same returned
   rows, same `_chunk` window / `_offset` (no retreat before row 0).

### 8.6 Row counts vs. page size

1. **`displayed_range` capped at `nrows`** — a page that would run past the end
   stops at `nrows` (`end == nrows`, never beyond); a `page_size >= nrows` shows
   the whole table as one page `(0, nrows)`.
2. **`set_page_size` rejects invalid values** — non-int, `< 1`, and
   `> CHUNK_SIZE // 2` each raise `ValueError` and leave the size unchanged.
3. **Resize + `reload_page`** — from a known page, **shrinking** `page_size`
   then `reload_page()` keeps the same start and narrows `displayed_range`
   (fewer rows); **growing** it then `reload_page()` keeps the same start and
   widens the range (more rows, capped at `nrows`).
4. **`reload_page` vs `next_page` on the last page after a resize** — on the
   last page, after **growing** `page_size`: `reload_page()` keeps the same
   first row (so `displayed_range` start is unchanged, a partial page), whereas
   `next_page()` **re-aligns** to a `page_size` boundary (start moves to the last
   aligned page). The two start indices differ — the official check of the
   keep-the-offset-vs-realign distinction.

## 9. Read layer (`sqlload`) — selection & filtering (MySQL-gated)

Same gated, populated run and ordering as §8. Filtered/looked-up expectations
are computed from the table's contents ordered by `order_columns` with the same
predicate applied; selection cases use a keyed table (e.g. `iteration_log`,
PK `move_id`) and the raise cases a key-less one (`priority_detail`).

### 9.1 Row selection (`Row.select` / `Row.deselect`)

1. **Key-less table raises** — `select()` and `deselect()` on a `Row` of a
   key-less table raise `TypeError`.
2. **Redundant calls are no-ops** — `select()` on an already-selected row, and
   `deselect()` on a row that isn't selected, leave `selected_keys` unchanged.
3. **Updates `selected_keys`** — `select()` adds the row's PK value and
   `deselect()` removes it; `Row.selected` reflects membership; selection
   survives paging (`next_page` / `prev_page` don't clear it).

### 9.2 Filters (`apply_filter_to` / `remove_filter`)

1. **`apply_filter_to` resets state** — after applying, the column's `_conds`
   entry holds the `Filter`, `_chunk` is `None`, `_offset` is `0`, and
   `selected_keys` is cleared (the query is rebuilt).
2. **Filtered rows** — `next_page()` after `apply_filter_to` returns exactly the
   rows satisfying the predicate (against the ordered, filtered contents).
3. **`remove_filter` with no active filter** — calling `remove_filter` on a
   column that has none still resets state, and `next_page()` returns the full
   (unfiltered) rows.
4. **`remove_filter` with an active filter** — removing the column's filter
   resets state, and `next_page()` returns the unfiltered rows again.
5. **Two filters, remove one** — apply a `Filter` to two columns, then
   `remove_filter` one; `next_page()` returns the rows matching **only** the
   remaining filter.

### 9.3 FK lookups (`apply_fk_lookup`) and clearing them

1. **Non-FK column raises** — `apply_fk_lookup` on a column that isn't a foreign
   key raises `KeyError` (likewise an unknown column).
2. **Selects matching rows** — `apply_fk_lookup(fkcol, values)` makes
   `next_page()` return exactly the rows whose `fkcol` is one of `values`.
3. **End-to-end routing** — selecting PK values in a referenced table `t1`, then
   `t2.apply_fk_lookup(fkcol, t1.selected_keys)` (e.g. `t1 = demand` →
   `t2 = iteration_log` on `order_id`) returns `t2`'s rows referencing exactly
   those selected keys.
4. **`remove_filter` clears an FK lookup** — `remove_filter(fkcol)` after an
   `apply_fk_lookup` resets state, and `next_page()` returns the unrestricted
   rows.
5. **Clearing one constraint leaves the others** — with a `Filter` on another
   column still applied, `remove_filter` on the FK column leaves that filter in
   effect; `next_page()` returns the rows matching the remaining filter.
