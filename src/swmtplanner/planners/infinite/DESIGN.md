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
   - One `family_change` per `StyleChange(is_family_change=True)`.
   - `idle_time × hours` per `Idle` activity, where `hours` is the
     activity's work-hour duration. Discourages letting a machine sit
     unstaffed longer than necessary — including the carrying-avoidance
     idles inserted by the candidate enumerator (see below).

   The time these activities consume is *already* reflected in
   downstream activity start times. These weights are extra
   discouragement on top of that — "we'd rather not do this even if
   the time fits".

3. **Cross-cutting aggregates** (Phase 2+). Penalties that compare each
   candidate against the others in the same iteration's pool — costs no
   single item's or machine's view can capture alone. Phase 2 adds two:
   - **Priority cost** — `rank × w.priority` per move, where `rank` is
     the move's order's position in a global priority ordering. Higher-
     priority orders rank lower, so the greedy min-score loop naturally
     prefers them.
   - **Level-loading cost** — `work_hours_delta × w.level_loading` per
     move, where the delta is from the earliest decision point in the
     candidate pool. Encourages spreading work across machines instead
     of piling onto the one that happens to score lowest in isolation.

   See "Plant-wide coordination" below for both. Future cross-cutting
   terms — once real-data behavior tells us priority + level-loading
   isn't enough — may include plant-wide total excess, per-machine
   utilization imbalance, and aggregate changeover time.

```
CostWeights
  # per-item demand weights (Phase 1)
  lateness, drainage, carrying, excess: float
  # per-machine schedule weights (Phase 1)
  tape_out_single, tape_out_both, family_change: float   # per occurrence
  idle_time: float                                       # per work-hour
  # cross-cutting weights (Phase 2)
  priority: float                                        # per rank step
  level_loading: float                                   # per work-hour delta from earliest DP

Costing
  score(state, ctx) -> float                             # current state's score
  score_after_move(state, move, ctx) -> float            # post-commit score, pure
```

`ctx` is a `ScoringContext` (see "Plant-wide coordination" below) that
bundles the priorities dict and the earliest DP time so the scorer can
compute the cross-cutting cost contributions without re-running the
priority sort or the candidate-wide min-DP scan.

`score_after_move` is the loop's hot path. It computes what `score`
would return if `move` were committed, without actually mutating
anything — built on `RlsItem.cost_if(jobs)` for the demand-side
contributions, on inspecting `move.plan` for the schedule-side
changeover contributions, and on the `ctx` lookups for the cross-
cutting contributions.

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
  start_at: Literal['next_job_end', 'next_runout']
  idle_for: timedelta
  week_idx: int | None    # which order this move addresses; None for safety (Phase 2)
  plan: list[Activity]    # cached output of machine.plan_production

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
```

The full schedules also remain on the `Machine` instances inside
`state`; the report bundles them into a self-contained snapshot so
callers can persist or render without holding the mutable `State`
around.

## Candidate enumeration

Each iteration of the main loop builds a fixed set of candidate `Move`s
from the current `State`. The candidates are the Cartesian product of
three axes — machine × decision point × eligible order — and each tuple
becomes one `Move` with derived `lbs`, `start_at`, and `idle_for`.

### Per-machine decision points

Every machine has up to two natural points in time at which new
production could begin:

- **`next_job_end`** — the schedule tail (`current_status.as_of`).
  Starts production sooner but pays the full changeover preamble
  (`TapeOut` + `BeamLoad`s + `StyleChange` as needed).
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
new `next_job_end` is typically pushed past `window_end`, so that
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
move.lbs = min(
    order_lbs,    # remaining_lbs of the regular order, OR
                  # safety_target - safety_pool for the safety order
    machine.producible_lbs_in_week(item, year, week,
                                    start=decision_point),
)
```

where `(year, week)` is the ISO week containing `decision_point`. The
cap is computed from `decision_point` through the end of that week,
accounting for the required preamble, any forced idle (below), and beam
reloads. `Machine.producible_lbs_in_week` was extended with the optional
`start` parameter specifically to support this query.

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

Phase 2 adds two cross-candidate scoring concerns — priority assignment
and level-loading. Both score each candidate against the others in the
same iteration's pool (rather than against one rls_item or machine in
isolation), and both feed into a `ScoringContext` that the main loop
builds once per iteration and hands to `Costing.score_after_move`.

The related types and the priority-assignment function live in
`planners/infinite/coordination/`:

```
OrderKey
  item_id: str
  week_idx: int | None              # None ⇒ safety order

ScoringContext
  priorities: dict[OrderKey, int]   # for priority assignment
  earliest_dp_time: datetime        # for level-loading

assign_priorities(state: State) -> dict[OrderKey, int]
```

The submodule is the natural home for everything that *defines
relationships across the plant*: the `OrderKey` identity, the
plant-wide priority sort, and the bundle the scorer reads from. Level-
loading's only cross-candidate input is `earliest_dp_time`, which the
main loop computes inline as `min(dp_time(c) for c in candidates)`
when building the context — see the two sections below for the
details.

