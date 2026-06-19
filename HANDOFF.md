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
  MySQL writer (`persist_run`).
- `src/swmtplanner/debuglog/` — the planner-agnostic `DebugLog` audit-log
  container (top-level, used by the planner under `--verbose`).
- `src/swmtplanner/dashboard/` — the **planner-agnostic debug-log viewer**
  (top-level): generic `manifest` dataclasses + reader `config`, the `sqlload`
  read/pagination layer, and the PyQt6 `app/` (GUI, later). Owns all GUI.
- `tests/` — `*_tests.py` modules (+ the shared `mysql_support.py` helper);
  coverage specs in `tests/spec-files/` (`SCHEDULE_TEST_SPEC.md`,
  `DEMAND_TEST_SPEC.md`, `COORD_TEST_SPEC.md`, `INF_PLAN_TEST_SPEC.md`,
  `DEBUGLOG_TEST_SPEC.md`, `PERSISTENCE_TEST_SPEC.md`, `DASHBOARD_TEST_SPEC.md`,
  `RUN_TEST_SPEC.md`).

Each major submodule has a `DESIGN.md` that is the source of truth for
structure before implementation. **Stub (`.pyi`) files are a standing
convention**: every module in the dashboard / persistence subpackages has one,
created with the code and kept in sync.

**Running tests / Python:** the project virtualenv is `.dev-venv` (has
pandas/numpy + pymysql; no pytest). Run with:
`PYTHONPATH=src:. .dev-venv/bin/python -m unittest tests.<module>`
(e.g. `tests.machine_tests`).

> **Suite state:** **462 tests, all passing** (`python -m unittest discover -s
> tests -p '*_tests.py'`; the MySQL-gated tests — `persist_run` end-to-end plus
> the whole `sqlload` read layer — run against a local `swmtinftest`, else skip).
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

## Debug log + investigation — ✅ committed; GUI ⏸ next

A codebase-wide **debug mode**: the planner records *why* each move was chosen
into a `DebugLog`, persists a run to a local **MySQL** store, and investigates it
through a planner-agnostic **PyQt6 dashboard**. The debug log, the MySQL writer,
and the dashboard's `sqlload` read layer are committed; the GUI is the remaining
piece.

### The debug log — `swmtplanner.debuglog` (done)

`DebugLog` is a generic, config-driven container of named tables (declare tables
+ `set_pk` / `set_fk`; populate with `add_row` / `update_row`; read with
`get_df` / `get_nrows` / the `tables` / `schema` accessors). It is
planner-agnostic, hard-coding no schema of its own.

The planner threads it as an optional `debuglog` kwarg through the loop +
costing and **populates eight tables live as it runs** — `iteration_log`,
`cost_summary`, `inv_cost_detail`, `sched_cost_detail`, `priority_detail`,
`production` — plus a post-loop copy of `demand` / `unmet_demand`. Supporting
provenance feeds these: `Job.tgt_order`, per-roll `Roll.knits`, and the
`SafetyAwareView` roll→order fill-links. This **replaced** an earlier
after-the-fact reconstruction (the old `iterlog` / `cost_breakdown` machinery),
which has been removed. Design: `swmtplanner/debuglog/DESIGN.md`.

### Planner-owned: debug schema + MySQL writer (done)

The database `swmtinfinite` (test copy `swmtinftest`) is **dedicated to the
knitting planner**, so its base tables share the `DebugLog` table names (no
translation); it also holds a `runs` registry and two read-only views
(`committed_sched` / `committed_prod`, the committed-move slices). The schema is
**user-provisioned** — the tool only INSERTs. The planner owns its concrete
schema + the write path:

- **`planners/infinite/manifest.py`** — the concrete schema: per-table column
  types, PKs, the FK graph (incl. `production.knit_id →
  sched_cost_detail.activity_id`, a link beyond `DebugLog.schema`), the
  FK-topological insert order, and per-table `order_by` for key-less paging.
  Built from the generic dataclasses in `swmtplanner.dashboard.manifest`. A test
  guards it against drift from the live `DebugLog`. The MySQL DDL is documented
  in `planners/infinite/DESIGN.md` (Debug-log persistence).
- **`planners/infinite/sqldump/persistence.py`** — `persist_run(debuglog, conn,
  …)`: connect as the writer, INSERT a `runs` row → `run_id`, then
  bulk-`executemany` every table's run-tagged rows in FK-topological order, one
  transaction (rollback + `PersistenceError` on failure). Driver: **PyMySQL**.
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
  (shape only — the planner fills them in) + the universal `RUN_ID` and the
  `order_columns` accessor.
- **`config.py`** — `ConnConfig` / `DatabaseConfigError` /
  `resolve_conn_config(block, env, *, prefix)` over a **flat** connection block
  (`host`/`port`/`name`/`user`/`password`). The planner's writer uses `SWMT_DB_*`;
  the reader's `read_reader_config` reads the JSON file named by
  **`SWMT_DASHBOARD_CONFIG`** and resolves with the distinct `SWMT_DASHBOARD_*`
  namespace (reader/writer creds never collide). Read-only is enforced at the
  MySQL grant level on the configured reader user.
