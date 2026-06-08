# Infinite Plant — Knitting Planner — Design

Top-level planner for the Infinite Knitting plant. Composes `schedule/`
(per-machine scheduling) and `demand/` (per-item fulfillment costing) into
a global optimizer that decides which greige to produce on which machine,
in what quantity, and in what order across the 4-week planning horizon.

This planner targets the knitting plant only. The broader project's
goal is an end-to-end supply-chain planner; downstream (dyeing,
finishing) lives in separate future submodules.

## Purpose

Given:

- A set of knitting machines, each with its initial threading and
  schedule (`Machine` instances).
- A set of released greige items, each with weekly demand, on-hand
  inventory, and lead time (`RlsItem` instances).
- A cost-weighting configuration.

Produce:

- A committed schedule on each `Machine` (its `activities` populated via
  `add_activities`).
- Matching `Job` registrations on each `RlsItem` (`register_jobs`).
- A summary of the resulting cost components and any unmet demand.

The planner introduces no new physical concepts. Its job is to choose
*placements* — `(machine, item, lbs, start_at, idle_for)` tuples — by
composing the existing `schedule/` and `demand/` operations.

## Inputs

The planner is invoked against:

- `machines: dict[str, Machine]` — keyed by machine id, already
  constructed with their initial state.
- `rls_items: dict[str, RlsItem]` — keyed by greige id, already
  constructed with weekly demand and on-hand inventory.
- `start_date: datetime` — the planning anchor; matches each
  `RlsItem.start_date`.
- `weights` — cost-weighting config that the costing module consumes
  (see below).

Constructing these from spreadsheets is a separate concern; the planner
takes them ready-made.

## High-level structure

Four modules under `infinite/`. Each has a single, well-defined
responsibility, and the main loop only knows the surface of each rather
than the internals. `coordination/` is Phase 2; the other three are
Phase 1.

### `state/`

The plant-wide state. A bag of data plus its mutation operations.

```
State
  machines: dict[str, Machine]
  rls_items: dict[str, RlsItem]
  start_date: datetime
  window_end: datetime              # right edge of the decision window
  reference_week_idx: int           # right edge of the priority "urgent" bucket
  # tuneable thresholds and step sizes (window_advance_amount,
  # carrying_avoidance_margin, candidate_threshold,
  # reference_advance_amount, reference_threshold,
  # planning_horizon_buffer)
  commit_move(move) -> None
  advance_window() -> None          # extends window_end forward
  advance_reference_week() -> None  # extends reference_week_idx forward
```

`State` is a thin container. Its primary purpose is to let any function
take `state` as a single argument rather than threading a half-dozen
dicts through call signatures. It owns three mutation operations:

- `commit_move` applies a chosen `Move` by calling the underlying
  `Machine` and `RlsItem` methods in lockstep.
- `advance_window` extends `window_end` forward so additional decisions
  become eligible (see "Decision window" below).
- `advance_reference_week` extends `reference_week_idx` forward so
  additional regular orders count as urgent for priority purposes (see
  "Priority assignment" below). Added in Phase 2.

Keeping these in `state/` rather than in the main loop keeps the loop
short and gives us a single point of truth for "what does it mean to
update state".

### `costing/`

Scores any `State` as a single scalar. Three ingredients combined into
one number:

1. **Weighted sum of per-item demand costs.** For each `RlsItem`, read
   the four `CostComponents` (`lateness`, `drainage`, `carrying`,
   `excess`) from its raw and safety views and multiply by their
   respective weights. Sum across all rls_items.

