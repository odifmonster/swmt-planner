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
  `Job`/`Roll` records). The activity set is now the Step-3 set (see below).
- `src/swmtplanner/demand/` — per-item demand/fulfillment views
  (`RlsItem`, raw + safety-aware views). Untouched by Steps 2–3.
- `src/swmtplanner/planners/infinite/` — the greedy planner that
  composes the two; CLI + dashboard generator live here (`costing/`,
  `iterlog.py`, `report.py`).
- `tests/` — `*_tests.py` modules; coverage specs in
  `tests/spec-files/` (`SCHEDULE_TEST_SPEC.md`, `DEMAND_TEST_SPEC.md`,
  `COORD_TEST_SPEC.md`, `INF_PLAN_TEST_SPEC.md`).

Each major submodule has a `DESIGN.md` that is the source of truth for
structure before implementation.

**Running tests / Python:** the project virtualenv is `.dev-venv` (has
pandas/numpy; no pytest). Run with:
`PYTHONPATH=src:. .dev-venv/bin/python -m unittest tests.<module>`
(e.g. `tests.machine_tests`).

> **Suite state:** **323 tests, all passing** (`python -m unittest discover
> -s tests -p '*_tests.py'`). Step 3 is fully landed and committed. **Step 4
> sub-step 1 (Job-related links + the `demand`/`xref` Excel tabs) is fully
> landed across design, `src/` code, coverage specs, and tests on all three
> layers — but is NOT yet committed** (sizable uncommitted diff in `src/` and
> `tests/`). The planner still prints `Total moves committed: N` debug lines
> to stdout during the loop tests; that's an intentional source-side print the
> user wants kept for now (harmless to the suite).

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

## The refactor: 4-step rework of the schedule layer

| Step | Scope | State |
|---|---|---|
| **1** | Separate production from schedule activities (`Job`/`Roll`, `ProductionPlan`) | ✅ complete + committed |
| **2** | Runout logic (`BEAM_FLOOR_LBS`, mid-roll beam loads, max-waste, yarn `Waste`) | ✅ complete + committed |
| **3** | Add `Doff`, split `BeamLoad`→`Hanging`/`Threading`, split changeover | ✅ complete + committed (design, `src/` code, tests + specs) |
| **4** | Codebase-wide **debug mode** (`VerboseLog` threaded through; `Job`↔order/`Knit` links; itemized lateness/drainage/carrying cost events; HTML dashboard) | 🔨 in progress — sub-step 1 complete (uncommitted); sub-steps 2–3 pending |

A cross-cutting **`Status` accessor refactor** was also done during Step 3
(see below) — it touched the same files and is committed alongside the
Step-3 code.

---

### Steps 1 & 2 — ✅ complete (committed, were fully tested)

Step 1 split the activity schedule (`Machine.activities`) from the
production schedule (`Machine.jobs` — `Job(item, rolls)` records);
`plan_production` returns a `ProductionPlan(activities, jobs)`;
`next_job_end`→`schedule_tail`.

Step 2 added the runout model: `BEAM_FLOOR_LBS = 5` (usable =
`bar_lbs - floor`), mid-roll beam swaps (rolls straddle), `MAX_BEAM_WASTE_LBS
= 100` (near-empty bars swapped before a roll), and the half-roll rule
removed. `Waste` became *unknit discarded yarn* (zero duration, empties a
bar), charged per-lb via a new `waste_lbs` cost weight. A later refinement:
`Waste` and `TapeOut` store the **`BeamSet`** (yarn SKU) being
discarded/removed, not the `Greige`.

### Step 3 — ✅ complete (design, code, tests + specs all committed)

**Design** (both `schedule/DESIGN.md` and `planners/infinite/DESIGN.md`),
**all `src/` code**, and the **tests + coverage specs** are implemented and
committed; the full suite is green. What was built:

**New activity set** (`schedule/activity/activity.py`), `BeamLoad` removed:
- **`Doff`** — fieldless (like `Idle`); one per completed roll. A roll's
  `completion_time` is its `Doff.end` (the roll is "ready" when off the
  machine).
- **`Hanging(bars, top_beam, top_lbs, btm_beam, btm_lbs)`** + **`Threading(bars)`**
  replace `BeamLoad`. **`Hanging` loads the physical set** (sets each bar's
  beam + lbs, leaves it un-threaded); **`Threading` flips `threaded`→True**
  and nothing else.
- **`StyleChange` / `RunnerChange` / `PatternChange`** (each just
  `from_item`/`to_item`; the `is_family_change` flag is gone). Selection:
  new machine → `StyleChange`; legacy same pattern family → `RunnerChange`;
  legacy cross-family → `PatternChange`.