- **`sqlload/`** — the read/pagination **data layer** (done, tested):
  - `helpers.py` — `Filter` (`selection`/`exclusion`/`range`/`pattern`) +
    `FKLookup`, each compiling a column constraint to a SQL format string via
    `to_sql_str()` (lazy validation → `FilterError`).
  - `query.py` — `Query.build(cursor, run_id, spec, **constraints)` takes a
    `TableSpec` (so it's schema-driven), runs count + per-column distinct
    queries, assembles one bounded SELECT (table-qualified, run-scoped,
    `ORDER BY order_columns`, `{limit}`/`{offset}`). Exposes `nrows`,
    `unique(col)` (→ `None` past `CHUNK_SIZE` distinct), `next_chunk`/`prev_chunk`
    (holds a full chunk, advances by half-chunks; `row_offset`).
  - `table.py` — `Table(spec, cursor, run_id)` owns the `Query`, serves
    `next_page`/`prev_page`/`reload_page` of `Row`s; `apply_filter_to` /
    `remove_filter` / `apply_fk_lookup` rebuild (reset to page 1 + clear
    selection); `unique(col)` passthrough to the current `Query`;
    `selected_keys` via `Row.select`/`deselect`; class-level `page_size` via
    `set_page_size` (must fit a half-chunk).
- **`app/` — the PyQt6 GUI (phases 1–3 done; FK/PK nav + pretty view pending).**
  `DashboardWindow` (`window.py`) is the shell: a sidebar (**Run selection** /
  **Raw view ▸ \<table\>** / **Pretty view**) beside a header + stacked content,
  zero layout margins so content fills the window. Modules:
  - `run_select.py` — `RunSelectionPage`: runs from the registry as rounded
    `RunButton` cards (Run N + created_at + start_date + total_score); clicking
    one sets `selected_run_id` and highlights it. Raw/Pretty show *"Please select
    a run…"* until then.
  - `pages.py` — `RawViewPage` (caches one grid per table for the run, with a
    "Loading…" placeholder on first load) and the `PrettyViewPage` placeholder.
  - `grid/` (table rendering) — `PageModel` + `PagedGrid` (paged `QTableView`,
    `m/d/yy h:mm` datetimes, alternating rows, a `FilterHeader` per column).
  - `filters/` — `FilterHeader` (per-column funnel/✕ button), `FilterPopup`
    (rounded off-white card; kind selector → membership / range / pattern
    bodies; Apply → `apply_filter_to`, ✕ → `remove_filter`).
  - `theme.py` — the soft off-white/grey, rounded, blue-hover stylesheet;
    `formatting.py` — shared `format_cell`; `knit_debug.py` — the `knit-debug`
    launcher (reader connection + the knit manifest).
  - **Pending:** FK/PK cell-click navigation + a back button (phase 4), then the
    planner-specific **pretty view** (phase 5).

### Tests

- `tests/persistence_tests.py` (planner) — manifest↔DebugLog consistency +
  structure, persistence pure helpers, `persist_run` end-to-end (MySQL-gated) +
  `run.py` wiring. Spec: `PERSISTENCE_TEST_SPEC.md`.
- `tests/dashboard_tests.py` (generic dashboard) — config resolution + reader
  config, `Filter`/`FKLookup` (pure), `Query`/`Table`/`Row` incl. `Table.unique`
  (MySQL-gated, using the knit planner's persisted run as the fixture). Spec:
  `DASHBOARD_TEST_SPEC.md`.
- `tests/mysql_support.py` — shared MySQL connection scaffolding (not collected).
- The **`app/` GUI is verified by running it** (`knit-debug`), not unit-tested —
  per convention; the `Table`/`Query`/`Row` stack beneath it is covered.

## Next concrete action

**GUI phase 4 — FK / PK navigation + back button**, DESIGN-first per
`swmtplanner/dashboard/app/DESIGN.md` (phase 4 sketch). Two parts:

1. **Data-model additions to `sqlload` first** — alongside the existing
   `FKLookup` / `Table.apply_fk_lookup`, add a **`PKLookup`** constraint and
   **`Table.apply_pk_lookup`**:
   - `FKLookup` (have) — *from* a referenced table's selected keys, find the rows
     of the table that reference them (drill via the FK column, an `INNER JOIN`
     sub-query).
   - `PKLookup` (new) — *to* a referenced table: given FK cell value(s), show the
     referenced row(s) by their PK (a `WHERE pk IN (…)` / equivalent). This is the
     forward direction of a foreign-key click; `apply_pk_lookup(pkcol, values)`
     mirrors `apply_fk_lookup`. Add it to `helpers.py` (a `to_sql_str`) +
     `Table`, with coverage in `DASHBOARD_TEST_SPEC.md` §5 and
     `tests/dashboard_tests.py` (pure `to_sql_str` + MySQL-gated `Table` path).
   - (Exact semantics — incl. whether a PK cell's "show only this row" reuses a
     selection `Filter` or `PKLookup` — to be pinned in the design first.)
2. **Then the GUI** — clicking an FK cell drills to the referenced table via the
   new lookup; a **navigation history** backs an in-view **back button** (extends
   the phase-2 per-table caching into a view stack). Plus the committed-only
   toggle.

After that, **phase 5 — the planner-specific pretty view** (custom `QtWidget`
subclasses; layout to be specified in the app DESIGN.md when it starts). The GUI
is verified by running `knit-debug`, not unit tests.