2. **Per-machine schedule penalties.** Walk each machine's activities
   and accumulate:
   - One `tape_out_single` per `TapeOut(bars='top')` or
     `TapeOut(bars='btm')`.
   - One `tape_out_both` per `TapeOut(bars='both')`.
   - One per changeover activity, by type (the activity class carries the
     semantic — there is no `is_family_change` flag): `style_change` per
     `StyleChange` (a new machine's uniform reconfigure), `runner_change`
     per `RunnerChange` (a legacy machine's within-pattern-family change),
     `pattern_change` per `PatternChange` (a legacy machine's
     cross-pattern-family rework). These three replace the old single
     `family_change`.
   - `idle_time × hours` per `Idle` activity, where `hours` is the
     activity's work-hour duration. Discourages letting a machine sit
     unstaffed longer than necessary — including the carrying-avoidance
     idles inserted by the candidate enumerator (see below).
   - `waste_lbs × lbs` per `Waste` activity, charging each lb of yarn the
     plan discards at a beam swap. `Waste` is zero-duration, so this per-lb
     charge is its only contribution to the score.

   `Knit`, `Doff`, `Hanging`, and `Threading` carry **no** schedule weight:
   their time is reflected in downstream start times (and a doff attends
   every roll, so it isn't avoidable), but they incur no extra penalty.

   The time these activities consume is *already* reflected in
   downstream activity start times. These weights are extra
   discouragement on top of that — "we'd rather not do this even if
   the time fits".

3. **Cross-cutting aggregates** (Phase 2+). Penalties that compare each
   candidate against the others in the same iteration's pool — costs no
   single item's or machine's view can capture alone. Phase 2 adds three:
   - **Priority cost** — for each move, sum the *predicted lateness
     lb-days* across every higher-priority regular order under the
     assumption that, if the planner doesn't address them now, those
     orders won't ship until at least one day past their `due_date` or
     until the earliest decision point on a different machine —
     whichever is later. Weighted by `w.priority`. The result is an
     opportunity cost: the higher-priority orders being deferred by
     this move. See "Priority cost" below for the formula.
   - **Level-loading cost** — `work_hours_delta × w.level_loading` per
     move, where the delta is from the earliest decision point in the
     candidate pool. Encourages spreading work across machines instead
     of piling onto the one that happens to score lowest in isolation.
   - **Old-machine cost** — `w.old_machine` per move that targets a
     legacy machine (`not Machine.is_new`) when at least one of the
     same item's candidates targets a new machine. New machines are
     faster and easier to change over, so we'd rather route work to
     them whenever the candidate pool offers the choice.

   See "Plant-wide coordination" below for all three. Future cross-
   cutting terms — once real-data behavior tells us priority +
   level-loading + new-machine preference isn't enough — may include
   plant-wide total excess, per-machine utilization imbalance, and
   aggregate changeover time.

```
CostWeights
  # per-item demand weights (Phase 1)
  lateness, drainage, carrying, excess: float
  # per-machine schedule weights (Phase 1)
  tape_out_single, tape_out_both: float                  # per occurrence
  style_change, runner_change, pattern_change: float     # per changeover, by type
  idle_time: float                                       # per work-hour
  waste_lbs: float                                       # per lb of discarded Waste
  # cross-cutting weights (Phase 2)
  priority: float                                        # per rank step
  level_loading: float                                   # per work-hour delta from earliest DP
  old_machine: float                                     # per move on a legacy machine when a new one is candidate-available

Costing
  score(state) -> float                                  # current state's score (no ctx — cross-cutting costs are per-move)
  score_after_move(state, move, ctx) -> float            # post-commit score, pure
  cost_breakdown(state) -> CostBreakdown                 # current state's breakdown; serves as the baseline for delta computation in verbose mode
  cost_breakdown_after_move(state, move, ctx) -> CostBreakdown   # same total broken down per component, pure

CostBreakdown                                            # plain named record returned by cost_breakdown and cost_breakdown_after_move
  # demand-side weighted totals + absolute per-item breakdown (the loop subtracts baseline to derive deltas for the per-cost detail tables in verbose mode)
  lateness: float                                        # weighted total across all rls_items for the state this CostBreakdown describes
  lateness_by_item: dict[str, float]                     # absolute weighted per-item contribution for that state; only items with a non-zero contribution are present
  drainage: float
  drainage_by_item: dict[str, float]
  carrying: float
  carrying_by_item: dict[str, float]
  excess: float
  excess_by_item: dict[str, float]
  # schedule weighted scalars (no per-item structure — these are not summed across items)
  tape_out_single, tape_out_both: float
  style_change, runner_change, pattern_change: float
  idle_time: float
  waste_lbs: float
  # cross-cutting weighted scalars; priority gets an absolute per-item breakdown (not delta), since priority cost is per-move and does not exist in the baseline
  priority: float
  priority_by_item: dict[str, PriorityContribution]      # absolute weighted per-item contribution; at most one entry per item (each item contributes at most one regular order to the candidate pool per iteration, so its higher-priority counterpart is unique); empty for cost_breakdown(state)
  level_loading, old_machine: float                      # no per-item structure (level_loading is per-machine; old_machine is a flat per-move flag)
  total: float                                           # sum of the fourteen weighted components above

PriorityContribution                                     # value type for CostBreakdown.priority_by_item; the item_id is the enclosing dict key
  week_idx: int                                          # week (0..3) of the item's deferred regular order
  remaining_lbs: float                                   # unfulfilled lbs of the order at the time of evaluation (O.remaining_lbs)
  priority: float                                        # absolute weighted contribution: w.priority × remaining_lbs × 2^days_late(O, move)
```

`ctx` is a `ScoringContext` (see "Plant-wide coordination" below) that
bundles the priorities dict, the earliest DP time, and the
new-machine-availability dict so the scorer can
compute the cross-cutting cost contributions without re-running the
priority sort or the candidate-wide min-DP scan. Only
`score_after_move` and `cost_breakdown_after_move` consume `ctx`;
`score(state)` reports the per-item + per-machine portion of the score
for a state with no in-iteration move under consideration (e.g., the
post-loop final score in `PlanReport.total_score`).

`score_after_move` is the loop's hot path. It computes what `score`
would return if `move` were committed, without actually mutating
anything — built on `RlsItem.cost_if(jobs)` for the demand-side
contributions, on inspecting `move.plan.activities` for the schedule-side
changeover contributions, and on the `ctx` lookups for the cross-
cutting contributions.

`cost_breakdown_after_move` returns the same total broken down into
one weighted scalar per component, plus absolute per-item dicts for
the four demand-side costs (`lateness_by_item`, `drainage_by_item`,
`carrying_by_item`, `excess_by_item`) *and* for priority cost
(`priority_by_item`, with `PriorityContribution` values so each
entry also carries the deferred order's `week_idx` and
`remaining_lbs`). `cost_breakdown(state)` returns the same shape
for the current (baseline) state with no move applied — its
`priority`, `level_loading`, and `old_machine` fields are 0
(`priority_by_item` is empty) because those costs are per-move.

The verbose loop calls `cost_breakdown` once at the start of each
iteration to capture the baseline, then `cost_breakdown_after_move`
per candidate. The demand-side detail tables hold *deltas* derived
by the loop as `after_move.{cost}_by_item[item] -
baseline.{cost}_by_item[item]`, with zero-delta items dropped. The
priority detail table holds the *absolute* per-item contributions
from `after_move.priority_by_item` directly, since the baseline has
none to subtract; each row also reports the deferred order's
`week_idx` and `remaining_lbs` so an operator can see exactly which
urgent orders this move is passing over and how much unfulfilled
demand each represents (see "Verbose iteration log" under the CLI
section). The hot loop keeps calling `score_after_move`; the
breakdown path is only walked when `plan` is invoked with
`verbose=True`.

### `coordination/` (Phase 2)

Plant-wide relationships across candidate orders and decision points.
Holds the cross-cutting identity (`OrderKey`), the scoring bundle
(`ScoringContext`), and the priority ranker (`assign_priorities`). The
costing layer consumes a `ScoringContext` but doesn't own its
construction — `coordination/` does, so the priority sort and the
shape of the cross-candidate inputs can evolve without touching
`costing/` or `loop/`. See "Plant-wide coordination" below for the
mechanism.

### `loop/`

The main iteration. Greedy: at each step, score every candidate move
and commit the one with the lowest resulting state score.

```
Move
  machine_id: str
  item: Greige
  lbs: float
  start_at: Literal['schedule_tail', 'next_runout']
  idle_for: timedelta
  week_idx: int | None    # which order this move addresses; None for safety (Phase 2)
  plan: ProductionPlan    # cached output of machine.plan_production

plan(state, costing) -> PlanReport
```

`plan` is the entrypoint. It iterates:

1. **Advance the reference week** while the count of items with at
   least one unmet `RegularOrder` at or before
   `state.reference_week_idx` falls below `state.reference_threshold` —
   see "Priority assignment" below. (Phase 2.)
2. **Enumerate** candidate `Move`s from the current state, filtered by
   the decision window — see "Candidate enumeration" below.
3. **If empty**, `state.advance_window()` and re-enumerate. If the
   window has reached the planning horizon and still empty, terminate.
4. **Build the scoring context** (Phase 2): assign priorities via
   `assign_priorities(state)`, compute `earliest_dp_time` as
   `min(dp_time(c) for c in candidates)`, and pack both into a
   `ScoringContext` — see "Plant-wide coordination" below.
5. **Score** each candidate via
   `costing.score_after_move(state, move, ctx)`.
6. **Commit** the lowest-scoring move via `state.commit_move(move)`.
   The score serves only as a tie-breaker among eligible candidates
   within an iteration; there is no "best must improve" check, because
   committing demand reliably matters more than minimizing score at any
   single step.
7. **Maintain** the window: if the in-window candidate count fell below
   the configured threshold after the commit, `state.advance_window()`.
8. **Repeat.**

`PlanReport` is the artifact the operator actually consumes. Returned at
the end of `plan`:

```
PlanReport
  # the planned schedule — the headline output of the planning tool
  schedules: dict[str, tuple[Activity, ...]]    # machine_id -> activities
  jobs_by_item: dict[str, tuple[Job, ...]]      # greige_id -> jobs registered
  # final cost picture
  total_score: float
  cost_components_by_item: dict[str, CostComponents]
  # what couldn't be placed
  unmet_lbs_by_item_week: dict[tuple[str, int], float]
  # which orders ship late and when they finish filling
  late_orders: tuple[RawOrder, ...]
  # per-iteration audit trail (populated only when plan(..., verbose=True);
  # all ten are None when verbose=False)
  iteration_log:    tuple[IterationLogRecord, ...]   | None
  cost_detail:      tuple[CostDetailRecord, ...]     | None
  lateness_detail:  tuple[LatenessDetailRecord, ...] | None
  drainage_detail:  tuple[DrainageDetailRecord, ...] | None
  carrying_detail:  tuple[CarryingDetailRecord, ...] | None
  excess_detail:    tuple[ExcessDetailRecord, ...]   | None
  priority_detail:  tuple[PriorityDetailRecord, ...] | None
  schedule_detail:  tuple[ScheduleDetailRecord, ...] | None
  job_detail:       tuple[JobDetailRecord, ...]      | None
  roll_detail:      tuple[RollDetailRecord, ...]     | None

IterationLogRecord                              # one row of iteration_log.tsv; one record per (iteration, scored candidate)
  iteration_idx: int                            # 0-indexed main-loop iteration
  role: Literal['committed', 'rejected']        # whether this candidate was the one committed
  score_rank: int                               # rank across all scored candidates in the iteration (0 = lowest score; the committed move is always 0)
  item_score_rank: int                          # rank within this item's candidates (0 = lowest-scoring same-item candidate; the committed move is always 0)
  # candidate identity
  item_id: str
  target_type: Literal['regular', 'safety']
  target_week: int | None                       # week_idx for regular orders; None for safety
  machine_id: str
  machine_is_new: bool                          # convenience flag; reads from state.machines[machine_id].is_new
  start_at: Literal['schedule_tail', 'next_runout']
  idle_hours: float                             # move.idle_for converted to hours
  # summary + foreign keys into the detail tables
  total_score: float                            # equals cost_detail[move_id].total
  move_id: int                                  # this candidate's id; foreign key into cost_detail, schedule_detail, and job_detail (one row / group per scored candidate)

CostDetailRecord                                # one row of cost_detail.tsv; one record per scored candidate
  move_id: int                                  # primary key; matches iteration_log.move_id
  # weighted scalars (same numeric values as the CostBreakdown totals)
  lateness, drainage, carrying, excess: float
  tape_out_single, tape_out_both: float
  style_change, runner_change, pattern_change, idle_time, waste_lbs: float
  priority, level_loading, old_machine: float
  total: float                                  # sum of the fourteen weighted components above
  # foreign keys into the per-cost detail tables; None when no item contributes to the corresponding cost
  lateness_detail_id: int | None
  drainage_detail_id: int | None
  carrying_detail_id: int | None
  excess_detail_id:   int | None
  priority_detail_id: int | None                # None when no higher-priority order is being skipped (priority cost == 0)

LatenessDetailRecord                            # one row of lateness_detail.tsv; one record per (candidate, item whose lateness contribution would change from baseline)
  lateness_detail_id: int                       # groups all rows from one candidate's lateness deltas
  item_id: str
  lateness_delta: float                         # weighted per-item delta: w.lateness × (after_move.raw_view.lateness - baseline.raw_view.lateness); rows with delta == 0 are omitted

DrainageDetailRecord                            # same shape, for drainage
  drainage_detail_id: int
  item_id: str
  drainage_delta: float

CarryingDetailRecord                            # same shape, for carrying
  carrying_detail_id: int
  item_id: str
  carrying_delta: float

ExcessDetailRecord                              # same shape, for excess
  excess_detail_id: int
  item_id: str
  excess_delta: float

PriorityDetailRecord                            # one row of priority_detail.tsv; one record per (candidate, item whose deferred regular order is higher-priority than this move's order)
  priority_detail_id: int                       # groups all rows from one candidate's priority breakdown
  item_id: str                                  # owner of the higher-priority deferred order; appears at most once per priority_detail_id (each item contributes at most one regular order to the candidate pool per iteration)
  week_idx: int                                 # week (0..3) of the deferred order
  remaining_lbs: float                          # unfulfilled lbs of the deferred order at the time of evaluation (O.remaining_lbs)
  priority: float                               # absolute weighted contribution: w.priority × remaining_lbs × 2^days_late(O, move); not a delta — baseline has no priority cost

ScheduleDetailRecord                            # one row of schedule_detail.tsv; one record per Activity in a candidate's move.plan.activities
  move_id: int                                  # groups all rows from one candidate's plan.activities
  activity_id: str                              # the Activity's own id (Activity.id); unique across the run
  machine_id: str
  start: datetime
  end: datetime
  description: str                              # human-readable rendering of the activity and its key fields (e.g. "Knit item=ABC lbs=1400", "TapeOut both", "PatternChange ABC→XYZ", "Doff", "Threading both")

JobDetailRecord                                 # one row of job_detail.tsv; one record per Job in a candidate's move.plan.jobs
  move_id: int                                  # foreign key into iteration_log; groups all jobs from one candidate (a move yields 1 or 2 jobs)
  job_id: str                                   # the Job's own id (Job is HasID); groups this job's roll_detail rows
  item_id: str                                  # job.item.id
  total_rolls: int                              # job.total_rolls
  total_lbs: float                              # job.total_lbs

RollDetailRecord                                # one row of roll_detail.tsv; one record per Roll in a candidate's job
  move_id: int                                  # foreign key into iteration_log
  job_id: str                                   # foreign key into job_detail (the owning Job)
  roll_idx: int                                 # unique id for this roll; auto-incremented across the verbose run (Roll has no id of its own)
  lbs: float                                    # roll.lbs
  completion_time: datetime                     # roll.completion_time

IterLogCounters                                 # loop-owned bundle of auto-incrementing id counters for the verbose tables; built once per verbose run, each field a zero-arg callable returning the next int in its own independent sequence
  move_id: () -> int                            # per scored candidate (collapsed the former cost_id + sched_id)
  roll_idx: () -> int                           # per RollDetailRecord; Roll carries no id of its own, so the loop assigns one
  lateness_detail_id: () -> int                 # per non-empty lateness delta group
  drainage_detail_id: () -> int                 # per non-empty drainage delta group
  carrying_detail_id: () -> int                 # per non-empty carrying delta group
  excess_detail_id: () -> int                   # per non-empty excess delta group
  priority_detail_id: () -> int                 # per non-empty priority group
  # activity_id and job_id are NOT counters here — they are record-owned
  # ids (Activity.id, Job.id); only Roll, which has no id, needs a counter
```

The full schedules also remain on the `Machine` instances inside
`state`; the report bundles them into a self-contained snapshot so
callers can persist or render without holding the mutable `State`
around.

`late_orders` is the sequence of `RawOrder`s across all rls_items
whose `late_lbs > 0` after the planner's last commit — sourced
directly from each `RlsItem.raw_view.orders` and filtered. Each
order's `late_lbs` and `late_fill_date` come from
`RawView.recompute` (see `demand/DESIGN.md`). The CLI uses this
sequence to build the operator-facing `late_orders` sheet.

`iteration_log` is populated only when `plan` is called with
`verbose=True`. Each main-loop iteration that commits a move
contributes up to 16 records, selected by a two-level group-then-
top-k rule:

1. Group the iteration's candidates by `item_id`.
2. Rank items by their lowest-scoring candidate (each item's best
   shot at being committed); select the top 4 items.
3. Within each selected item, log the top 4 lowest-scoring
   candidates of that item.

The committed move — always the lowest-scoring candidate of the
lowest-scoring item — is logged with `score_rank == 0`,
`item_score_rank == 0`, `role == 'committed'`. All other logged
candidates are `role == 'rejected'`. If the iteration has fewer
than 4 candidate items, all items are logged; if a selected item
has fewer than 4 candidates, all of that item's candidates are
logged. The two-level rule separates two questions the old global
top-4 conflated — "why this candidate?" (same-item siblings) and
"why this item?" (runner-up items) — and puts both within reach in
a single block.

**Tie-breaking.** Ranks are deterministic so the log is
reproducible. When two items' lowest candidates score equal, items
are ordered by `item_id`. When two candidates score equal — used to
compute both `score_rank` (across the pool) and `item_score_rank`
(within an item) — the order is by `item_id`, then `machine_id`,
then decision point with `next_runout` ordered before
`schedule_tail`.

The nine companion detail tuples on `PlanReport` are populated in
lockstep with `iteration_log`. At the start of each iteration the
loop captures a baseline `CostBreakdown` via
`Costing.cost_breakdown(state)`; for each scored candidate it then
calls `Costing.cost_breakdown_after_move(state, move, ctx)` and,
using the baseline, emits in addition to the candidate's
`IterationLogRecord`:

- one `CostDetailRecord` holding the fourteen weighted post-commit
  scalars and per-cost detail-table FKs;
- one row per `item_id` whose contribution to a given demand-side
  cost would *change* from baseline (`after_move.{cost}_by_item -
  baseline.{cost}_by_item`), with zero-delta items dropped; rows
  go into `lateness_detail`, `drainage_detail`, `carrying_detail`,
  or `excess_detail` as appropriate and are grouped by their
  respective `*_detail_id`;
- one row per `item_id` in `after_move.priority_by_item` (i.e.,
  each item whose deferred regular order is higher-priority than
  this move's order), grouped by `priority_detail_id`; each row
  carries the deferred order's `week_idx` and `remaining_lbs`
  alongside the *absolute* weighted contribution (no baseline to
  subtract from);
- one `ScheduleDetailRecord` per `Activity` in `move.plan.activities`,
  grouped by `move_id`;
- one `JobDetailRecord` per `Job` in `move.plan.jobs` (1 or 2 per
  candidate), grouped by `move_id`;
- one `RollDetailRecord` per `Roll` in each job's `rolls`, grouped
  by `job_id` (and carrying `move_id`).

In practice the move touches the jobs and on_hand of at most two items:
`move.item` and `machine.current_status.current_item`, so the four
demand-side delta dicts have at most two entries each — that item,
and the previous running item if `move.start_at == 'next_runout'`, and
only if the demand-side costs on those items actually change. The
priority dict can have many entries, one per item with a deferred
higher-priority regular order — each item appears at most once,
since the candidate enumerator picks at most one regular order per
item per iteration, so its higher-priority counterpart is unique.
The per-item attribution exposes *which* urgent orders are being
passed over and how much unfulfilled demand each carries, which is
exactly the diagnostic an operator needs when an urgent order
doesn't get committed.

Cross-table links are ids owned by the loop, bundled in
`IterLogCounters`. `move_id` (the scored candidate), `roll_idx`, and
the five `*_detail_id` counters are auto-incremented integers, each
starting at 1 at the beginning of the verbose run. `activity_id` and
`job_id` are not counters — they are the record-owned ids `Activity.id`
and `Job.id`; `roll_idx` exists as a counter only because `Roll` has
no id of its own. `job_id` is reused as the `job_detail`→`roll_detail`
link.
A `*_detail_id` is omitted (`None` on the
`CostDetailRecord`, blank cell in the TSV) when the corresponding
cost would have no contributing rows (no non-zero deltas for the
four demand-side costs; no higher-priority skipped orders for
priority), and the matching detail table emits no rows for that
candidate.

With `verbose=False` (the default), all ten tuples are `None`,
`Costing.cost_breakdown` is never called, and the loop skips the
breakdown path entirely — the verbose mode is strictly opt-in.

## Candidate enumeration

Each iteration of the main loop builds a fixed set of candidate `Move`s
from the current `State`. The candidates are the Cartesian product of
three axes — machine × decision point × eligible order — and each tuple
becomes one `Move` with derived `lbs`, `start_at`, and `idle_for`.

### Per-machine decision points

Every machine has up to two natural points in time at which new
production could begin:

- **`schedule_tail`** — the schedule tail (`current_status.as_of`).
  Starts production sooner but pays the full changeover preamble
  (`TapeOut` + re-threads (`Hanging` + `Threading`) + the changeover
  activity as needed).
- **`next_runout`** — the forward-extrapolated time at which the
  current item's beam(s) would exhaust if the machine kept running.
  Waits out the current beam but avoids the `TapeOut` for the
  naturally-exhausted bar.

If the two coincide (the schedule has just exhausted a beam at its
tail), they collapse into a single decision point. The enumerator
considers both per machine; the scorer picks whichever yields the lower
total state cost.

### Per-item eligible orders

Each `RlsItem` contributes at most two orders to the candidate set:

- **Regular order** — the earliest week with unmet demand (lowest
  `week_idx` where `remaining_lbs > 0`). At most one per item per
  iteration.
- **Safety replenishment order** — if
  `rls_item.safety_view.safety_pool < safety_target`, an order to top
  up the pool, sized at `safety_target - safety_pool`. At most one per
  item per iteration.

An `RlsItem` whose demand is fully met *and* whose safety pool is at
target contributes nothing to the candidate set.

### Decision window

The plant has ~40 machines; enumerating every decision at once
produces a huge candidate space and lets the planner pile work on
whichever machine happens to score lowest, even when leaving it
alone and using an idle machine would be better.

The decision window cuts this down. `state.window_end` is a moving
right-edge boundary on which decision points are eligible. A
candidate is in the window iff its `decision_point <= window_end`.
Decisions beyond the window are skipped for this iteration.

When committing a move whose `Job`(s) span a long time, the machine's
new `schedule_tail` is typically pushed past `window_end`, so that
machine drops out of the candidate pool until the window catches up.
This naturally distributes high-volume items across multiple machines
without any explicit "split this order across machines" enumerator:
once machine A takes a big chunk, the next iteration's candidates are
drawn from machines B, C, etc.

When the count of in-window candidates drops below a configured
threshold, `state.advance_window()` extends `window_end` forward to
admit more decisions. The window can be advanced repeatedly; the loop
terminates only when advancing yields no new productive candidates
across the full planning horizon.

### Move sizing

For each (machine, decision_point, item, order) tuple, the move's lbs
is:

```
effective_start = decision_point + carrying_avoidance_idle (work hours)
cap_end          = end of ISO week containing effective_start
producible_cap   = machine.producible_lbs_through(
                       item, end=cap_end, start=effective_start)
if producible_cap == 0:
    cap_end       = cap_end + 7 days   # bump to end of next ISO week
    producible_cap = machine.producible_lbs_through(
                       item, end=cap_end, start=effective_start)
move.lbs = min(
    order_lbs,    # remaining_lbs of the regular order, OR
                  # safety_target - safety_pool for the safety order
    producible_cap,
)
```

The default cap window is `[effective_start, end_of_iso_week)`. When
that window doesn't admit even a single full roll (e.g., the
schedule tail landed late on a Friday with most of the week's work
hours already consumed), the cap end is bumped forward by one week
so a tightly-loaded machine doesn't get artificially excluded from
contention. Without the bump, the enumerator would filter the
candidate out (`n_rolls <= 0`), and the loop would have to advance
the decision window past this machine entirely; with the bump, the
planner can commit a sensible chunk of next week's work on it.

`Machine.producible_lbs_through(item, end, start)` accounts for the
required preamble, any forced idle (below), mid-stream beam reloads,
and non-work hours via `workcal`. The legacy
`Machine.producible_lbs_in_week(item, year, week, start)` remains as
a thin wrapper for callers that want a single-ISO-week cap.

### Forced idle for carrying-cost avoidance (regular orders only)

A regular order whose `due_date - lead_time` is later than the decision
point would, if produced now, sit in inventory long enough to accrue
carrying cost. To avoid this, the enumerator forces:

```
target   = order.due_date - lead_time - state.carrying_avoidance_margin
idle_for = max(timedelta(0), target - decision_point)
```

so that production starts approximately at the target moment.
`carrying_avoidance_margin` (configurable on `State`, default 24h) is a
soft allowance below the strict no-carry moment: production may begin
one margin's worth of time earlier than necessary, trading a bounded
amount of carrying cost for less idle pressure. A margin of 0 enforces
strict no-carry; a larger margin trades carrying for tighter scheduling.

The idle itself costs `idle_time × hours` per the schedule penalty
above; the scorer trades "idle, then produce just-in-time" against "do
something else on this machine entirely".

If the required idle pushes production past the ISO week containing
`decision_point`, the cap collapses to 0 and the move is effectively
infeasible — that item simply isn't picked up this iteration and gets a
fresh shot once a later decision point brings it into range.

Safety replenishment orders never carry-avoidance-idle. Bucket-2 fills
don't accrue carrying cost in the demand view, so there's nothing to
avoid.

## Plant-wide coordination

Phase 2 adds three cross-candidate scoring concerns — priority
assignment, level-loading, and new-machine preference. All three score
each candidate against the others in the same iteration's pool (rather
than against one rls_item or machine in isolation), and all three feed
into a `ScoringContext` that the main loop builds once per iteration
and hands to `Costing.score_after_move`.

The related types and the priority-assignment function live in
`planners/infinite/coordination/`:

```
OrderKey
  item_id: str
  week_idx: int | None                                     # None ⇒ safety order

ScoringContext
  priorities: dict[OrderKey, int]                          # for priority assignment
  regular_orders_by_key: dict[OrderKey, RegularOrder]      # for priority cost — looks up due_date and remaining lbs
  earliest_dp_excluding: dict[str, datetime]               # machine_id → earliest candidate DP NOT on that machine; missing key ⇒ no other machine has a DP this iteration
  earliest_dp_time: datetime                               # for level-loading (global min DP)
  new_machine_avail: dict[Greige, bool]                    # for new-machine preference

assign_priorities(state: State) -> dict[OrderKey, int]
build_new_machine_avail(
    state: State, candidates: list[Move],
) -> dict[Greige, bool]
build_earliest_dp_excluding(
    state: State, candidates: list[Move],
) -> dict[str, datetime]
```

The submodule is the natural home for everything that *defines
relationships across the plant*: the `OrderKey` identity, the
plant-wide priority sort, the new-machine availability sweep, the
per-machine "earliest other DP" computation, and the bundle the
scorer reads from. Level-loading's only cross-candidate input is
`earliest_dp_time`, which the main loop computes inline as
`min(dp_time(c) for c in candidates)` when building the context.
New-machine preference's input is `new_machine_avail`, built by
`build_new_machine_avail`. Priority cost's cross-candidate inputs
are `regular_orders_by_key` (derived from `eligible_orders(state)`)
and `earliest_dp_excluding`, built by `build_earliest_dp_excluding`
— see the three sections below for the details.

## Priority assignment

The planner ranks every eligible order each iteration of the main
loop. The ranks themselves don't appear directly in any move's score;
instead, they identify which orders are *higher priority than* a
given move — the input to the priority cost (see "Priority cost"
below). Rank 1 is highest priority; for a move at rank `R`, every
order at rank `< R` is "higher priority" and contributes to the
move's priority cost if it's a regular order. The ranking function
is `assign_priorities` in `coordination/` (see above).

### Priority order

Three buckets, top to bottom:

1. **Urgent regulars** — `RegularOrder`s with `week_idx <=
   state.reference_week_idx`. Sorted by `(due_date asc,
   safety_pool / safety_target asc)` so an item that is already light
   on safety gets pulled forward when its order shares a due date with
   a safer item's.
2. **Safety orders** — sorted by `safety_pool / safety_target` ascending
   (item with the largest relative safety depletion first; this scales
   fairly across items whose `safety_target`s differ in absolute lbs).
3. **Future regulars** — `RegularOrder`s with `week_idx >
   state.reference_week_idx`. Same intra-bucket sort as urgent.

Placing safety in the middle reflects the design intent: we should not
discourage scheduling safety stock when only future regular demand
remains, because that would force the planner to schedule next-month
demand *this* week even though the safety pool is empty.
`reference_week_idx` is the lever that controls how far out a regular
order has to be before safety jumps the queue.

`safety_pool` and `safety_target` come from each `RlsItem`'s safety
view as currently committed — i.e., the final pool after all
already-registered jobs and on-hand are allocated through the buckets.
That's a coarse proxy for "how at-risk is this item" but it's a single
number per item that's already computed; we can refine later if real
data shows the planner mis-ordering things.

### Reference-week advance

`state.reference_week_idx` mirrors the decision window's advance
pattern. It starts at `1` — next week's demand should be in production
this week, so weeks 0 and 1 are urgent from the start — and advances in
steps of `state.reference_advance_amount` (default `1`) when the count
of items with at least one unmet `RegularOrder` at or before
`reference_week_idx` drops below `state.reference_threshold` (default
`5`). The main loop calls `state.advance_reference_week()` before the
window-advance step each iteration, advancing until the threshold is
met or `reference_week_idx` exceeds the latest order's `week_idx`.

The threshold keeps a healthy pool of urgent regulars available to
score against. With too few urgent items, safety stock would dominate
the score early and starve later regulars; with too many, safety stock
never gets a turn. Like `candidate_threshold`, this is a tuneable knob
expected to be refined against real-data behavior.

### Priority cost

The priority cost reframes "did the planner take a higher-priority
move first?" as an *opportunity cost*: every higher-priority regular
order the move skips is assumed to be deferred to either one day
past its `due_date` or the earliest non-self decision point in the
candidate pool — whichever is later — and is charged the standard
exponential lateness formula for that deferral.

For a move at rank `r = priorities[OrderKey(move.item.id,
move.week_idx)]`:

```
priority_cost(move) = w.priority × sum_{O ∈ higher_priority_regulars(r)}
                      predicted_lateness(O, move)

higher_priority_regulars(r):
  for K, rank in ctx.priorities.items():
    if rank < r and K in ctx.regular_orders_by_key:
      yield ctx.regular_orders_by_key[K]

predicted_lateness(O, move):
  other_dp = ctx.earliest_dp_excluding.get(
      move.machine_id, ctx.earliest_dp_time,
  )
  fill_time = max(O.due_date + 1 day, other_dp)
  days_late = (fill_time - O.due_date) in days
  return O.lbs × 2 ** days_late
```

Notes:

- **Regular orders only.** Safety orders contribute no priority cost
  for now — their "miss" cost is drainage, which has a different
  temporal shape that doesn't compose cleanly into this per-move sum.
  Future work may revisit.
- **Minimum one day late.** The `due_date + 1 day` floor reflects
  that even when another machine *is* available immediately, the
  schedule won't fill the order until at least one work day past due
  in practice (queue effects, hand-off). It also keeps `days_late ≥
  1`, so each skipped higher-priority regular contributes at least
  `2 × O.lbs × w.priority` to the move — a measurable floor.
- **Self-machine excluded.** `earliest_dp_excluding[machine_id]`
  drops every candidate on the move's own machine — that machine is
  committed to this move and can't simultaneously fill the higher-
  priority order. Missing key (no other machine has a DP this
  iteration) falls back to `earliest_dp_time` (the global min, which
  equals the move's own DP) — a slight underestimate that still
  yields a sensible floor via the `due_date + 1 day` clause.
- **Same shape as `w.lateness`.** `lbs × 2 ** days_late` matches the
  raw view's lateness formula, so the priority cost and the
  realized-lateness cost (`w.lateness × raw_view.lateness`) are
  directly comparable scalars once the relevant weights are applied.
  In practice `w.priority` should be tuned in roughly the same
  order of magnitude as `w.lateness` for the trade-off to behave
  intuitively.
- **Move identity.** `Move` already carries `week_idx`, so the cost
  layer forms `OrderKey(move.item.id, move.week_idx)` directly to
  look up the move's own rank. `week_idx = None` (safety move) is a
  valid key.
- **Heuristic.** The "deferred to one-day-past-due-or-next-DP"
  assumption is a proxy, not a prediction. Reality could fill the
  order earlier (via window advance bringing more candidates in)
  or later (via repeated commits piling up). Real-data tuning will
  show whether this proxy needs to evolve.

## Level-loading

For each in-iteration candidate, the level-loading cost is:

```
level_loading_cost(move) = machine.workcal.get_work_hours_between(
    earliest_dp_time, dp_time(move)
) × w.level_loading
```

where `dp_time(move)` is `state.machines[move.machine_id].schedule_tail`
when `move.start_at == 'schedule_tail'` and `.next_runout` otherwise —
the time the move's decision point falls at, *before* any carrying-
avoidance idle. The delta is measured in **work hours** so a weekend
gap between two DPs doesn't manufacture a level-loading difference
where there's no production difference to speak of.

The earliest DP in the candidate pool naturally pays zero. As soon as
a commit pushes that machine's `schedule_tail` past the others, the
remaining machines become the earliest and inherit the zero-cost slot
— so the level-loading penalty produces "spread work across machines"
behavior without any explicit "distribute" enumerator.

`earliest_dp_time` is `min(dp_time(c) for c in candidates)`, computed
in the main loop once after `enumerate_candidates` returns and packed
into the `ScoringContext`. Carrying-avoidance idle is **not** part of
`dp_time`: idle is already discouraged by `idle_time`, and rolling the
idle into level-loading would double-penalize moves that idle for
legitimate just-in-time reasons.

Like the other Phase 2 weights, `level_loading` is tuneable and
expected to be calibrated against real plant behavior.

## New-machine preference

The plant runs a mix of modern (`Machine.is_new == True`) and legacy
machines. The new ones knit faster and change over with a single
reconfigure step rather than the pattern-wheel rework legacy machines
require, so plant-wide throughput is highest when work is routed to a
new machine whenever one is eligible. The new-machine preference is a
per-move penalty that nudges the greedy loop toward the new fleet
without ruling legacy moves out — the latter still win whenever
demand-side or other schedule-side costs make them the better choice.

For each in-iteration candidate, the cost is:

```
old_machine_cost(move) = (
    w.old_machine
    if (ctx.new_machine_avail.get(move.item, False)
        and not state.machines[move.machine_id].is_new)
    else 0
)
```

`ctx.new_machine_avail` has an entry for every `Greige` that appears
in the iteration's candidate pool, mapping to `True` iff at least one
of that item's candidate moves targets a `Machine.is_new` machine.
Items with no eligible new-machine candidate map to `False`, so their
legacy candidates pay no penalty — the cost only fires when the
planner actually has a choice to skip.

`new_machine_avail` is produced by `build_new_machine_avail(state,
candidates)` in `planners/infinite/coordination/` — a single pass
over `candidates` that joins each `move.machine_id` with
`state.machines[...].is_new` and reduces per item. The main loop
calls it once after `enumerate_candidates` returns and packs the
result into the `ScoringContext` alongside `priorities` and
`earliest_dp_time`. The dict's lifetime is one iteration: committing
a move that exhausts the new-machine option for an item simply
leaves that item's entry as `False` in the next iteration's freshly-
built dict.

Like the other Phase 2 weights, `old_machine` is tuneable and expected
to be calibrated against real plant behavior — a small flat penalty
should be enough to break ties; a large one risks starving legacy
machines even when they're the right answer.

## End-to-end workflow

```
state = State(machines, rls_items, start_date)
costing = Costing(weights)
report = plan(state, costing)
# state has been mutated; report summarizes the result
```

The post-call `state` is the deliverable — machines now carry the
committed activities, rls_items now carry the registered jobs.

## CLI entry point

A `typer` app in `planners/infinite/run.py` runs the planner end-to-
end. The CLI takes one required positional argument — a path to a
**run-config JSON** — plus a set of optional override flags:

```
swmt-infinite-plan <config.json>
    [--start-date YYYY-MM-DD]
    [--products PATH] [--workcal PATH] [--machines PATH]
    [--demand PATH]   [--weights PATH]
    [--output-dir DIR]
    [--verbose]
```

### Run-config JSON

A top-level object with six required keys:

```
{
    "start_date": "YYYY-MM-DD",                # always inline
    "products":   <path-string | list of greige objects>,
    "workcal":    <path-string | workcal object>,
    "machines":   <path-string | list of machine objects>,
    "demand":     <path-string | list of demand objects>,
    "weights":    <path-string | weights object>
}
```

Every key except `start_date` can hold **either** a string (a path
to a JSON file with the same shape that the per-input loader would
read from disk) **or** the inline value (the object/list that the
file would have contained). The two forms are interchangeable and
can be mixed freely from one key to the next, so a run-config can:

- Reference external JSONs for fields that change frequently (e.g.,
  `demand` pulled fresh from the database each day).
- Inline fields that are stable or session-specific (e.g., a one-off
  `weights` variation for an experiment).
- Whatever combination is most convenient.

String paths in the config are resolved against the directory
holding the config file, so a whole input bundle can sit in one
folder and move together as a unit.

### CLI option overrides

Each input key has a matching CLI flag that, when provided,
overrides the config value for that key. The override always wins —
even if the config inlines the value. Options are truly optional;
the config alone suffices for a full run.

| Option         | Short | Value                                                       |
|---|---|---|
| `--start-date` | `-s`  | `YYYY-MM-DD` literal                                        |
| `--products`   | `-p`  | path to greige-styles JSON, *or* an inline JSON string      |
| `--workcal`    | `-c`  | path to workcal JSON, *or* an inline JSON string            |
| `--machines`   | `-m`  | path to machines JSON, *or* an inline JSON string           |
| `--demand`     | `-d`  | path to demand JSON, *or* an inline JSON string             |
| `--weights`    | `-w`  | path to weights JSON, *or* an inline JSON string            |
| `--output-dir` | `-o`  | output directory (defaults to cwd)                          |
| `--verbose`    | `-v`  | flag; emit a per-iteration TSV audit log alongside the XLSX |

Non-`start_date` override values are interpreted as **inline JSON**
when the first non-whitespace character is `{` or `[`, otherwise as
a **file path**. The inline form is primarily for testing —
realistic input objects are too big to comfortably paste on a
command line, but a one-off small `--weights '{"lateness": 10, ...}'`
is sometimes the quickest way to vary a single field during an
experiment. CLI paths are resolved against the shell's current
working directory (typer's default), not the config's directory.

### Resolution rule

For each input key, the value is determined in this order:

1. **CLI override** — when the matching flag is present:
   - If the value starts with `{` or `[` (after whitespace), parse
     it as inline JSON and build the input directly from that data.
   - Otherwise treat it as a path (relative to cwd) and load.
2. **Config string** — when the config's value is a string, treat
   it as a path relative to the config's directory and load.
3. **Config inline** — when the config's value is an object/list,
   build the input directly from that data.

Concretely each per-submodule loader exposes two entry points:

- `read_X(path, ...)` — file-based; opens the JSON and delegates.
- `X_from_dict(...)` / `X_from_list(...)` — in-memory; takes the
  already-parsed value (`weights_from_dict` is the existing example).

`run()` picks the right one per key based on the resolved value's
shape. Inline `workcal` objects whose `holidays` field is a string
resolve that nested path against the config's directory (the only
sub-path inside a config-inlined value the planner is aware of).
Inline `workcal` from a CLI override has no enclosing directory to
resolve against; its `holidays` must also be inlined.

### Output

The CLI writes a single Excel workbook at
`<output_dir>/knit_plan_<YYYYMMDD>.xlsx` where the YYYYMMDD is the
resolved `start_date`. Four sheets:

- `schedule` — multi-indexed by `(machine, activity_id)`, every
  activity across all machines.
- `production` — multi-indexed by `(item, job_id)`, one row per
  committed `Job`: its `total_rolls`, `total_lbs`, and `completion`
  (when the job finishes — its last roll's `completion_time`).
- `unmet_demand` — flat `(item, week_idx, unmet_lbs)`, one row per
  `safety_view.orders` entry with `remaining_lbs > 0`.
- `late_orders` — flat `(item, week_idx, late_lbs, late_fill_date)`,
  one row per `PlanReport.late_orders` entry. `late_fill_date`
  reports when the order will finish filling (the latest contributing
  chunk's arrival time), even if some demand remains unmet.

When `--verbose` is set, an additional set of TSV files is written
in a `verbose_<YYYYMMDD>/` subdirectory next to the workbook — see
"Verbose iteration log" below.

See `report.py` for the per-sheet layouts.

### Verbose iteration log

The `--verbose` flag turns on a per-iteration audit log written as
ten TSV files in a `<output_dir>/verbose_<YYYYMMDD>/`
subdirectory next to the workbook. The files form a small joinable
schema: the headline `iteration_log.tsv` holds one row per scored
candidate keyed by `move_id`, which joins to companion tables that
store the full weighted cost breakdown, per-item demand-cost deltas,
per-item priority-cost attribution, the candidate's full activity
plan, and the production it generates (jobs and their rolls).

| File                   | Grain                                                  | Joined to iteration_log via            |
|---|---|---|
| `iteration_log.tsv`    | One row per scored candidate                           | (primary key: `move_id`)               |
| `cost_detail.tsv`      | One row per scored candidate                           | `move_id`                              |
| `lateness_detail.tsv`  | One row per (candidate, item) with a non-zero lateness delta vs the iteration's baseline | `cost_detail.lateness_detail_id` |
| `drainage_detail.tsv`  | One row per (candidate, item) with a non-zero drainage delta vs the iteration's baseline | `cost_detail.drainage_detail_id` |
| `carrying_detail.tsv`  | One row per (candidate, item) with a non-zero carrying delta vs the iteration's baseline | `cost_detail.carrying_detail_id` |
| `excess_detail.tsv`    | One row per (candidate, item) with a non-zero excess delta vs the iteration's baseline   | `cost_detail.excess_detail_id`   |
| `priority_detail.tsv`  | One row per (candidate, item) with at least one higher-priority regular order being skipped by this move | `cost_detail.priority_detail_id` |
| `schedule_detail.tsv`  | One row per Activity in `move.plan.activities`         | `move_id`                              |
| `job_detail.tsv`       | One row per `Job` in `move.plan.jobs`                  | `move_id`                              |
| `roll_detail.tsv`      | One row per `Roll` in a job's `rolls`                  | `job_detail.job_id` (and `move_id`)    |

For each main-loop iteration the CLI records up to 16 candidates —
grouped by item, with the top 4 items (ranked by their
lowest-scoring candidate) each contributing their top 4
lowest-scoring candidates. The committed move is always the first
row of the first item. Operators understand *why* the planner chose
a particular move by reading `iteration_log.tsv` (committed row
next to its same-item siblings and runner-up items), expanding any
row into its weighted cost breakdown by joining `cost_detail.tsv`
on `move_id`, drilling into per-item *deltas* for any of the four demand-side
costs (how each affected item's contribution would change from the
iteration's baseline) by joining the appropriate `*_detail.tsv` on
the matching `*_detail_id`, drilling into the *absolute* per-item
attribution of priority cost (which urgent orders this move would
defer) by joining `priority_detail.tsv` on `priority_detail_id`,
and inspecting the candidate's full activity plan by joining
`schedule_detail.tsv` on `move_id`, and its production output by
joining `job_detail.tsv` on `move_id` and `roll_detail.tsv` on
`job_id`.

#### `iteration_log.tsv` columns (in order)

| Column            | Type         | Notes                                                                                          |
|---|---|---|
| `iteration`       | int          | 0-indexed main-loop iteration.                                                                 |
| `role`            | str          | `committed` or `rejected`.                                                                     |
| `score_rank`      | int          | Rank across all scored candidates in the iteration (0 = lowest score; the committed move is always 0). |
| `item_score_rank` | int          | Rank within this item's candidates (0 = lowest-scoring same-item candidate; the committed move is always 0). |
| `item_id`         | str          | The move's target item.                                                                        |
| `target_type`     | str          | `regular` or `safety` — which kind of order the move was placed against.                       |
| `target_week`     | int \| blank | Week index (0–3) for a regular order; blank cell for a safety order.                           |
| `machine_id`      | str          | The move's machine.                                                                            |
| `machine_is_new`  | bool         | `state.machines[machine_id].is_new` — useful for explaining the `old_machine` cost.            |
| `start_at`        | str          | `schedule_tail` or `next_runout`.                                                               |
| `idle_hours`      | float        | `move.idle_for` expressed in hours (carrying-avoidance idle).                                  |
| `total_score`     | float        | The candidate's `score_after_move(state, move, ctx)`; equals `cost_detail[move_id].total`.     |
| `move_id`         | int          | This candidate's id; foreign key into `cost_detail.tsv`, `schedule_detail.tsv`, and `job_detail.tsv`. |

#### `cost_detail.tsv` columns (in order)

| Column                | Type         | Notes                                                                                          |
|---|---|---|
| `move_id`             | int          | Primary key; matches `iteration_log.move_id`.                                                  |
| `lateness`            | float        | Weighted total: `w.lateness × sum_i raw_view_i.lateness` for the post-commit state.            |
| `drainage`            | float        | Weighted total from per-item `safety_view.drainage` (summed).                                  |
| `carrying`            | float        | Weighted total from per-item `safety_view.carrying` (summed).                                  |
| `excess`              | float        | Weighted total from per-item `safety_view.excess` (summed).                                    |
| `tape_out_single`     | float        | Weighted count of `TapeOut(bars='top'|'btm')` in the affected machine's combined activities.   |
| `tape_out_both`       | float        | Weighted count of `TapeOut(bars='both')`.                                                      |
| `style_change`        | float        | Weighted count of `StyleChange` (new-machine changeover).                                      |
| `runner_change`       | float        | Weighted count of `RunnerChange` (legacy, within pattern family).                              |
| `pattern_change`      | float        | Weighted count of `PatternChange` (legacy, cross pattern family).                              |
| `idle_time`           | float        | Weighted sum of `Idle` work-hour durations.                                                    |
| `waste_lbs`           | float        | Weighted sum of `Waste.lbs` (discarded yarn) in the affected machine's combined activities.    |
| `priority`            | float        | Cross-cutting: `w.priority × sum_O O.lbs × 2^days_late(O)` over higher-priority regular orders — see "Priority cost". |
| `level_loading`       | float        | Cross-cutting: `work_hours_delta × w.level_loading` per "Level-loading".                       |
| `old_machine`         | float        | Cross-cutting: `w.old_machine` when applicable, else 0; see "New-machine preference".          |
| `total`               | float        | Sum of the fourteen weighted components above; equals `iteration_log.total_score`.               |
| `lateness_detail_id`  | int \| blank | Foreign key into `lateness_detail.tsv`. Blank when no item has a non-zero `lateness` delta from baseline. |
| `drainage_detail_id`  | int \| blank | Foreign key into `drainage_detail.tsv`. Blank when no item has a non-zero `drainage` delta from baseline. |
| `carrying_detail_id`  | int \| blank | Foreign key into `carrying_detail.tsv`. Blank when no item has a non-zero `carrying` delta from baseline. |
| `excess_detail_id`    | int \| blank | Foreign key into `excess_detail.tsv`. Blank when no item has a non-zero `excess` delta from baseline.    |
| `priority_detail_id`  | int \| blank | Foreign key into `priority_detail.tsv`. Blank when no higher-priority order is being skipped (priority cost == 0). |

#### Demand-cost detail TSVs — `lateness_detail.tsv` shown; same shape for `drainage`, `carrying`, `excess`

| Column                | Type  | Notes                                                                                          |
|---|---|---|
| `lateness_detail_id`  | int   | Groups all rows from one candidate's lateness deltas.                                          |
| `item_id`             | str   | The RlsItem whose lateness contribution would change if this candidate were committed.         |
| `lateness_delta`      | float | Weighted per-item delta vs the iteration's baseline: `w.lateness × (after_move.raw_view.lateness - baseline.raw_view.lateness)`. Sign reflects whether the candidate would worsen (>0) or improve (<0) this item's lateness. |

`drainage_detail.tsv`, `carrying_detail.tsv`, and
`excess_detail.tsv` use the analogous `<cost>_detail_id` and
`<cost>_delta` column names. Rows are emitted only for items with
a non-zero delta in the corresponding cost — in practice the move
only changes its target item's demand-side costs, so each detail
group typically has at most one row (and is omitted entirely when
the candidate would not move that cost). A candidate whose only
effect is on, say, drainage will produce a single row in
`drainage_detail.tsv` and no rows in the other three demand-detail
tables (with the matching `*_detail_id` cells in `cost_detail.tsv`
left blank).

#### `priority_detail.tsv` columns (in order)

| Column                | Type  | Notes                                                                                          |
|---|---|---|
| `priority_detail_id`  | int   | Groups all rows from one candidate's priority breakdown.                                       |
| `item_id`             | str   | Owner of the higher-priority deferred regular order. Appears at most once per `priority_detail_id` — each item contributes at most one regular order to the candidate pool per iteration. |
| `week_idx`            | int   | Week (0..3) of the deferred order.                                                             |
| `remaining_lbs`       | float | Unfulfilled lbs of the deferred order at the time of evaluation (`O.remaining_lbs`).           |
| `priority`            | float | *Absolute* weighted contribution: `w.priority × remaining_lbs × 2^days_late(O, move)`. Sums across rows in the group equal `cost_detail.priority`. |

`priority_detail.tsv` is structurally analogous to the four
demand-cost detail tables but holds **absolute** weighted
contributions, not deltas. Priority cost is a per-move quantity
that doesn't exist in the baseline state, so there's nothing to
subtract from — the absolute value is the most informative thing to
log. The `week_idx` and `remaining_lbs` columns turn each row into
a full picture of *what* is being deferred, not just *how much*
that costs, so an operator scanning `priority_detail.tsv` for an
iteration where an urgent order didn't get committed sees which
competing items pulled the planner's attention elsewhere, which
weeks of theirs are at stake, and how much demand is sitting
unfulfilled.

Multiple rows per candidate are common here (unlike the demand-cost
detail tables): any item whose own deferred regular order is
higher-priority than this move's order contributes a row. Rows are
emitted only when the per-item weighted contribution is non-zero,
so an item present in `ctx.priorities` but ranked below the move
produces no row.

#### `schedule_detail.tsv` columns (in order)

| Column         | Type     | Notes                                                                                          |
|---|---|---|
| `move_id`      | int      | Groups all rows from one candidate's `move.plan.activities`.                                   |
| `activity_id`  | str      | The `Activity`'s own id (`Activity.id`); unique across the run.                                 |
| `machine_id`   | str      | The candidate's machine.                                                                       |
| `start`        | datetime | Activity start.                                                                                |
| `end`          | datetime | Activity end.                                                                                  |
| `description`  | str      | Human-readable rendering of the activity and its key fields (e.g. `"Knit item=ABC lbs=1400"`, `"TapeOut both"`, `"PatternChange ABC→XYZ"`, `"Doff"`, `"Threading both"`). |

#### `job_detail.tsv` columns (in order)

| Column         | Type     | Notes                                                                                          |
|---|---|---|
| `move_id`      | int      | Foreign key into `iteration_log.tsv`; groups all jobs from one candidate (a move yields 1 or 2 jobs). |
| `job_id`       | str      | The `Job`'s own id (`Job.id`); groups this job's `roll_detail` rows.                            |
| `item_id`      | str      | `job.item.id`.                                                                                 |
| `total_rolls`  | int      | `job.total_rolls`.                                                                             |
| `total_lbs`    | float    | `job.total_lbs`.                                                                               |

#### `roll_detail.tsv` columns (in order)

| Column            | Type     | Notes                                                                                          |
|---|---|---|
| `move_id`         | int      | Foreign key into `iteration_log.tsv`.                                                          |
| `job_id`          | str      | Foreign key into `job_detail.tsv` (the owning `Job`).                                          |
| `roll_idx`        | int      | Unique id for this roll, auto-incremented across the verbose run (`Roll` has no id of its own). |
| `lbs`             | float    | `roll.lbs`.                                                                                    |
| `completion_time` | datetime | `roll.completion_time` — when the roll is ready to ship.                                        |

#### Row ordering and id semantics

Rows in `iteration_log.tsv` are emitted in main-loop order, so a
top-to-bottom read is a chronological decision trace. Within an
iteration block, rows are grouped by item (top-ranked item first,
ranked by the item's lowest-scoring candidate); within each item
group `item_score_rank` orders the rows (0 first). The committed
row is therefore the very first row of each iteration block.

The companion tables are emitted in `move_id` order —
i.e., parallel to the candidate sequence in `iteration_log.tsv`, so
each TSV reads top-to-bottom in the same chronological direction.
The auto-incremented counters (`move_id`, `roll_idx`, and the five
`*_detail_id`s, bundled in `IterLogCounters`) restart at 1 at the
beginning of each verbose run and are independent of one another.
`move_id` is 1:1 with scored candidates and is the single handle the
cost, schedule, and job detail tables all join on — this refactor
collapsed the former separate `cost_id` and `sched_id` (always 1:1
with each other) into it. `activity_id` and `job_id` are not
counters — they are the record-owned ids `Activity.id` and `Job.id`;
`roll_detail` joins to `job_detail` on `job_id` directly. `roll_idx`
is a counter only because `Roll` has no id of its own. Cross-file
joins are by id only.

#### Internal flow

At the start of each main-loop iteration in verbose mode, the loop
captures a baseline via `Costing.cost_breakdown(state)`; for each
scored candidate it then calls
`Costing.cost_breakdown_after_move(state, move, ctx)` and derives
the per-item deltas for the four demand-cost detail tables by
subtracting `baseline.{cost}_by_item` from the candidate's
`{cost}_by_item` (zero-delta items dropped). Priority detail rows
come directly from `after_move.priority_by_item` (absolute, no
subtraction); the `job_detail` and `roll_detail` rows come straight
from `move.plan.jobs` and each job's `rolls`, needing no baseline.
The resulting records flow through `plan(...,
verbose=True)` into the ten detail tuples on `PlanReport`; the
CLI converts each tuple into the corresponding TSV. With
`--verbose` off, the loop never calls `cost_breakdown` or
`cost_breakdown_after_move`, and all ten `PlanReport` detail
tuples stay `None` — the verbose path adds work only when
explicitly requested.

### Why a config file (with overrides)

The CLI lives in `planners/infinite/` because it's the highest-level
artifact that touches every submodule. Per-submodule reading stays
in the submodules so the planner doesn't grow a spreadsheet
dependency it doesn't need, and per-input format evolution is local
to the owner of that input.

The config-plus-overrides shape supports two normal workflows:

- **Production runs** — one stable config per shift / week, all
  inputs cleanly pinned in one file; the user just points at it.
- **Experiments / re-runs** — same config plus an override or two
  (e.g., `--weights variant.json` to try a different cost setup
  without editing the canonical config).

It's also intentional groundwork for a future user-friendlier shell
(dashboard for editing weights and triggering runs) — the JSON-only
inputs make that wrapper straightforward to build.

## Phases

Like the `schedule/` rollout, the planner is built up in phases. Each
phase produces a working end-to-end planner; later phases improve
optimization breadth and quality rather than adding new capabilities.

### Phase 1 — basic greedy with decision window

The minimum viable planner. Implements the full candidate-enumeration
structure described above, including the decision window — which is
what gives Phase 1 multi-machine parallelism for high-volume items
without any explicit "split" enumerator.

- `state/`: `State` data class with machines, rls_items, start_date,
  `window_end`, `commit_move`, and `advance_window`. No undo / no
  snapshots — the loop is monotonic.
- `costing/`: `CostWeights` with the four per-item demand weights, the
  three per-occurrence changeover weights, the `idle_time` weight, and the
  per-lb `waste_lbs` weight. `score` is the weighted sum of per-item
  `CostComponents` plus the per-machine schedule penalties (changeover
  counts, idle hours, and discarded-waste lbs). No cross-cutting aggregates
  yet.
- `loop/`: greedy `plan` per "Candidate enumeration" above. Each
  iteration enumerates the (machine × decision-point × order)
  Cartesian product filtered by the window, derives `lbs`, `start_at`,
  and `idle_for` for each `Move`, scores via `score_after_move`, and
  commits the lowest-scoring candidate. Advances the window when
  in-window candidate count falls below threshold.
- Termination: enumerator returns no candidates even after the window
  has been advanced past the planning horizon. No "best must improve"
  check — committing demand matters more than minimizing score at any
  single step.

Delivers: a feasible end-to-end planner that respects the
carrying-cost / idle trade-off and naturally spreads high-volume items
across multiple machines via the window mechanism.

### Phase 2 — cross-cutting cost aggregates

Adds the priority-cost, level-loading, and new-machine-preference
layers — the first three cross-cutting costs in scope. See "Plant-wide
coordination" above for all three mechanisms.

- New `planners/infinite/coordination/` submodule exposing `OrderKey`,
  `ScoringContext`, `assign_priorities(state) -> dict[OrderKey, int]`,
  `build_new_machine_avail(state, candidates) -> dict[Greige, bool]`,
  and `build_earliest_dp_excluding(state, candidates) -> dict[str,
  datetime]`. `ScoringContext` bundles `priorities`,
  `regular_orders_by_key`, `earliest_dp_excluding`,
  `earliest_dp_time`, and `new_machine_avail`, and is passed to
  `Costing.score` / `Costing.score_after_move` each iteration.
- Extend `State` with `reference_week_idx` (default `1`),
  `reference_advance_amount` (default `1`), `reference_threshold`
  (default `5`), and `advance_reference_week()`.
- Extend `Move` with a `week_idx: int | None` field so the cost layer
  can derive the order key.
- Extend `CostWeights` with `priority`, `level_loading`, and
  `old_machine`, and change `Costing.score` /
  `Costing.score_after_move` to take a `ScoringContext` and add
  the priority cost (per-move sum of predicted-lateness lb-days
  across higher-priority regular orders × `w.priority`),
  `work_hours_delta × w.level_loading`, and `old_machine_cost` per
  move.
- Extend the main loop with a reference-week advance step before the
  window-advance step each iteration, plus a `ctx = ScoringContext(...)`
  build step before scoring (calling `build_new_machine_avail` and
  `build_earliest_dp_excluding`, computing `earliest_dp_time` from
  the candidate pool, and collecting `regular_orders_by_key` from
  `eligible_orders(state)`).

Avoids three Phase-1 failure modes: the greedy loop filling a high-
weight component (e.g., a near-due regular order on week 0) on an
arbitrary machine while a more urgent order on a more-depleted item
sits behind it in the candidate pool, the loop piling work onto
whichever machine happens to score lowest in isolation while other
machines remain idle, and the loop routing work to legacy machines
even when a faster new machine was an eligible candidate for the same
item.

Future cross-cutting cost terms — once real-data behavior tells us
priority + level-loading + new-machine preference isn't enough — may
include plant-wide total excess, per-machine utilization imbalance,
and aggregate changeover time.

### Phase 3 — verbose iteration audit log

A decision-trace output that explains *why* each committed move was
chosen over the alternatives. No change to the planner's behavior
or output schedule — only an additional set of TSVs produced when
the CLI's `--verbose` flag is set. See "Verbose iteration log"
under the CLI section for the file layout.

- Extend `Costing` with two methods: `cost_breakdown(state) ->
  CostBreakdown` (current-state baseline; per-move cross-cutting
  costs are 0 and `priority_by_item` is empty) and
  `cost_breakdown_after_move(state, move, ctx) -> CostBreakdown`
  (same total as `score_after_move`, broken into the fourteen
  weighted scalars). Both return CostBreakdowns whose
  `lateness_by_item`, `drainage_by_item`, `carrying_by_item`, and
  `excess_by_item` dicts hold *absolute* weighted per-item
  contributions for the state they describe, and whose
  `priority_by_item` dict (value type `PriorityContribution`)
  carries each deferred order's `week_idx`, `remaining_lbs`, and
  weighted contribution.
- Extend `plan` with a `verbose: bool = False` keyword and ten
  internal record accumulators (one per output table). When
  `verbose=True`, the loop calls `Costing.cost_breakdown(state)`
  once at the start of each iteration to capture a baseline
  breakdown, then for each of up to 16 candidates — the top 4
  items (ranked by each item's lowest-scoring candidate) each
  contributing up to 4 of their lowest-scoring candidates — emits
  an `IterationLogRecord`, a `CostDetailRecord`, one row per
  *non-zero-delta* item in each of the four demand-cost detail
  tables (delta computed as `after_move.{cost}_by_item -
  baseline.{cost}_by_item`), one row per non-zero entry in
  `after_move.priority_by_item` for the priority detail table
  (absolute values, no subtraction), one `ScheduleDetailRecord`
  per `Activity` in `move.plan.activities`, one `JobDetailRecord`
  per `Job` in `move.plan.jobs`, and one `RollDetailRecord` per
  `Roll` in each job's `rolls`. Cross-table ids — `move_id`,
  `roll_idx`, and the five `*_detail_id`s — are auto-incremented
  integer counters owned by the loop; `activity_id` and `job_id` are
  the record-owned `Activity.id` and `Job.id`; a
  `*_detail_id` is `None` when the corresponding cost has no
  contributing rows (no non-zero deltas for the demand-side costs;
  no higher-priority skipped orders for priority). The committed
  move is always the first record of the iteration's batch.
- Extend `PlanReport` with ten `tuple[..., ...] | None` fields:
  `iteration_log`, `cost_detail`, `lateness_detail`,
  `drainage_detail`, `carrying_detail`, `excess_detail`,
  `priority_detail`, `schedule_detail`, `job_detail`, `roll_detail`.
  All ten are `None` when `verbose=False` and populated otherwise.
- Add `--verbose` / `-v` to the CLI; when set, the CLI calls
  `plan(..., verbose=True)` and writes one TSV per `PlanReport`
  detail tuple into `<output_dir>/verbose_<YYYYMMDD>/` next to the
  XLSX.

Delivers: an audit trail that turns "the greedy committed X" into
"the greedy committed X because its lateness was Y vs the next
candidate's Z, and its priority rank was W". Used for diagnosis and
weight tuning — not part of the operator-facing deliverables when
`--verbose` is off.

### Phase 4 — local search post-pass

- After Phase 1–3 produce a greedy baseline, run a local-search pass
  that tries swap/replace operations on already-committed moves to
  reduce the total score.
- Requires either reversible state updates (undo) or operating on
  state snapshots. Probably introduces a `state.snapshot()` method or
  a copy-on-write variant of `commit_move`.

## Out of scope

- **Downstream supply chain.** Dyeing and finishing are handled by
  future separate planners. This planner stops at greige production.
- **Input construction.** Building `Machine` / `RlsItem` instances from
  spreadsheets or other operational inputs is a separate concern; the
  planner consumes them ready-made.
- **Output formatting.** The planner returns data (a `PlanReport` and a
  mutated `State`); rendering for human consumption is downstream.
- **Mid-plan demand changes.** The planner assumes demand and on-hand
  inventory are fixed for the duration of a single `plan` call.
- **Multi-week look-ahead beyond greedy.** Phase 4's local search is
  the deepest non-greedy optimization in scope; full
  dynamic-programming or solver-based optimization is out.
