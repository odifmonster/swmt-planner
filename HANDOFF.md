# Knit-planner refactor — session handoff

## Project context

Working in `~/git-repos/swmt-projs/knit-planner/` — a Python supply-chain
scheduling tool for a textile (knitting) manufacturer. This is one of
several parallel versions; this version implements **only the knitting
plant**, and **this branch is the live patch branch** (quick, targeted
patches — it does *not* follow the design-driven-python plugin's templates;
the other branches do). Layout:

- `src/swmtplanner/schedule/` — per-machine activity scheduling
  (`Machine`, `Activity` subclasses, `Status`; `job/` submodule with the
  `Job`/`Roll` records).
- `src/swmtplanner/demand/` — per-item demand/fulfillment views
  (`RlsItem`, raw + safety-aware views).
- `src/swmtplanner/planners/infinite/` — the greedy planner that composes the
  two; CLI + report writer live here (`costing/`, `loop/`, `report.py`,
  `run.py`), plus its **debug schema** (`manifest.py`) and the **`sqldump/`**
  SQL Server writer (`persist_run`).
- `src/swmtplanner/debuglog/` — the planner-agnostic `DebugLog` audit-log
  container (top-level, used by the planner under `--verbose`).
- `src/swmtplanner/dashboard/` — the **planner-agnostic debug-log viewer**
  (top-level): generic `manifest` dataclasses + reader `config`, the `sqlload`
  read/pagination layer, and the PyQt6 `app/` (GUI, later). Owns all GUI.
- `tests/` — `*_tests.py` modules (+ the shared `sqlserver_support.py` helper);
  coverage specs in `tests/spec-files/` (`SCHEDULE_TEST_SPEC.md`,
  `DEMAND_TEST_SPEC.md`, `COORD_TEST_SPEC.md`, `INF_PLAN_TEST_SPEC.md`,
  `DEBUGLOG_TEST_SPEC.md`, `PERSISTENCE_TEST_SPEC.md`, `DASHBOARD_TEST_SPEC.md`,
  `RUN_TEST_SPEC.md`).

Each major submodule has a `DESIGN.md` that is the source of truth for
structure before implementation. **Stub (`.pyi`) files are a standing
convention**: every module in the dashboard / persistence subpackages has one,
created with the code and kept in sync.

**Running tests / Python:** the project virtualenv is `.dev-venv` (has
pandas/numpy + pyodbc — reaching a server also needs the ODBC driver installed;
no pytest). Run with:
`PYTHONPATH=src:. .dev-venv/bin/python -m unittest tests.<module>`
(e.g. `tests.machine_tests`).

> **Suite state:** **713 tests pass, 4 skip** (`python -m unittest discover -s
> tests -p '*_tests.py'`; as of 2026-10-15 on branch `knit-only`). The 4 skips are the **SQL Server-gated** classes —
> `persist_run` end-to-end plus the `sqlload` read layer against a live store —
> which probe a `SWMT_TEST_*` SQL Server test database in `setUpClass` and skip
> when the driver/server is unreachable. **No test database exists yet**, so they
> currently always skip; the SQL Server translation is instead proven by pure
> tests (storage mapping, `insert_sql`/`project_rows`, `Query.build` SQL text,
> `connect` wiring) and must be smoke-checked manually against the real DB.
> The planner prints `Total moves committed: N` (and per-table `Dumping …` lines
> during a verbose persist) to stdout — intentional source-side prints, harmless
> to the suite.

## Preferred workflow

For any significant change: **DESIGN.md first** (iterate over multiple turns,
one section/concept per turn — the user reviews each before moving on), then
**code**, then **coverage spec**, then **test code**, then run. Small,
reviewable diffs; don't sweep multiple subsystems at once. The user tolerates
the docs/code being temporarily inconsistent across sections rather than a
big sweep, and explicitly calls out which sections to do or skip. Surface
design gaps/conflicts rather than papering over them — this has repeatedly
caught real issues (e.g. the smoke test that caught `next_runout` not folding
in doff time). Commits are the user's to make.