- Duration constants are now **floats (work-hours)**, passed straight to
  `WorkCal.offset_work_hours`: `TAPE_OUT_SINGLE=2`/`BOTH=3`,
  `HANGING_SINGLE=1`/`BOTH=1.5`, `THREADING_SINGLE=2`/`BOTH=3.5`,
  `DOFF=20/60`, `STYLE_CHANGE=5/60`, `RUNNER_CHANGE=45/60`,
  `PATTERN_CHANGE=1.5`. `BEAM_FLOOR_LBS`/`MAX_BEAM_WASTE_LBS` also moved here
  (so `status.py` can share them without a circular import).

**`Status` accessor refactor** (`schedule/machine/status.py`): per-bar state
is private (`_bars: dict[str, _BarState]`); the **only** read API is
`status.beam(bar)` / `lbs_remaining(bar)` / `threaded(bar)` (`bar` is
`'top'`/`'btm'`) — the old `top_*`/`btm_*` fields are gone. Construct via the
**`Status.create(...)`** factory (per-bar primitives). `Greige`/activities
were intentionally **left as plain fields** (only `Status` got accessors).

**Beam-swap sequencing guard rails** (`status.apply_activity`): a swap is
**remove → hang → thread**. Per bar, `removed` = `beam(bar) is None or
lbs_remaining(bar) <= BEAM_FLOOR_LBS`; `hung` = `not removed and not
threaded`. `Hanging` requires the bar **removed** (else raises) and sets
`threaded=False`; `Threading` requires the bar **hung** (else raises) and
sets `threaded=True`; `TapeOut`/`Waste` remove (beam→None, lbs→0,
threaded→False).

**`machine.py` emission**: run-up emits a `Knit`+`Doff` per whole roll;
preamble does tape/waste then re-thread (`Hanging`+`Threading`, `'both'`
batched) then the changeover; production loop emits `Knit`+`Doff` per roll
with `resolve()` re-threading on runout (`'both'` co-swap). Helpers:
`_emit_doff`/`_emit_hanging`/`_emit_threading`/`_emit_rethread`/`_emit_changeover`
(removed `_emit_beam_load`/`_emit_rolls`/`_emit_roll`/`_emit_style_change`).
**`next_runout` folds in per-roll doff time** (`per_roll = tgt_wt/rate +
DOFF_DURATION`) so it equals the run-up's last `Doff.end`. The constructor
**no longer takes `simple_change_duration`/`family_change_duration`** (and
`io.py` no longer reads `style_change_time`/`family_change_time`).

**Costing** (`costing.py`, `iterlog.py`, `report.py`): the `family_change`
weight split into **`style_change` / `runner_change` / `pattern_change`**
(CostBreakdown/CostDetailRecord/`cost_detail.tsv` now **fourteen** weighted
components). `Knit`/`Doff`/`Hanging`/`Threading` are **unweighted**.
`_activity_desc`: `Hanging` shows the beam SKU + lbs per affected bar (e.g.
`"top 40D BLACK 1000X4 (2800 lbs), btm 60D WHITE 1000X4 (1800 lbs)"`),
`Threading` shows the bar(s), `Doff` is blank.

**Post-Step-3 fixes (committed, suite still green at 316):**
- The float tolerance that `machine.py` uses in `plan_production` is now also
  applied in `status.py`'s `_removed` predicate — a bar the planner treated as
  exhausted (sitting a hair above the floor by float drift) no longer raises
  on the paired `Hanging`'s remove→hang guard.
- Activity and `Job` string ids widened from **5-digit** to **8-digit**
  zero-padded counters (e.g. `KNIT00001` → `KNIT00000001`).

### Step 4 — 🔨 in progress (sub-step 1 complete, uncommitted)

Step 4 has been **re-scoped** into a far-reaching refactor that gives the
whole codebase a custom **"debug mode."** Instead of reconstructing the
verbose audit after the fact in `iterlog.py`/`report.py`, every relevant
method gains an **optional `VerboseLog` keyword argument** and writes detail
records straight into the log as it runs (a no-op when the log is absent).
The payoff is a dashboard that makes it obvious *why* an order was scheduled
and how each cost was incurred.

**Key new concepts:**

- **`VerboseLog` threaded through the code.** An optional kwarg on the
  relevant methods (planner loop, costing, demand views, schedule emission,
  …); when present, the method appends its own detail records directly. When
  absent, behavior is unchanged and nothing is logged.
- **Full `Job` provenance.** At creation a `Job` carries (1) the order it
  **originally targeted** and (2) its **component `Knit` objects** — so it
  traces back to the knits that produced it. The **highest-priority order it
  actually fills** can't be known when the `Job` is created, so it is **not**
  stored on the `Job`. The **`SafetyAwareView`** is the natural home for the
  job→demand fill-link — it already tracks both the jobs and the
  orders/demand — resolving it by priority.
