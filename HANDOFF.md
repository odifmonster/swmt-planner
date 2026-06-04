# Knit-planner refactor — session handoff

## Project context

Working in `~/git-repos/swmt-projs/knit-planner/` — a Python supply-chain
scheduling tool for a textile (knitting) manufacturer. This is one of
several parallel versions; this version implements **only the knitting
plant**. Layout:

- `src/swmtplanner/schedule/` — per-machine activity scheduling (the
  `Machine`, `Activity`, `Status` model).
- `src/swmtplanner/demand/` — per-item demand/fulfillment views
  (`RlsItem`, raw + safety-aware views).
- `src/swmtplanner/planners/infinite/` — the greedy planner that
  composes the two; CLI lives here; dashboard generator lives here.
- `tests/` — `*_tests.py` modules, spec files in `tests/spec-files/`.

Each major submodule has a `DESIGN.md` that's the source of truth for
the structure before implementation.

## Preferred workflow

For any significant change:

1. **DESIGN.md first** — edit the relevant DESIGN.md in the affected
   module(s). Iterate over multiple turns until aligned before any
   code.
2. **Implementation in phases** — small, reviewable diffs. Don't sweep
   multiple subsystems at once.
3. **Test specs in `tests/spec-files/`** for the new behavior, then
   implement the tests, then run them.

Within DESIGN.md edits, keep the scope per turn narrow (one section or
one concept). The user prefers to leave the doc temporarily
inconsistent across sections rather than do a big sweep, so:

- If the user says "update Core objects", do *only* Core objects —
  leave the rest stale.
- If they say "through the plan_production walk section", that means
  inclusive of that section, not beyond.
- They'll explicitly call out sections to skip ("beam-swap decision
  stays as-is").

## Current refactor: 3-step split of production from machine activities

The textile-floor team gave updated information that's prompting a
substantial rework of the schedule layer. The refactor is broken into
3 phases tracked as tasks in the Claude Code task list:

### Step 1 (in progress) — Separate production from schedule activities

Conceptually: a `Machine` now carries two parallel schedules.

- **Activity schedule** (`Machine.activities`) — physical machine
  activities. The activity formerly known as `Job(Activity)` is
  renamed to **`Knit(Activity)`** (same fields: `item`, `lbs`).
- **Production schedule** (`Machine.jobs`) — a list of **`Job`
  records** (NOT activities). Each `Job` is an "order" fulfilled by
  one `plan_production` call, holding the `item` and a tuple of
  `Roll(lbs, completion_time)` entries. Computed properties:
  `total_rolls`, `total_lbs`. A `Job` can span multiple `BeamLoad`s
  within a single call (unlike a `Knit`, which is one uninterrupted
  run).
- **`ProductionPlan(activities, jobs)`** — the new return type of
  `plan_production`. Committed via
  `Machine.add_activities(plan.activities)` +
  `Machine.add_jobs(plan.jobs)`.
- **`Machine.next_job_end` → `Machine.schedule_tail`** (and the
  `start_at='next_job_end'` literal → `'schedule_tail'`).
- The costing module previously filtered `Job` instances out of
  `Machine.activities`; now it should consume `Machine.jobs`
  directly.

**Step 1 progress:**

- ✅ `src/swmtplanner/schedule/DESIGN.md` — fully updated (Core
  objects, Purpose, Activity durations, Beam-swap decision incidental
  line, Roll-level production, plan_production walk, Capacity queries,
  Natural stopping points, File I/O, Test-placement contract,
  Integration with demand, Out of scope).
- ⏳ `src/swmtplanner/planners/infinite/DESIGN.md` — still has
  `next_job_end` references in several places (Move.start_at literal,
  Per-machine decision points, Decision window, Level-loading
  `dp_time`). Mechanical rename pending.
- ⏳ Code changes — not started. Will touch `schedule/activity/`,
  `schedule/machine/`, `planners/infinite/state/`,
  `planners/infinite/costing/`, `planners/infinite/loop/`,
  `planners/infinite/report.py`, and tests.