## Schedule layer — ✅ committed

A three-step rework of the schedule/production layer is **complete and
committed** (design, code, tests, specs; suite green). In brief: the production
schedule (`Job`/`Roll` records, `ProductionPlan`) is separated from the activity
schedule; a runout model (`BEAM_FLOOR_LBS`, mid-roll beam swaps, max-waste,
unknit-yarn `Waste`) drives beam management; and the activity set is per-roll
`Doff` + `Hanging`/`Threading` (replacing `BeamLoad`, with a remove→hang→thread
guard rail) and a three-way changeover split (`StyleChange` / `RunnerChange` /
`PatternChange`), alongside a `Status` accessor refactor. Full detail lives in
`schedule/DESIGN.md` and `planners/infinite/DESIGN.md`.

## Debug log + investigation — data layer done; GUI through phase 4

A codebase-wide **debug mode**: the planner records *why* each move was chosen
into a `DebugLog`, persists a run to a **SQL Server** store, and investigates it
through a planner-agnostic **PyQt6 dashboard**. The debug log, the writer, and
the dashboard's `sqlload` read layer are done (the earlier MySQL-era pieces
committed; the composite-PK + two-new-table work **and the SQL Server
cut-over** are in the working tree); the GUI is built through phase 4, with the
pretty view (phase 5) remaining.

**Store cut-over (MySQL → SQL Server, pyodbc) — in the working tree, pure tests
green, real-DB smoke pending.** Three physical differences from the logical
manifest, all hidden by one generic module, `dashboard/storage.py`: (1) every
table is `knit_`-prefixed (`TableSpec.db_name`; only SQL text uses it); (2) each
`datetime` column is an INT pair `<stem>_date` (YYYYMMDD) / `<stem>_time`
(HHMMSS) at second precision, the stem being the name minus a trailing `_date`
(`start`→`start_date`/`start_time`, but `due_date`→`due_date`/`due_time`); (3) a
`date` column (only `runs.start_date`) is a lone YYYYMMDD INT. The dialect is
T-SQL: bracket quoting, `?` placeholders, `OFFSET … ROWS FETCH NEXT … ROWS ONLY`,
`LIKE … ESCAPE '\'`, `OUTPUT INSERTED.run_id`. `Query` selects the physical
columns and recombines pairs into logical rows, orders/compares datetimes via the
combined `CAST(_date AS BIGINT)*1000000 + _time` integer, so `Table`/`Row`/the
GUI are unchanged. Design: `dashboard/DESIGN.md` "Storage mapping" and
`planners/infinite/DESIGN.md` "Debug-log persistence to SQL Server".

### The debug log — `swmtplanner.debuglog` (done)

`DebugLog` is a generic, config-driven container of named tables (declare tables
+ `set_pk` / `set_fk`; populate with `add_row` / `update_row`; read with
`get_df` / `get_nrows` / the `tables` / `schema` accessors). It is
planner-agnostic, hard-coding no schema of its own. **Primary keys may be
composite**: `set_pk(table, *columns)` stores `@pk_cols` as a tuple and keys rows
by the tuple of PK values; the public API returns a **scalar for a single-column
PK** (back-compat) and a **tuple for a composite** one. `add_row`/`get_last_pk_val`
follow that; `get_df` keeps a composite PK's columns as ordinary leading columns
(no MultiIndex). An FK may reference only a **single-column** PK.
`TableSchema.pk` is now a `tuple[str, ...]` (empty for key-less).

The planner threads it as an optional `debuglog` kwarg through the loop +
costing and **populates ten tables** — live per-iteration: `iteration_states`
(window end + reference week), `iteration_log`, `cost_summary`,
`inv_cost_detail`, `sched_cost_detail`, `priority_detail`, `production`; once
before the loop: `run_configs` (cost weights + State knobs, timedeltas in hours,
keyed by composite `(kind, label)`); and post-loop copies of `demand` /
`unmet_demand`. Supporting provenance feeds these: `Job.tgt_order`, per-roll
`Roll.knits`, and the `SafetyAwareView` roll→order fill-links. This **replaced**
an earlier after-the-fact reconstruction (the old `iterlog` / `cost_breakdown`
machinery), which has been removed. Design: `swmtplanner/debuglog/DESIGN.md`.

