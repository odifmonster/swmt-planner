# Knit-planner refactor — session handoff

## Project context

Working in `~/git-repos/swmt-projs/knit-planner/` — a Python supply-chain
scheduling tool for a textile (knitting) manufacturer. This is one of
several parallel versions; this version implements **only the knitting
plant**, and **this branch is the live patch branch** (quick, targeted
patches — it does *not* follow the design-driven-python plugin's templates;
the other branches do). Layout:

- `src/swmtplanner/schedule/` — per-machine activity scheduling
  (`Machine`, `Activity` subclasses, `Status`; plus the new `job/`
  submodule with the `Job`/`Roll` records).
- `src/swmtplanner/demand/` — per-item demand/fulfillment views
  (`RlsItem`, raw + safety-aware views).
- `src/swmtplanner/planners/infinite/` — the greedy planner that
  composes the two; CLI + dashboard generator live here.
- `tests/` — `*_tests.py` modules; coverage specs in
  `tests/spec-files/` (`SCHEDULE_TEST_SPEC.md`, `DEMAND_TEST_SPEC.md`,
  `COORD_TEST_SPEC.md`, `INF_PLAN_TEST_SPEC.md`).

Each major submodule has a `DESIGN.md` that is the source of truth for
structure before implementation.

**Running tests / Python:** the project virtualenv is `.dev-venv` (has
pandas/numpy; no pytest). Run with:
`PYTHONPATH=src:. .dev-venv/bin/python -m unittest tests.<module>`
(e.g. `tests.machine_tests`). Full suite currently: **278 tests, all
passing.**

## Preferred workflow

For any significant change:

1. **DESIGN.md first** — edit the relevant DESIGN.md, iterating over
   multiple turns until aligned, before any code.
2. **COVERAGE next** — update the relevant `tests/spec-files/*_SPEC.md`
   before writing test code.
3. **Then code, then tests, then run.** Small, reviewable diffs; don't
   sweep multiple subsystems at once.

Keep DESIGN/spec edits narrow per turn (one section or concept). The user
prefers leaving the doc temporarily inconsistent across sections rather
than a big sweep:

- "update Core objects" → do *only* Core objects, leave the rest stale.
- "through the plan_production walk section" → inclusive of that section,
  not beyond.
- They'll explicitly call out sections to skip.

The user reviews each section before moving on; surface design gaps/conflicts
rather than papering over them (this has caught real issues).

## The refactor: 4-step rework of the schedule layer

The textile-floor team gave updated information prompting a substantial
rework. Tracked as 4 tasks in the Claude Code task list (`TaskList` /
`TaskGet` / `TaskUpdate`):

- **#1 Step 1: Separate production from schedule activities** — ✅ CODE +
  TESTS COMPLETE.
- **#2 Step 2: New runout logic (BEAM_FLOOR + mid-roll loads + max-waste)**
  — 🔵 DESIGN COMPLETE; coverage/code/tests remaining.