### Step 2 (pending, blocked on step 1) — New runout logic

The team revised two operational facts that change the runout model:

1. Beams can't be knit to zero — there's a residue floor.
   **`BEAM_FLOOR_LBS = 5 lbs`** (tunable).
2. Beam loads can happen mid-roll (the roll continues on the fresh
   beam). No more half-roll fallback.
3. Operators won't bother knitting through a near-empty beam.
   **`MAX_BEAM_WASTE_LBS = 100 lbs`** (tunable) — usable yarn
   (`bar_lbs - BEAM_FLOOR_LBS`) below this and the bar gets swapped
   before the next roll starts.

Mechanics:

- **`Waste(item, bar, lbs)`** activity (zero duration; the cost layer
  charges per-lb on a new `waste_lbs` weight).
- **Max-waste rule** (pre-roll gate): if `usable < MAX_BEAM_WASTE_LBS`,
  emit `Waste + BeamLoad` for that bar before the roll starts.
- **Post-load co-swap**: when one bar exhausts mid-roll, check the
  other; if its `usable < MAX_BEAM_WASTE_LBS`, swap both with one
  operation.
- **Changeover preamble** decides per-bar between `TapeOut` (preserve,
  machine runs in reverse) and `Waste` (discard) — same
  `MAX_BEAM_WASTE_LBS` threshold. `TapeOut` is emitted for the
  machine-time cost but the preserved beam isn't tracked in inventory
  yet.

`BeamLoad` stays as the existing single activity through step 2; it
splits in step 3.

### Step 3 (pending, blocked on step 2) — New activity types

- **`Doff` activity** — `DOFF_DURATION = 20 minutes`. Fieldless beyond
  `start`/`end` (matches `Idle`'s shape; kept as a distinct class for
  readability). One `Doff` per completed roll; the matching `Roll`'s
  `completion_time` is the Doff's `end`. The implicit invariant
  `Doff.end == Roll.completion_time` is the join.
- **`Hanging` + `Threading`** replace `BeamLoad`:
  - `Hanging(bars: 'top'|'btm'|'both')` — physical beam mount only.
  - `Threading(bars, top_beam, top_lbs, btm_beam, btm_lbs)` — yarn
    routing; this updates machine status.
  - Four new durations: `HANGING_SINGLE_DURATION`,
    `HANGING_BOTH_DURATION`, `THREADING_SINGLE_DURATION`,
    `THREADING_BOTH_DURATION` (values TBD from floor measurements).
- **`StyleChange` splits into three**:
  - Old machine, same family → `RunnerChange` (duration:
    `machine.simple_change_duration`).
  - Old machine, different family → `WheelChange` (duration:
    `machine.family_change_duration`).
  - New machine, any → `StyleChange` (duration:
    `machine.simple_change_duration`).
  - The `is_family_change` flag goes away; the activity class carries
    the semantic.
- Knits are now strictly bounded by `(0, item.tgt_wt]` (since every
  roll ends in a Doff).
- Cost layer: split `family_change` weight into
  `runner_change`/`wheel_change` (and a `style_change` for new
  machines), and add `waste_lbs` if not done in step 2.

## Task tracking

Three tasks exist in the Claude Code task list (`/tasks` or
equivalent):

- **#1 Step 1: Separate production from schedule activities** —
  in_progress.
- **#2 Step 2: New runout logic (BEAM_FLOOR + mid-roll loads +
  max-waste rule)** — pending, blocked by #1.
- **#3 Step 3: Add Doff, Hanging, Threading; split style-change
  activities** — pending, blocked by #2.

Use `TaskList` to view, `TaskGet` for full descriptions, `TaskUpdate`
to mark progress.

## Next concrete action

Continue step 1's DESIGN-doc work by sweeping
`src/swmtplanner/planners/infinite/DESIGN.md` for the `next_job_end` →
`schedule_tail` rename (Move literal, decision points, level-loading,
etc.). Code changes follow after that's done.