### Planner-owned: debug schema + SQL Server writer (done)

The SQL Server database is **shared with other tables**, so this planner's are
all stored under `knit_`-prefixed physical names (`db_name`) while keeping their
logical `DebugLog` names; it also holds the `knit_runs` registry and two
read-only views (`knit_committed_sched` / `knit_committed_prod`, the
committed-move slices). Temporal columns are INTs (see the store cut-over note
above). The schema is **user-provisioned** — the tool only INSERTs. The planner
owns its concrete schema + the write path:

- **`planners/infinite/manifest.py`** — the concrete schema for **ten** tables
  (+ the `runs` registry and the two committed views): per-table column types,
  PKs (incl. `run_configs`' composite `(kind, label)`), the FK graph (incl.
  `production.knit_id → sched_cost_detail.activity_id` and `iteration_log.
  iteration_idx → iteration_states.iteration_idx`, links beyond `DebugLog.schema`,
  plus the committed views' identity-column FK back to `sched_cost_detail`), the
  FK-topological insert order (`iteration_states` before `iteration_log`), and
  per-table `order_by` (the explicit paging order, overriding the pk when set).
  Built from the generic dataclasses in `swmtplanner.dashboard.manifest`; each
  `TableSpec` also carries a `disp_name` + `desc` for the GUI. A test guards it
  against drift from the live `DebugLog`. The SQL Server DDL is documented in
  `planners/infinite/DESIGN.md` (Debug-log persistence).
- **`planners/infinite/sqldump/persistence.py`** — `persist_run(debuglog, conn,
  …)`: connect as the writer via `config.connect` (pyodbc), INSERT the
  `knit_runs` row with `OUTPUT INSERTED.run_id` (`created_at` supplied from the
  wall clock as its `_date`/`_time` pair, `start_date` as a YYYYMMDD int), then
  bulk-`executemany` (`fast_executemany`) every table's run-tagged rows in
  FK-topological order, one transaction (rollback + `PersistenceError` on
  failure). `insert_sql`/`project_rows` expand each datetime to its INT pair via
  `storage.to_storage`; `?` placeholders, bracket-quoted identifiers.
- **`run.py --verbose`** — resolves the writer `ConnConfig` from the config's
  optional `database` block (`--db-conn` overrides), calls `persist_run`, echoes
  the new `run_id`. Verbose **requires `--label`** + multi-line **notes via `vi`**
  (rejects empty). No `database` block → not persisted.

### The dashboard — `swmtplanner.dashboard` (top-level viewer)

A **planner-agnostic** viewer, *handed* a planner's manifest. It owns **all
GUI** — the generic raw view *and* the planner-specific "pretty" view. Layout:
generic `manifest` dataclasses + reader `config` at top; the `sqlload` read
layer; `app/` (GUI, later). Design: `swmtplanner/dashboard/DESIGN.md`.

- **`manifest.py`** — generic `TableSpec` / `Column` / `ForeignKey` dataclasses
  (shape only — the planner fills them in; `TableSpec` carries `disp_name` +
  `desc` for the GUI and the physical **`db_name`**, default = `name`; `Column`
  types now include **`date`** beside `datetime`) + the universal `RUN_ID`, the
  `order_columns` accessor (`order_by` if set, else `pk`), and `referencing_fks`
  (the reverse-FK map).
- **`storage.py`** — the **storage mapping** (pure): `physical_columns` (the
  `_date`/`_time` pair for a datetime, via the stem rule), `to_storage` /
  `from_storage` (cell tuples in, logical values out; second precision),
  `encode_datetime` / `decode_datetime` (the combined YYYYMMDDHHMMSS integer),
  `sort_expr` (the ORDER BY / compare expression), `quote` (`[ ]`). Both the
  writer and the read path go through it; nothing above SQL sees the encoding.
- **`config.py`** — `ConnConfig` / `DatabaseConfigError` /
  `resolve_conn_config(block, env, *, prefix)` over a **flat** connection block
  (`host`/`port`/`name`/`user`/`password` + optional `driver` [default `ODBC
  Driver 17 for SQL Server`], `encrypt` [`no`], `trust_server_certificate`
  [`yes`] — JSON booleans accepted; port default 1433). The planner's writer uses
  `SWMT_DB_*`; the reader's `read_reader_config` reads the JSON file named by
  **`SWMT_DASHBOARD_CONFIG`** and resolves with the distinct `SWMT_DASHBOARD_*`
  namespace (reader/writer creds never collide). **`connection_string(cfg)`** /
  **`connect(cfg, autocommit=)`** are the one pyodbc path both sides use (the
  `pyodbc` import is lazy). Read-only is enforced by the reader login's SQL
  Server permissions.
- **`sqlload/`** — the read/pagination **data layer** (done, tested):
  - `helpers.py` — `Filter` (`selection`/`exclusion`/`range`/`pattern`) +
    `FKLookup`, each compiling a column constraint to a T-SQL format string via
    `to_sql_str()` (lazy validation → `FilterError`). Bracket-quoted; `pattern`
    emits `LIKE … ESCAPE '\'`; `FKLookup.ref_table` is the referenced table's
    **physical** name; `_sql_literal` does **not** double backslashes (T-SQL).
  - `query.py` — `Query.build(cursor, run_id, spec, **constraints)` takes a
    `TableSpec`, runs only the count query, and assembles one bounded T-SQL
    SELECT: the **physical** columns of `[db_name]` (a datetime → its pair),
    run-scoped, filters/`ORDER BY`/`DISTINCT` via `storage.sort_expr` with
    temporal filter values pre-encoded, `OFFSET {offset} ROWS FETCH NEXT {limit}
    ROWS ONLY`. Loaded chunks are **recombined to logical rows**, so `Table`/
    `Row` are untouched. Exposes `nrows`, `unique(col)` (decoded; → `None` past
    `CHUNK_SIZE` distinct), `next_chunk`/`prev_chunk` (half-chunk stepping;
    `row_offset`).
  - `table.py` — `Table(spec, cursor, run_id)` owns the `Query`, serves
    `next_page`/`prev_page`/`reload_page` of `Row`s; `apply_filter_to` /
    `remove_filter` / `apply_fk_lookup` rebuild (reset to page 1 + clear
    selection); `unique(col)` passthrough to the current `Query`;
    `selected_keys` via `Row.select`/`deselect`; class-level `page_size` via
    `set_page_size` (must fit a half-chunk).
- **`app/` — the PyQt6 GUI (phases 1–4 done; pretty view pending).**
  `DashboardWindow` (`window.py`) is the shell: a sidebar (**Run selection** /
  **Raw view ▸ \<table\>** / **Pretty view**) beside a header + stacked content,
  zero layout margins so content fills the window. Modules:
  - `run_select.py` — `RunSelectionPage`: runs from the registry as rounded
    `RunButton` cards (Run N + created_at + start_date + total_score); clicking
    one sets `selected_run_id` and highlights it. Raw/Pretty show *"Please select
    a run…"* until then.
  - `pages.py` — `RawViewPage` (now the **FK-navigation controller**: a stack of
    `PagedGrid` frames; sidebar pick = fresh root, drill / "Go to…" push, **‹ Back**
    pops; emits `current_table_changed` → the shell header) and the
    `PrettyViewPage` placeholder.
  - `grid/` (table rendering) — `PageModel` + `PagedGrid` (paged `QTableView`,
    `m/d/yy h:mm` datetimes, alternating rows, a `FilterHeader` per column;
    a leading **checkbox column** for keyed tables wired to `Row.select`/`deselect`,
    **FK cells as blue links** emitting `fk_activated`).
  - `filters/` — `FilterHeader` (per-column funnel/✕ button, skips the checkbox
    column), `FilterPopup` (rounded off-white card; kind selector → membership /
    range / pattern bodies; Apply → `apply_filter_to`, ✕ → `remove_filter`).
  - `theme.py` — the soft off-white/grey, rounded, blue-hover stylesheet;
    `formatting.py` — shared `format_cell`; `knit_debug.py` — the `knit-debug`
    launcher (reader connection + the knit manifest).
  - **FK/PK navigation (phase 4, done):** clicking a non-null **FK cell** drills to
    the referenced table with a single-value selection `Filter` on its PK;
    checking **PK rows** + **"Go to…"** navigates to a referencing table via
    `apply_fk_lookup` (menu built from `manifest.referencing_fks`, the reverse-FK
    map). Each nav constraint shows as a clearable header ✕ on the relevant
    column. No new `sqlload` primitive (the once-floated `PKLookup` was dropped —
    a PK lookup is just a selection filter). **Pending:** the planner-specific
    **pretty view** (phase 5).

### Tests

- `tests/debuglog_tests.py` — white-box `DebugLog` coverage incl. the
  **composite-PK** section (multi-col `set_pk`, tuple `add_row`/`update_row`/
  `get_last_pk_val`, flat composite `get_df`, FK-onto-composite rejected). Spec:
  `DEBUGLOG_TEST_SPEC.md`.
- `tests/persistence_tests.py` (planner) — manifest↔DebugLog consistency +
  structure (incl. `run_configs`/`iteration_states`), persistence pure helpers
  (incl. composite-PK `project_rows`), the `plan`→`run_configs`/`iteration_states`
  population, the write-side translation (`insert_sql` brackets/qmarks/physical
  expansion, `project_rows` datetime splitting — pure), `persist_run` end-to-end
  (SQL Server-gated, currently skipping) + `run.py` wiring. Spec:
  `PERSISTENCE_TEST_SPEC.md`.
- `tests/dashboard_tests.py` (generic dashboard) — config resolution + reader
  config, `Filter`/`FKLookup` (pure), the `referencing_fks` reverse-FK map (pure),
  the **storage mapping** (§7) and **`Query.build`'s exact T-SQL + recombination
  against a fake cursor** (§2b) — both pure, `Query`/`Table`/`Row` incl.
  `Table.unique` (SQL Server-gated, currently skipping). The gated tests
  persist a **synthetic, controlled `DebugLog`** (`_dashboard_fixture_log`, built
  via `add_row`) — decoupled from the planner so row counts stay stable through
  planner tuning. Spec: `DASHBOARD_TEST_SPEC.md`.
- `tests/inf_plan_tests.py` — planner loop / coordination, incl. `eligible_orders`
  (see the precedence note below). Spec: `INF_PLAN_TEST_SPEC.md`.
- `tests/sqlserver_support.py` — shared SQL Server scaffolding (not collected):
  `SWMT_TEST_*` connection details, `_connect` (pyodbc via `config.connect`),
  and `_clean_slate` (empties the `knit_` tables children-first — T-SQL has no
  FK-checks toggle). Gated classes probe reachability and skip when unavailable.
- The **`app/` GUI is verified by running it** (`knit-debug`), not unit-tested —
  per convention; the `Table`/`Query`/`Row` stack beneath it is covered.

## Planner — `eligible_orders` precedence (one order per item)

`coordination.eligible_orders` now returns **at most one order per item**, by
precedence: (1) **urgent regular** — the earliest unmet order with `week_idx <=
state.reference_week_idx`; else (2) **safety** — when the pool is below target;
else (3) **future regular**. So an item gets a safety order only once its urgent
demand is met *and* it is below safety target; otherwise it gets a regular order.
This shrank the default planner run (fewer candidates / iterations), which is why
the dashboard read-layer tests moved to the synthetic fixture above. Detail:
`INF_PLAN_TEST_SPEC.md` §1.3.2.

## Knit-only branch — the planning tools (as of 2026-10-13)

Branch `knit-only` (worktree `~/git-repos/swmt-projs/knit-only`) carries the
knit planner as the plant now runs it. **Everything below is in the working
tree, uncommitted** (68 files, ~7,800 lines added); the user commits. Inputs
and run configs live in `~/git-repos/swmt-projs/knit-input-files/`
(`master.json` for `plan infinite`, `retime.json` for `plan retime`, the
exports as `machines.json` / `beam-sets.json` / `assigned-sets.json` /
`demand.json` / `black-list.json`, the variant map + masters); plans go to
`~/Desktop/Shawmut Projects/Scheduling/` (`knit_plan_<date>[_n].{xlsx,json}`,
`tape_outs_*.txt`, `retime_*.txt`, Gantt `.html` from
`scripts/make_gantt.py <plan.json> <out.html>`). The user edits inputs and
configs themselves; the daily machine status table is built by the Claude
skill `~/.claude/skills/reconcile-machine-status/` from the floor's exports.

Commands (`plan …`, `planners/cli.py`):
`infinite <config> -o <dir>` (the greedy planner), `retime <config> <prior
plan.json> <tickets.json> -o <dir> [--keep-sets]` (realign a plan to the
morning's status), `manual` (step-file replay), plus `machines` / `variants`
/ `styles` input builders. The usual morning: `plan retime` yesterday's plan,
then `plan infinite` with the retimed JSON as `prior_plan`.

Landed this session, each design → spec → tests (DESIGN.md sections named):

- **Sets described by evidence** (`schedule/DESIGN.md` "Beam-set
  inventory", "Foreign bars"): mounted / queued sets take the export's or
  the record's yarn, not the item's; a non-fitting mounted set is a
  *foreign bar* (no run-up, taped out at the first plan); a non-fitting
  queued set is *passed over* at the hang (`PassedOver`, with a `reason`).
- **Sets assigned after planning** ("Assigning sets after planning"):
  `schedule.assign_sets` hands stock to placeholder hangs in runout order
  and relabels the schedule (`Machine.rebind_sets`); knits carry their
  sets (`Knit.top_beam` / `btm_beam`, JSON and xlsx).
- **Retimer** (`planners/retime/DESIGN.md`): two passes (placeholders,
  then runout-order assignment), `--keep-sets`, and now **re-timing
  rounds** — replay with the assigned sets named at real pounds until a
  round assigns nothing (`MAX_ROUNDS` 6; sets refused at their hang are
  held back and reported); `HangRecord.rolls` = rolls doffed off each set.
- **Sticking to the prior plan** (`planners/infinite/DESIGN.md`): config
  `prior_plan` (a retimed JSON); the pre-pass `recommit_prior` keeps prior
  jobs inside `frozen_window` whose order (matched by item + due date) is
  still **urgent and open** (week ≤ `reference_week_idx`); `prior_jobs`
  sheet; JSON jobs carry `due_date` / `prior_job`.
- **EOQ batching** for unique-setup low-volume items (`eoq_threshold_rolls`
  / `eoq_batch_rolls`).
- **Change cap + filling the wait** ("Changeover capacity", "Filling a
  slot wait"): a third rationed kind `change` (one unit per machine
  changed, whole-day period; master.json has 6/day); a move that must wait
  for a slot knits its current item meanwhile as far as demand allows
  (`Fill`, `Job.fill`).
- **`init_roll_lbs` is the lbs WOUND on the roll in progress** (2026-10-27,
  `schedule/DESIGN.md` File I/O): the loader turns it into the model's
  `init_roll_lbs_remaining` (`tgt_wt − wound`, floored at 0; `_roll_remaining`),
  and `plan machines` now writes the wound lbs (converting the old
  racks-left form). Before, the field was read as lbs left.
- **A mounted set wins over its assignment** (2026-10-23, `schedule/DESIGN.md`
  File I/O): assigned-sets records naming a set the machines file has
  mounted are dropped at load (`_split_mounted`; `mounted_assignments`
  lists them, `run.mounted_assignment_lines` echoes them) — a queued
  record wherever it was assigned, and a `hung` record for the set the
  file has on that same bar; a `hung` record naming another set still
  replaces the file's.
- **Machine `status`** (2026-10-22, `schedule/DESIGN.md` "Standing machines"
  and File I/O; planner design "Restart cost"): the machines file's
  `status` is `running` (default) / `standing` / `overhaul`. Overhaul
  machines are left out of the run entirely (`overhaul_machines`,
  `Inputs.overhaul`, echoed; the retimer reports their prior rolls).
  Standing machines (`Machine.standing`: no run-up, no fill, idle to the
  change date) join the candidate pool with a **`restart`** cost weight on
  their first move — a NEW REQUIRED WEIGHT: the user must add `restart`
  to the inline weights in master.json / retime.json (6400 suggested).
  Echo `run.standing_machines`; manual `pending()` has `standing`.
- **Retimer look-ahead** (2026-10-20, `planners/retime/DESIGN.md` "Where
  each machine is"): a ticket or status on the item of *any* later job
  is an early change — every job before it is dropped and recorded —
  not only the very next job's; only an item the plan never has again
  on the machine is a wrong style. Cause: O3 switched to 8154 early and
  the plan's 4583 run was two jobs (run-up + planned).
- **Queued sets are skipped, not dropped** (2026-10-20, `schedule/DESIGN.md`
  "Assigned sets and bar queues"): a plant-assigned set that does not fit
  a hang stays in the bar's queue for a later hang it fits (the hang
  takes the first usable queued set — `_PlanCtx.pick` / `pass_over`,
  `Hanging.skipped`, `PassedOver.dropped`); only blacklisted or too-large
  sets are dropped. Cause: O3 staged for 8154 ran 4583 first and lost its
  sets. `PlanReport.queues_left` / `item_at_end` feed the sheet below.
- **`unassign` sheet** in the plan workbook (`report.unassign_dataframe`,
  2026-10-19; `planners/infinite/DESIGN.md` Reporting): the assigned
  sets the plan passed over at a hang (`queued`) or took off a bar
  unthreaded (`hung`), with the bar's requirement and the reason — for
  the person entering the schedule to unassign. Always written; both
  `plan infinite` and `plan retime` produce it.
- **Blacklisted merges, vendors and sets** (`schedule/DESIGN.md`
  "Blacklisted merges"): config `blacklist` — a JSON list of merge codes,
  or an object `{"merges", "vendors", "sets"}` (`products.Blacklist`,
  2026-10-19) naming whole vendors by the export's name and individual
  set numbers too; a flagged set fits nothing and is never stock —
  withheld from picks, passed over in a queue, taped out off a bar.

- **Assigned-set `status`** (`schedule/DESIGN.md` "Hung bars" and the
  `status` paragraph under File I/O): `"inventory"` (default) / `"staged"`
  queue the set with a `location`; `"hung"` makes it the bar's unthreaded
  initial set (`init_*_threaded`), which the first plan threads without a
  hang, or takes off with the new zero-duration `Unhang` activity (set
  back to stock) when it does not fit. The user's `assigned-sets.json`
  already carries the field.
- **Large beams** (`schedule/DESIGN.md` "Large beams"): export records
  carry `size` (`"<diam> x <width>"` in inches); a set of 40 in or more
  (`LARGE_BEAM_DIAMETER`) fits only new machines — `Machine.accepts`
  gates the stock pick, manual assignments, `assign_sets`, the queue
  (passed over, reason `too large for this machine`), the retimer's
  keep-sets and a mounted set (foreign bar, taken off at the first plan).
  The stock pick order is now `stock_order`: large sets first, then
  oldest received, then set number — the merge/vendor continuity tiers
  are gone.
- **An item the machine cannot run** (`schedule/DESIGN.md` "An item the
  machine cannot run"): a machine set up for a style whose machine list
  leaves it out (`Machine.can_run_current_item` False) knits nothing of
  it — treated like foreign bars for the run-up (roll zeroed, no run-up,
  no fill, runout immediate) while its sets keep their real lbs for the
  preamble; `run_until` idles it to the change date; its cheap set is
  empty, so moving it costs no recovery and it covers for nobody; the
  load echoes it (`run.cannot_run_on_machines`). Note the style file
  still lists Q6 for AU7992T2A — the machine master qualifies it — so
  the rule fires only once the user drops Q6 from that style.
- `plan styles` reads the reshaped `knit-machine-master.json`: a
  per-machine `width` (a machine must be at least as wide as the style)
  and a single `rpm` (no `wide` attribute, no `rpms.any/wide`).
- Variant rows are split into sets by **threading**, not by shared merge
  (`products/variants.py` `_sets`): the two bars threaded `1 IN, 1 OUT` /
  `1 OUT, 1 IN` are the split-lease set (same planner yarn required,
  merge codes may differ); every other bar is its own set, so two solid
  bars of one merge are two sets (this is what defines AU1148G36, skipped
  before). A row with more than two distinct merges is still excluded.
  Not regenerated in the input folder — the user runs `plan variants` /
  `plan styles`; note a regenerated styles file re-adds the nine old
  machines the user removed by hand from AU7992T2A.

**Parked (user's call, not designed):** the split-lease short-doff rule
(a split-lease set running out mid-roll forces a short doff; counting is by
400-lb ports: ≥ half a standard roll counts as half, styles ≤ 400 lbs count
no half rolls); the retimer's `locate` treating a prior plan whose first
job on a machine is an immediate changeover as a *wrong style* (seen on
Q6 in the 10-13 plan — the machine is left at status, its jobs dropped).

Spec files for all of this: `tests/spec-files/SCHEDULE_TEST_SPEC.md` (Phases
5–7), `INF_PLAN_TEST_SPEC.md` (1.3.4–1.3.5, 1.5, 1.7–1.9), `RETIME_TEST_SPEC.md`,
`RUN_TEST_SPEC.md` §5.

## Next concrete action

On `knit-only`: commit the branch (the user commits); the next feature is the
user's call — the parked items above are the open candidates. The dashboard / SQL Server
cut-over notes below predate this branch's work and still apply to the
debug-log viewer, which this branch has not touched:

Recently landed (working tree, pure suite green): `DebugLog` **composite PKs**,
the two new tables (`run_configs` / `iteration_states`) end-to-end, the
`eligible_orders` precedence rework + its tests, the **decoupled dashboard
fixture**, the `collapsed_sched` report sheet, the new greige-styles JSON loader,
`inv_cost_detail` restricted to affected items, and the **SQL Server cut-over**
(see the store cut-over note above; steps: manifest `db_name`/`date` →
`storage.py` → `config.py` → `sqlload` → `persistence.py` → app → test
scaffolding, all done). `pymysql` is gone from `requirements.txt`.

**Immediate next action — smoke the cut-over against the real database** (no
test DB exists, so the gated suites can't do it): a `--verbose` planner run with
the `database` block pointing at the SQL Server store should persist a run
(`knit_runs` gets `created_at_date`/`_time` + `start_date` ints; every `knit_`
table fills; `due_date`/`due_time` etc. land as INT pairs), and `knit-debug`
should list the run with a correctly formatted `created_at`/`start_date`, page
every table, show datetimes as `m/d/yy h:mm`, range-filter a datetime column, and
drill an FK (the sub-query names the `knit_` table). Anything that fails there is
a translation gap the pure tests didn't model — fix at the storage/`Query` seam.
Also worth a manual pass while there: GUI phase 4 (drill an FK cell, check PK rows
+ "Go to…", **‹ Back**, clear a nav filter via the header ✕). When a SQL Server
test database is provisioned, point `SWMT_TEST_*` at it and the 4 gated classes
run again (their raw-SQL oracles are already T-SQL / physical-name aware).

Next: **phase 5 — the planner-specific pretty view**, DESIGN-first per the usual
workflow. The elaborate, non-technical view built from custom `QtWidget`
subclasses; its layout is to be specified in the app DESIGN.md when the phase
starts. The GUI is verified by running `knit-debug`, not unit tests.
