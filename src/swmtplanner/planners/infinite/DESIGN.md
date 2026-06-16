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
  score_after_move(state, move, ctx, debuglog=None) -> float   # post-commit score, pure; with a DebugLog, also records the per-component cost breakdown into the log
```

`ctx` is a `ScoringContext` (see "Plant-wide coordination" below) that
bundles the priorities dict, the earliest DP time, and the
new-machine-availability dict so the scorer can
compute the cross-cutting cost contributions without re-running the
priority sort or the candidate-wide min-DP scan. Only
`score_after_move` consumes `ctx`; `score(state)` reports the per-item
+ per-machine portion of the score for a state with no in-iteration
move under consideration (e.g., the post-loop final score in
`PlanReport.total_score`).

`score_after_move` is the loop's hot path. It computes what `score`
would return if `move` were committed, without actually mutating
anything — built on `RlsItem.cost_if(jobs)` for the demand-side
contributions, on inspecting `move.plan.activities` for the schedule-side
changeover contributions, and on the `ctx` lookups for the cross-
cutting contributions.

`score_after_move` also accepts an optional `debuglog` keyword: when a
`DebugLog` is passed, it records the move's full per-component cost
breakdown (and the supporting cost-detail leaf rows) into the log as it
scores, then returns the same scalar total. When absent (the hot path)
nothing is logged. The debug/audit log lives in the standalone
top-level `swmtplanner.debuglog` module — see `debuglog/DESIGN.md` for
its table schema and the planner's population flow.

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
  order_remaining_lbs: float  # unfulfilled lbs on the targeted order at enumeration
                          # (the eligible RegularOrder.lbs / SafetyOrder.lbs); for the debug log
  plan: ProductionPlan    # cached output of machine.plan_production

plan(state, costing, debuglog=None) -> PlanReport
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
  rls_items: dict[str, RlsItem]                 # greige_id -> RlsItem (the input demand + its post-plan views, incl. each safety view's roll_order_links); feeds the `demand` and `xref` sheets
  # final cost picture
  total_score: float
  cost_components_by_item: dict[str, CostComponents]
  # what couldn't be placed
  unmet_lbs_by_item_week: dict[tuple[str, int], float]
  # which orders ship late and when they finish filling
  late_orders: tuple[RawOrder, ...]
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

The per-iteration decision trail — *why* each move was chosen over
the alternatives — is no longer reconstructed onto `PlanReport`.
Instead, `plan` accepts an optional `debuglog` (a `DebugLog`); when
present, the loop takes a debug scoring path that scores and ranks the
full candidate list and writes each candidate's iteration-log row and
cost breakdown into the log as it runs, then commits the lowest-cost
move exactly as the hot path does. When absent (the default), the loop
scores via the scalar `score_after_move` and nothing is logged. The
log object, its tables, and the population flow are owned by the
standalone `swmtplanner.debuglog` module — see `debuglog/DESIGN.md`.

## Candidate enumeration

Each iteration of the main loop builds a fixed set of candidate `Move`s
from the current `State`. The candidates are the Cartesian product of
three axes — machine × decision point × eligible order — and each tuple
becomes one `Move` with derived `lbs`, `start_at`, and `idle_for`.

One pairing is dropped: a `next_runout` decision point is never paired with an
order for the machine's **current** item. `next_runout` means "finish the
current item, then change over to a different one," so with no item change
`Machine.plan_production` rejects it (the same-item guard in the schedule
design); the machine's `schedule_tail` point already covers continuing the
current item.

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

Each eligible order also carries the **id of the demand-layer order it
corresponds to**, captured straight off the demand object at construction (so
the id is never rebuilt from parts): the `SafetyAwareOrder.id`
(`P{week_idx}@{item.id}`) for a regular order, the safety view's `Safety.id`
(`S@{item.id}`) for a safety order. The enumerator threads this id into
`Machine.plan_production` as `tgt_order`, so the resulting `Job` records which
order the planner was targeting (the *actually-filled* order is resolved later
in the demand layer — see the schedule and demand designs).

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

A top-level object with six required keys, plus an optional `database`
block:

```
{
    "start_date": "YYYY-MM-DD",                # always inline
    "products":   <path-string | list of greige objects>,
    "workcal":    <path-string | workcal object>,
    "machines":   <path-string | list of machine objects>,
    "demand":     <path-string | list of demand objects>,
    "weights":    <path-string | weights object>,
    "database":   <db-config object>           # optional; only used with --verbose
}
```

Every required key except `start_date` can hold **either** a string (a path
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

#### The `database` block (optional)

Connection settings for the MySQL store the verbose `DebugLog` is persisted to
(and that the `knit-debug` investigation app reads from). **Only consulted when
`--verbose` is set**; a non-verbose run ignores it, and it may be omitted
entirely. Shared connection fields plus a `writer` and a `reader` credential
sub-block — two MySQL roles so the dashboard is read-only at the grant level
(writer: `SELECT,INSERT,UPDATE`; reader: `SELECT`). The planner persists as the
**writer**; the app reads as the **reader**.

```
"database": {
    "host": "127.0.0.1",
    "port": 3306,
    "name": "swmtplanner",
    "writer": { "user": "swmt_writer", "password": null },   # null → SWMT_DB_WRITER_PASSWORD
    "reader": { "user": "swmt_reader", "password": null }     # null → SWMT_DB_READER_PASSWORD
}
```

Any field may be left out of the file and supplied by environment variable
(`SWMT_DB_HOST` / `SWMT_DB_PORT` / `SWMT_DB_NAME`; `SWMT_DB_WRITER_USER` /
`SWMT_DB_WRITER_PASSWORD`; `SWMT_DB_READER_USER` / `SWMT_DB_READER_PASSWORD`),
with the environment winning — so a committed config can hold non-secret
defaults and leave passwords to the environment. Unlike the six input keys, the
`database` block is **always inline** (not a path-string) and has no CLI
override flag; it lives in the main config file (shared with the app). The full
schema and persistence/investigation design are in
`planners/infinite/dashboard/DESIGN.md`.

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
| `--db-conn`    | `-b`  | override the `database` block — path to a JSON file, *or* an inline JSON string |
| `--label`      | `-l`  | this run's `label` (required with `--verbose`; ignored otherwise) |
| `--output-dir` | `-o`  | output directory (defaults to cwd)                          |
| `--verbose`    | `-v`  | flag; persist the run's `DebugLog` to MySQL (see below + `dashboard/DESIGN.md`) |

**Verbose mode requires a label and notes.** A `--verbose` run is persisted as
a labelled, annotated run, so before any work begins the CLI fails fast if
`--label` is missing, and collects the run's **notes interactively**: it opens
`vi` on a fresh temp file (`temp.txt`, or the first `tempN.txt` not already
present in the cwd), waits for the user to write and quit, takes the file's
contents as the notes, and deletes the file. The notes must contain
non-whitespace text — the CLI exits with an error otherwise. `--db-conn`
overrides the config's `database` block (e.g. to point a one-off run at a
different server); absent both, a verbose run reports that nothing was persisted.

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
resolved `start_date`. Six sheets:

- `demand` — the original input demand, one row per order across all
  `rls_items`, **regular and safety**. Built from `PlanReport.rls_items`.
  Columns:
  - `order_id` — the demand-layer order id (`P{week_idx}@{item}` for a
    regular order, `S@{item}` for a safety order)
  - `item` — greige id
  - `due_date` — the order's due date; **blank for safety orders** (a
    safety replenishment has no due date)
  - `demand` — the original ordered quantity: a regular order's weekly
    `qty_lbs`, a safety order's `safety_target`
  - `covered_on_hand` — lbs of this order met by the item's **initial
    on-hand inventory**, from `RlsItem.on_hand_coverage` (the jobs=`[]`
    allocation captured at construction — see the demand design)
  - `remaining` — `demand - covered_on_hand`, the demand production must
    still place after initial inventory
- `schedule` — multi-indexed by `(machine, activity_id)`, every
  activity across all machines.
- `production` — multi-indexed by `(item, job_id)`, one row per
  committed `Job`: its `total_rolls`, `total_lbs`, `completion`
  (when the job finishes — its last roll's `completion_time`), and
  `tgt_order` — the id of the order the job was raised to target
  (`Job.tgt_order`), **blank** when the job targeted no specific order
  (e.g. a `'next_runout'` run-up job).
- `xref` — the roll/knit/order cross-reference: a flat table, **one row
  per `Knit` activity** across every committed job (run-up and
  production). Built from `PlanReport.rls_items` and the jobs they carry.
  Columns:
  - `item` — greige id
  - `job_id` — the id of the job the knit's roll belongs to
  - `roll_idx` — the roll's 0-based index within its job (a `Roll` has no
    id of its own, so `(job_id, roll_idx)` identifies it)
  - `roll_completion` — the roll's `completion_time`
  - `knit_id` — the `Knit` activity's id
  - `knit_lbs` — the lbs that `Knit` wound (a roll straddling a beam swap
    has two knit rows whose `knit_lbs` sum to the roll's lbs)
  - `order_id` — the order this roll **actually fills**, looked up from the
    item's `safety_view.roll_order_links` by roll identity; **blank** when
    the roll reached no order (its lbs went entirely to excess). Distinct
    from the job's `tgt_order` on the `production` sheet (what the job
    *aimed* at) — `xref` shows the resolved fill.

  Construction: for each item, build a `{roll: order_id}` map (keyed by
  roll identity) from that item's `safety_view.roll_order_links`; then walk
  `jobs_by_item` → `Job.rolls` (enumerated for `roll_idx`) → `Roll.knits`,
  emitting one row per knit and looking up the roll's order in the map.
  Rows ordered by `(item, job completion, roll_idx, knit order within the
  roll)`. Flat table (no MultiIndex) — `item`/`job_id`/`roll_idx` are plain
  columns so each knit's full provenance reads on its own row.
- `unmet_demand` — flat `(item, week_idx, unmet_lbs)`, one row per
  `safety_view.orders` entry with `remaining_lbs > 0`.
- `late_orders` — flat `(item, week_idx, late_lbs, late_fill_date)`,
  one row per `PlanReport.late_orders` entry. `late_fill_date`
  reports when the order will finish filling (the latest contributing
  chunk's arrival time), even if some demand remains unmet.

When `--verbose` is set, the planner additionally builds and populates
an in-memory `DebugLog` audit trail during the run — see "Verbose
audit log" below.

See `report.py` for the per-sheet layouts.

### Verbose audit log

The `--verbose` flag turns on a per-iteration decision trail that
explains *why* each committed move was chosen over the alternatives.
It is built into a `DebugLog` — a standalone, generic, config-driven
table container in the top-level `swmtplanner.debuglog` module —
threaded into `plan(..., debuglog=...)` and populated live as the loop
runs (iteration log, per-component cost summary, the cost-detail leaf
tables, the per-`Knit` production ledger) plus a post-loop copy of the
`demand` / `unmet_demand` tables. The log's table schema, keys/links, and
population flow are specified in `swmtplanner/debuglog/DESIGN.md`. With
`--verbose` off, no log is built and the loop stays entirely on the scalar hot
path.

When `--verbose` is on and a `database` block is configured, the populated log
is persisted to a local **MySQL** store (run-tagged by an auto-incremented
`run_id`) and investigated through a **PyQt6** desktop app — both owned by
`planners/infinite/dashboard/` (see its DESIGN.md), not the planner core.

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

### Phase 3 — verbose audit log (the `debuglog` module)

A decision-trace audit that explains *why* each committed move was
chosen over the alternatives. No change to the planner's behavior or
output schedule — it is built only when the CLI's `--verbose` flag is
set. Realized as the standalone top-level `swmtplanner.debuglog`
module rather than as `PlanReport` fields, so the audit machinery
stays decoupled from the planner's headline output.

- `DebugLog` is a generic, config-driven container of named tables
  (no hard-coded schema). The planner declares the tables it needs and
  threads the log through the methods that populate it.
- `Costing.score_after_move` and `plan` take an optional `debuglog`
  keyword; when present, the loop scores and ranks the full candidate
  list and the methods write their rows into the log live (iteration
  log, per-component cost summary, the cost-detail leaf tables, the
  per-`Knit` production ledger), with a post-loop copy of the
  `demand` / `unmet_demand` tables. When absent, the hot path runs
  unchanged and nothing is logged.
- The CLI's `--verbose` / `-v` flag builds the `DebugLog` and passes
  it to `plan(..., debuglog=...)`. Persisting the populated log to a
  local MySQL store and investigating it through a PyQt6 app are the
  final pieces, owned by `planners/infinite/dashboard/`.

The full table schema, keys/links, and population flow live in
`swmtplanner/debuglog/DESIGN.md`; the persistence + investigation design
lives in `planners/infinite/dashboard/DESIGN.md`. Delivers an audit trail
that turns
"the greedy committed X" into "the greedy committed X because its
lateness was Y vs the next candidate's Z, and its priority rank was
W" — for diagnosis and weight tuning, not an operator-facing
deliverable when `--verbose` is off.

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