- **Itemized cost events.** The inventory- and priority-side cost breakdowns
  stop being opaque scalars: they expose the actual **days/lbs late**, backed
  by a **complete table of cost-carrying events** for `lateness`, `drainage`,
  and `carrying`.
- **HTML dashboard, two modes.** A generator renders the logged detail into
  an HTML dashboard shipped with the verbose log:
  - a **raw / debug mode** — direct access to the source-data tables with the
    foreign/primary-key links surfaced for inspection;
  - a **user-friendly mode** — starts from the schedule by machine and drills
    down (machine → its jobs/activities → the order each job fills → the cost
    breakdown) through nicely-formatted views.

**Sub-steps (do in order, DESIGN/spec-first each):**

1. **Job-related links. ✅ complete (uncommitted), 323 green** — including the
   added Excel-output scope. What shipped (the design evolved from the original
   sketch):
   - **schedule** — `Job.tgt_order: str | None` (the order the caller
     *targeted*, passed into `plan_production`; stamped on the new-item `Job`
     only, run-up `Job` always `None`). Component `Knit`s live on **`Roll`**,
     not `Job` (`Roll.knits` — collected per-roll at each `Doff`; a straddling
     roll holds its two `Knit`s; a `Job`'s knits are the union of its rolls').
     Added a guard: `plan_production` raises `ValueError` for `'next_runout'`
     mode when `item == current_item` (no real changeover).
   - **demand** — new very-basic **`Safety`** order class attached to a
     `SafetyAwareView` (`id = S@{item}`, `remaining_lbs` reads the pool
     shortfall live). `SafetyAwareView.recompute` now also builds
     **`roll_order_links`** (read-only `tuple[tuple[Roll, str], ...]`): each
     filled roll → the **earliest** order/safety it fills (first bucket
     destination); `on_hand`/excess produce no link. Distribution math
     unchanged (the chunk-crossing logic is harmless whole-roll leftover).
   - **planner** — `RegularOrder` / `SafetyOrder` carry `order_id` (captured
     straight off the demand order / `Safety`, never rebuilt);
     `enumerate_candidates` threads it into `plan_production` as `tgt_order`
     and **skips** `next_runout` pairings for the machine's current item (so
     the new guard never fires at runtime).
   - **Excel output (added scope — ✅ done).** `write_plan_report_xlsx` in
     `planners/infinite/report.py` now writes **six** sheets (`demand`,
     `schedule`, `production`, `xref`, `unmet_demand`, `late_orders`):
     - **`demand`** — original input demand, one row per order (**regular and
       safety**): `order_id`, `item`, `due_date` (blank for safety), `demand`
       (regular = weekly `qty_lbs`; safety = `safety_target`), `covered_on_hand`,
       `remaining`. On-hand coverage comes from **`RlsItem.on_hand_coverage`**
       (a `dict[str,float]` keyed by order id, captured at construction from
       the jobs=`[]` allocation).
     - **`production`** gained a `tgt_order` column (`Job.tgt_order`, blank for
       run-up jobs).
     - **`xref`** — flat, one row per `Knit`: `item`, `job_id`, `roll_idx`,
       `roll_completion`, `knit_id`, `knit_lbs`, `order_id` (the **resolved**
       fill from `roll_order_links`, distinct from the job's aimed-at
       `tgt_order`). Joins `Roll.knits` / `roll_order_links` / `Job.rolls`.
     - **`PlanReport`** gained `rls_items: dict[str, RlsItem]` to feed both new
       sheets. Output rendering is intentionally **not** unit-tested (verified
       by running the program); only `on_hand_coverage` was added to the
       PlanReport snapshot-fidelity test.