## Priority assignment

The planner ranks every eligible order each iteration of the main
loop and adds `rank × w.priority` to each `Move`'s score. Rank 1 is
highest priority (lowest cost contribution); lower-ranked candidates
lose to their higher-ranked siblings unless some other cost component
shifts the balance. The ranking function is `assign_priorities` in
`coordination/` (see above).

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

### Cost mapping

Each move's priority cost is:

```
priority_cost(move) = priorities[OrderKey(move.item.id, move.week_idx)]
                      × w.priority
```

with `move.week_idx = None` for safety orders. `Move` carries
`week_idx` directly so the cost layer can form the key without re-
running eligibility.

## Level-loading

For each in-iteration candidate, the level-loading cost is:

```
level_loading_cost(move) = machine.workcal.get_work_hours_between(
    earliest_dp_time, dp_time(move)
) × w.level_loading
```

where `dp_time(move)` is `state.machines[move.machine_id].next_job_end`
when `move.start_at == 'next_job_end'` and `.next_runout` otherwise —
the time the move's decision point falls at, *before* any carrying-
avoidance idle. The delta is measured in **work hours** so a weekend
gap between two DPs doesn't manufacture a level-loading difference
where there's no production difference to speak of.

The earliest DP in the candidate pool naturally pays zero. As soon as
a commit pushes that machine's `next_job_end` past the others, the
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

A `typer` app in `planners/infinite/cli.py` runs the planner end-to-
end. Invocation shape:

```
swmt-infinite-plan \
    --products path/to/greige.xlsx \
    --demand path/to/demand.xlsx \
    --machines path/to/machines.xlsx \
    --weights path/to/weights.json \
    --start-date 2026-05-18 \
    --workcal path/to/workcal.json \
    --output path/to/plan.xlsx
```

The CLI is glue: it reads each input via the appropriate submodule's
reader (`products.read_greige_styles`, `demand.read_rls_items`,
`schedule.read_machines`), reads weights and workcal config, builds
the `State` and `Costing`, calls `plan(state, costing)`, and writes
the resulting `PlanReport` to a single Excel workbook.

Output workbook layout:

- **One sheet per machine** — chronological activity list with
  start, end, duration, activity type, item, and lbs columns.
- **One sheet per rls_item** — chronological job list with start,
  end, machine, and lbs, plus a header section showing the item's
  cost-component totals and any unmet weekly demand.
- **A summary sheet** — total score, plant-wide cost-component
  totals, an unmet-demand table, and the cost-weight config used
  (for traceability).

The CLI lives in `planners/infinite/` because it's the highest-level
artifact that touches every submodule. Per-submodule reading stays in
the submodules so the planner doesn't grow a spreadsheet dependency
it doesn't need, and so per-input format evolution is local to the
owner of that input.

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
  three per-occurrence changeover weights, and the `idle_time` weight.
  `score` is the weighted sum of per-item `CostComponents` plus the
  per-machine schedule penalties (changeover counts + idle hours). No
  cross-cutting aggregates yet.
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

Adds the priority-cost and level-loading layers — the first two cross-
cutting costs in scope. See "Plant-wide coordination" above for both
mechanisms.

- New `planners/infinite/coordination/` submodule exposing `OrderKey`,
  `ScoringContext`, and `assign_priorities(state) -> dict[OrderKey, int]`.
  `ScoringContext` bundles `priorities` and `earliest_dp_time` and is
  passed to `Costing.score` / `Costing.score_after_move` each iteration.
- Extend `State` with `reference_week_idx` (default `1`),
  `reference_advance_amount` (default `1`), `reference_threshold`
  (default `5`), and `advance_reference_week()`.
- Extend `Move` with a `week_idx: int | None` field so the cost layer
  can derive the order key.
- Extend `CostWeights` with `priority` and `level_loading`, and change
  `Costing.score` / `Costing.score_after_move` to take a
  `ScoringContext` and add `rank × w.priority` plus
  `work_hours_delta × w.level_loading` per move.
- Extend the main loop with a reference-week advance step before the
  window-advance step each iteration, plus a `ctx = ScoringContext(...)`
  build step before scoring.

Avoids two Phase-1 failure modes: the greedy loop filling a high-weight
component (e.g., a near-due regular order on week 0) on an arbitrary
machine while a more urgent order on a more-depleted item sits behind
it in the candidate pool, and the loop piling work onto whichever
machine happens to score lowest in isolation while other machines
remain idle.

Future cross-cutting cost terms — once real-data behavior tells us
priority + level-loading isn't enough — may include plant-wide total
excess, per-machine utilization imbalance, and aggregate changeover
time.

### Phase 3 — local search post-pass

- After Phase 1–2 produce a greedy baseline, run a local-search pass
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
- **Multi-week look-ahead beyond greedy.** Phase 3's local search is
  the deepest non-greedy optimization in scope; full
  dynamic-programming or solver-based optimization is out.
