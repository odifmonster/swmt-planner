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

> **Suite state:** through Step 2 the suite was **285 tests, all passing**.
> The Step-3 *code* rework has landed but the **tests have NOT been updated
> yet** — the suite is currently **stale and will fail** (it references the
> old `Status` structure, `BeamLoad`, `family_change`, and Step-2
> mechanics). The `swmtplanner` package itself **imports cleanly** and the
> schedule layer is smoke-verified; the costing layer is verified in
> isolation. Updating the tests is the remaining work (see "Next").

## Preferred workflow

For any significant change: **DESIGN.md first** (iterate over multiple turns,
one section/concept per turn — the user reviews each before moving on), then
**coverage spec**, then **code**, then **test code**, then run. Small,
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
| **3** | Add `Doff`, split `BeamLoad`→`Hanging`/`Threading`, split changeover | 🟡 design ✅ + **all `src/` code ✅ committed**; **tests remaining** |
| **4** | Expand verbose audit (more FK links, consolidate `*_detail_id`, log all candidates) | ⏸ pending (blocked by #3) |

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

### Step 3 — design ✅, code ✅ (committed), tests remaining

**Design** (both `schedule/DESIGN.md` and `planners/infinite/DESIGN.md`) is
fully updated. **All `src/` code is implemented and committed**; the package
imports and the schedule layer is smoke-clean. What was built:

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

### Step 4 — pending (blocked on Step 3)

More FK links across the verbose detail tables; consolidate the five
`*_detail_id` counters to key off `move_id`; possibly a job→activity link
for a true knit-start; expand the iteration log to log **all** considered
candidates (remove the 16-row truncation).

## Next concrete action

**Update the Step-3 tests + coverage specs** (the package imports and the
schedule layer is smoke-verified, so the suite can actually run again):

1. **Coverage specs first** — bring `SCHEDULE_TEST_SPEC.md` and
   `INF_PLAN_TEST_SPEC.md` to the Step-3 model: `Doff` per roll +
   `completion_time == Doff.end`; `Hanging`/`Threading` (and the guard
   rails / remove→hang→thread sequencing); the three changeover types;
   the `Status` accessor API + `Status.create`; doff-aware `next_runout`;
   costing `style_change`/`runner_change`/`pattern_change` (fourteen
   components); `_activity_desc` for the new activities.
2. **Test code** — rework `tests/machine_tests.py` (biggest: `Status(...)`
   → `Status.create(...)`, `.top_beam`→`.beam('top')`, all activity-sequence
   assertions for `Doff`/`Hanging`/`Threading`/changeovers, per-roll doffs,
   `next_runout` math, guard-rail raises), `tests/inf_plan_tests.py`
   (`CostWeights` three changeover weights; `_activity_desc`; `cost_detail`
   columns; any `Status` construction), and `tests/coord_tests.py` (check
   any machines-file fixtures for dropped `style_change_time` /
   `family_change_time` keys — they're now ignored, so harmless, but verify).
3. Run each module, then the full suite, until green.

DESIGN/spec-first, narrow per turn; the user reviews each section.