- **#3 Step 3: Add Doff, Hanging, Threading; split style-change** — pending
  (blocked by #2).
- **#4 Step 4: Expand verbose audit — more FK links + log all candidates**
  — pending (blocked by #3; concretely couples to the Step-1 verbose
  tables).

> Commits are the user's to make. DESIGN.md changes were committed earlier;
> confirm the working-tree state of the Step-1 code/tests and Step-2 design
> before continuing.

---

### Step 1 — Separate production from schedule activities  ✅ COMPLETE

A `Machine` carries two parallel schedules:

- **Activity schedule** (`Machine.activities`) — `Knit` (was
  `Job(Activity)`; fields `item`, `lbs`), `Waste`, `TapeOut`, `BeamLoad`,
  `StyleChange`, `Idle`.
- **Production schedule** (`Machine.jobs`) — `Job` records (HasID): `item`,
  `rolls: tuple[Roll(lbs, completion_time)]`, computed `total_rolls` /
  `total_lbs`. No start/end; one per `plan_production` call (a `Job` can
  span multiple `BeamLoad`s; `'next_runout'` yields up to two Jobs).
- **`ProductionPlan(activities, jobs)`** — return of `plan_production`;
  committed via `add_activities(plan.activities)` + `add_jobs(plan.jobs)`.
- `Machine.next_job_end` → `Machine.schedule_tail` (literal
  `'next_job_end'` → `'schedule_tail'`), renamed across all code + tests.
- Costing consumes `Machine.jobs` / `move.plan.jobs` directly.

Done: all three DESIGN.md docs; `schedule/job/` submodule; `Knit` rename;
`ProductionPlan` in `machine.py`; `plan_production` populates
`ProductionPlan.jobs` (real `Job`/`Roll` records, straddling beam loads);
all consumers migrated (`status.py`, `state.commit_move`, `costing.py`,
`report.py`, `iterlog.py`, `demand/view.py`, `demand/rlsitem.py`); `.pyi`
stubs; full test suite + coverage specs updated and green (278 tests).

Note: the verbose-log `cost_id`+`sched_id` were consolidated into a single
`move_id`; the five `*_detail_id` counters were **left as-is** (their
consolidation is part of **Step 4**). `job_id` = `Job.id`.

### Step 2 — New runout logic  🔵 DESIGN COMPLETE (coverage/code/tests next)

Operational facts that change the runout model:

1. Beams can't be knit to zero — residue floor **`BEAM_FLOOR_LBS = 5`**
   (tunable). Usable yarn on a bar = `bar_lbs - BEAM_FLOOR_LBS`.
2. Beam loads can happen **mid-roll** — a roll continues on the fresh beam.
   The half-roll fallback is **gone**; rolls are always whole (~`tgt_wt`),
   but a `Knit` can end mid-roll with a partial-roll weight (rolls straddle
   `BeamLoad`s). `Knit.lbs` is no longer constrained to whole rolls.
3. Operators won't knit through a near-empty beam:
   **`MAX_BEAM_WASTE_LBS = 100`** (tunable) — usable below this and the bar
   gets swapped before the next roll.

Mechanics (all in the schedule/machine logic; demand layer is unaffected —
it only cares when lbs land):

- **`Waste(item, bar, lbs)`** — now *unknit* discarded yarn from a
  swapped-out beam (was knit sub-half fabric). **Zero duration.** Applying
  it empties the named `bar` (beam→None, lbs→0); a paired `BeamLoad`
  refills. Cost layer charges per-lb via a new **`waste_lbs`** weight.
- **Run-up** — produces whole rolls only; emits no `Waste` and no beam
  work; leaves leftover yarn for the preamble.
- **Changeover preamble** — uniform per-bar rule on
  `usable = bar_lbs - BEAM_FLOOR_LBS`: empty/floor→`BeamLoad`; yarn
  matches→keep; mismatch & `usable > MAX`→`TapeOut`+`BeamLoad` (preserve,
  machine reverses, preserved beam not tracked yet); mismatch &
  `usable <= MAX`→`Waste(bar)`+`BeamLoad` (discard). `TapeOut('both')`
  possible in both modes.
- **Production loop** — `resolve()` per bar (`usable<=0`→`BeamLoad`;
  `0<usable<MAX`→`Waste`+`BeamLoad`); pre-roll max-waste gate; mid-roll
  runout + co-swap of the other bar; rolls straddle; one `Knit` spans
  consecutive rolls until a beam event. (`_split_roll`/half-roll removed.)
- **`next_runout`** stops at `BEAM_FLOOR` (`usable = bar_lbs - floor`).

`BeamLoad` stays a single activity through Step 2; it splits in Step 3.

**DESIGN status:** `schedule/DESIGN.md` fully updated (Constants section
now centralizes ALL module-level constants — durations, fresh-beam denier,
`BEAM_FLOOR_LBS`, `MAX_BEAM_WASTE_LBS`). `planners/infinite/DESIGN.md`
updated for the `waste_lbs` cost weight (CostWeights / CostBreakdown /
CostDetailRecord / `cost_detail.tsv` / costing bullets / Phase-1 prose;
"eleven"→"twelve" components throughout). `demand/DESIGN.md` unchanged.

**Step 2 remaining:**

1. **COVERAGE** — `SCHEDULE_TEST_SPEC.md` Step-2 additions (run-up
   whole-rolls/no-Waste/no-beam-work; preamble per-bar tape/waste/keep/load
   + `'both'`; production loop straddle / pre-roll gate / co-swap / floor;
   `next_runout` floor; `Waste` status zeroes its bar; capacity with
   floor). `INF_PLAN_TEST_SPEC.md` — the `waste_lbs` cost-weight case
   (§1.2.x).
2. **Code** — `machine.py` (constants, run-up, preamble, production loop,
   `next_runout`, remove `_split_roll`); `status.py` (`Waste.apply_activity`
   = empty the named bar); `costing.py` (`waste_lbs` weight + schedule
   penalty term).
3. **Test code** — update affected `*_tests.py`, then run the suite.

### Step 3 (pending, blocked on Step 2) — New activity types

- **`Doff`** — `DOFF_DURATION = 20 min`; fieldless beyond `start`/`end`
  (matches `Idle`'s shape, distinct class for readability). One per
  completed roll; invariant `Doff.end == Roll.completion_time`.
- **`Hanging` + `Threading`** replace `BeamLoad`:
  - `Hanging(bars: 'top'|'btm'|'both')` — physical beam mount only.
  - `Threading(bars, top_beam, top_lbs, btm_beam, btm_lbs)` — yarn routing;
    updates machine status.
  - New durations `HANGING_SINGLE/BOTH_DURATION`,
    `THREADING_SINGLE/BOTH_DURATION` (values TBD from floor measurements).
- **`StyleChange` splits into three**: old machine + same family →
  `RunnerChange` (`simple_change_duration`); old machine + different family
  → `WheelChange` (`family_change_duration`); new machine, any →
  `StyleChange` (`simple_change_duration`). `is_family_change` flag goes
  away — the class carries the semantic.
- Knits strictly bounded by `(0, item.tgt_wt]` (every roll ends in a Doff).
- Cost layer: split `family_change` into `runner_change`/`wheel_change`
  (+ a `style_change` for new machines).

### Step 4 (pending, blocked on Step 3) — Expand verbose audit

- Add more FK links across the verbose detail tables, and consolidate the
  five `*_detail_id` counters to key off `move_id` (deferred from Step 1).
- Possibly add a true knit-start to the production sheet / `job_detail`
  via a job→activity link (a `Job` currently has no start).
- Expand the iteration log to include **all** considered candidates per
  iteration (remove the top-4-items × top-4-candidates / 16-row
  truncation).

## Next concrete action

Start **Step 2 coverage**: add the Step-2 cases to
`tests/spec-files/SCHEDULE_TEST_SPEC.md` (run-up, preamble, production loop,
`next_runout`, `Waste` status, capacity), plus the `waste_lbs` cost-weight
case in `INF_PLAN_TEST_SPEC.md`. Then code (`machine.py`, `status.py`,
`costing.py`), then test code, then run the suite. DESIGN-first, narrow per
turn; the user reviews each section.