2. **`DebugLog` + dashboard — new top-level `swmtplanner.debuglog` module.**
   The original sub-steps 2 (verbose-logging methodology) and 3 (dashboard
   generator) are now realized here. `DebugLog` is a generic, config-driven
   table container (no hard-coded schema), so it lives at the top level rather
   than under `planners/infinite/`. It is the renamed `VerboseLog`:
   an optional object threaded (kwarg) through the planner loop / costing /
   demand views / schedule emission, which each populate as they run; it will
   subsume the after-the-fact reconstruction in `iterlog.py` / the `*_detail`
   machinery on `PlanReport`. Built over **four phases** — each gets its own
   DESIGN → code → coverage spec → tests when it begins (see
   `debuglog/DESIGN.md`).

   **Groundwork — divorce the old verbose path. ✅ done (uncommitted).** Before
   layering the new code in, the existing verbose-logging build path was cut
   from the live planner so the old structures stay referenceable without
   tangling: `plan()`'s `verbose` branch (accumulators/counters/
   `build_candidate_records`) is removed and the param is now **inert**;
   `_build_report` no longer attaches the `*_detail` tuples (always `None`);
   the CLI keeps `--verbose` but it's a **no-op**. **Kept untouched as
   reference:** `iterlog.py` (record types + builders), `report.py`'s verbose
   dataframe builders + `write_verbose_log_tsvs` + `write_dashboard_html` (now
   uncalled), and `costing.py`'s `cost_breakdown*` methods. 323 green.

   - **Phase 1 — simplified iteration log + cost summary. ⏸ next.** `DebugLog`
     carries just two tables: a **simplified `IterationLog`** (one row per
     scored candidate per iteration) and a **`CostSummary`**. Chosen because
     both are built **live as the loop runs** (unlike the output tables, built
     post-hoc), so they actually exercise the pass-the-object-and-write
     mechanic this phase exists to validate. No dashboard; iteration log
     deliberately simplified (schema refined later).
   - **Phase 2 — remaining tables (cost detail + output). ⏸ pending.** Add the
     cost detail tables for **inventory**, **schedule**, and **priority** (and
     expand the iteration log if needed), plus the output tables the regular
     Excel workbook produces (`demand`, `schedule`, `production`, `xref`,
     `unmet_demand`, `late_orders`) as **flat (no MultiIndex)** tables —
     deferred here because they're built at the end, not live.
   - **Phase 3 — raw dashboard. ⏸ pending.** Render the tables directly as
     HTML with foreign-key links surfaced (debug view only, no drill-down).
   - **Phase 4 — full dashboard. ⏸ pending.** Add the user-friendly
     machine→jobs→order→cost drill-down alongside the raw view.

### Step-3 tests — ✅ done (record of what was reworked)

- **Coverage specs**: `SCHEDULE_TEST_SPEC.md` (Phases 1–4) and
  `INF_PLAN_TEST_SPEC.md` brought to the Step-3 model — `Doff` per roll,
  `Hanging`/`Threading` + remove→hang→thread guard rails, three changeover
  types, `Status` accessor API + `Status.create`, doff-aware `next_runout`,
  and the `style_change`/`runner_change`/`pattern_change` split. `COORD_TEST_
  SPEC.md` needed no changes. (Decisions on file: `level_loading`/`old_machine`
  weights stay untested; `_activity_desc`/`cost_detail.tsv` are dev-only and
  intentionally unspecced.)
- **Test code**: `machine_tests.py` (accessor API, per-roll `Doff`, guard
  rails, doff-aware `next_runout` + `producible_lbs_in_week` caps),
  `inf_plan_tests.py` (new activity set, three changeover weights, doff-aware
  caps, `Machine(...)` constructor no longer takes change durations), and
  `coord_tests.py` (just the constructor-arg fix).

## Next concrete action

**First: commit the uncommitted work** — now two logical changes (consider
separate commits): (a) sub-step 1 (links + the `demand`/`xref` Excel tabs),
and (b) the sub-step-2 groundwork (divorcing the old verbose path; see the
sub-step-2 "Groundwork" note above). Sizable diff across `src/` and `tests/`;
323 green.

**Continue sub-step 2 — `debuglog` Phase 1 (simplified iteration log + cost
summary).** Phase 1 is **designed in full** (`swmtplanner/debuglog/DESIGN.md`):
the generic `DebugLog` API (`DebugLog(**tables)` of `(col, default)` tuples ·
`set_pk(table, col, ctr_name=None)` · `set_fk(table, col, foreign_table,
foreign_column)` · `add_row` → PK · `get_last_pk_val(table)` · `update_row(table,
pk_val, **kwargs)` · `get_df(table, **kwargs)`), the `iteration_log` /
`cost_summary` schemas, and the single-pass population flow.

**Code status:** the `DebugLog` **schema construction** is implemented —
`__init__`, `set_pk`, `set_fk` in `swmtplanner/debuglog/debuglog.py` (323
green). **Remaining for Phase 1:** the row methods (`add_row`,
`get_last_pk_val`, `update_row`, `get_df`), then wiring — thread the optional
`debuglog` kwarg through `plan` (score + rank the full candidate list, write
`iteration_log`, patch rank/role via `update_row`) and `Costing.score_after_move`
(build `cost_summary`, reading the id via `get_last_pk_val`). Then coverage
spec → tests.

DESIGN-first, narrow per turn (one section/concept), the user reviews each
section, then code → coverage spec → tests. Phases 2–4 (cost detail + output
tables, raw dashboard, full dashboard) follow in order, each designed when it
begins — see `swmtplanner/debuglog/DESIGN.md`.
