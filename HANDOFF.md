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
  `run.py`), plus the **`dashboard/`** subpackage (debug-log persistence +
  investigation app).
- `src/swmtplanner/debuglog/` — the planner-agnostic `DebugLog` audit-log
  container (top-level, used by the planner under `--verbose`).
- `tests/` — `*_tests.py` modules; coverage specs in `tests/spec-files/`
  (`SCHEDULE_TEST_SPEC.md`, `DEMAND_TEST_SPEC.md`, `COORD_TEST_SPEC.md`,
  `INF_PLAN_TEST_SPEC.md`, `DEBUGLOG_TEST_SPEC.md`, `DASHBOARD_TEST_SPEC.md`,
  `RUN_TEST_SPEC.md`).

Each major submodule has a `DESIGN.md` that is the source of truth for
structure before implementation. **Stub (`.pyi`) files are a standing
convention**: every dashboard module has one, created with the code and kept in
sync.

**Running tests / Python:** the project virtualenv is `.dev-venv` (has
pandas/numpy + pymysql; no pytest). Run with:
`PYTHONPATH=src:. .dev-venv/bin/python -m unittest tests.<module>`
(e.g. `tests.machine_tests`).

> **Suite state:** **408 tests, all passing** (`python -m unittest discover -s
> tests -p '*_tests.py'`; the 6 MySQL-gated dashboard tests run against a local
> `swmtinftest`, else skip). The planner prints `Total moves committed: N` (and
> per-table `Dumping …` lines during a verbose persist) to stdout — intentional
> source-side prints, harmless to the suite.

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

## Debug log + investigation — 🔨 in progress (UNCOMMITTED)

A codebase-wide **debug mode**: the planner records *why* each move was chosen
into a `DebugLog`, persists a run to a local **MySQL** store, and (read side,
pending) investigates it through a **PyQt6** app. All of the work in this
section is uncommitted.

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

### Persistence to MySQL — `planners/infinite/dashboard/` (write half done)

The database `swmtinfinite` (test copy `swmtinftest`) is **dedicated to the
knitting planner**, so its base tables share the `DebugLog` table names (no
translation); it also holds a `runs` registry and two read-only views
(`committed_sched` / `committed_prod`, the committed-move slices). The schema is
**user-provisioned** — the tool only INSERTs.

The `dashboard/` package (shared `manifest` + `config` at the top; the write
path in `sqldump/`; the read path in `sqlload/`; the GUI in `app/` later):

- **`manifest.py`** — the static source of truth: per-table column types, PKs,
  the FK graph (incl. `production.knit_id → sched_cost_detail.activity_id`, a
  link beyond `DebugLog.schema`), and the FK-topological insert order. A test
  guards it against drift from the live `DebugLog`.
- **`config.py`** — `resolve_conn_config(block, role, env)`: reads the
  `database` block (shared `host`/`port`/`name` + a `writer` and a `reader`
  credential sub-block) with `SWMT_DB_*` env fallback. **Two MySQL roles**
  enforce read-only at the grant level (writer persists; reader, used by the
  app, cannot mutate data).
- **`sqldump/persistence.py`** — `persist_run(...)`: connect as the writer,
  INSERT a `runs` row → `run_id`, then bulk-`executemany` every table's
  run-tagged rows in FK-topological order, in one transaction (rollback +
  `PersistenceError` on any failure). Driver: **PyMySQL**.
- **`run.py --verbose`** — resolves the writer `ConnConfig` from the config's
  optional `database` block (`--db-conn` overrides it), then calls `persist_run`
  and echoes the new `run_id`. Verbose mode **requires `--label`** and collects
  multi-line **notes interactively via `vi`** (rejecting empty notes). Absent a
  `database` block, the run isn't persisted.

Tested by `tests/dashboard_tests.py` (manifest↔DebugLog consistency, config
resolution, persistence pure helpers, and MySQL-gated end-to-end incl. the
`run.py` wiring) and `tests/run_tests.py` (the CLI helpers). Design:
`planners/infinite/dashboard/DESIGN.md`.

### Read side — ⏸ not yet built

- **`sqlload/`** — the read/pagination data layer (separate from the GUI).
  The user has specific ideas for how loading should work; **design pending**.
- **`knit-debug` PyQt6 app** (`dashboard/app/`) — Home selects a run from
  `runs`; then run-scoped, uniformly **paged** grids (LIMIT/OFFSET + COUNT —
  FK/PK lookups paged too), FK navigation from the manifest's graph, per-column
  SQL `WHERE` filters, and a committed-only toggle (via the DB views). The app
  ships the manifest statically and connects as the reader.

## Next concrete action

1. (Optional) **commit** the schedule-layer work's successors and the whole
   debug-log/dashboard arc above — it's all uncommitted.
2. **Design `sqlload`** (read/pagination layer) — the user drives this.
3. Then build `sqlload` + the `knit-debug` PyQt6 app per the phases in
   `planners/infinite/dashboard/DESIGN.md`, DESIGN-first.
