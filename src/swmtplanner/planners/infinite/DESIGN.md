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

Three modules under `infinite/`. Each has a single, well-defined
responsibility, and the main loop only knows the surface of each rather
than the internals.

### `state/`

The plant-wide state. A bag of data plus its mutation operations.

```
State
  machines: dict[str, Machine]
  rls_items: dict[str, RlsItem]
  start_date: datetime
  window_end: datetime          # right edge of the decision window
  # query helpers as needed (e.g. eligible machines for an item,
  # remaining unmet demand for an rls_item/week, etc.)
  commit_move(move) -> None
  advance_window() -> None       # extends window_end forward
```

`State` is a thin container. Its primary purpose is to let any function
take `state` as a single argument rather than threading a half-dozen
dicts through call signatures. It owns two mutation operations:

- `commit_move` applies a chosen `Move` by calling the underlying
  `Machine` and `RlsItem` methods in lockstep.
- `advance_window` extends `window_end` forward so additional decisions
  become eligible (see "Decision window" below).

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

3. **Cross-cutting aggregates** (Phase 2+). Penalties on plant-wide
   state metrics that can't be captured by any single item's view in
   isolation — e.g. overproducing one item while another goes unmet, or
   piling work onto one machine while others sit idle. Likely terms:
   - Plant-wide total excess across all items.
   - Machine-utilization imbalance (variance across machines).
   - Aggregate changeover time.

   The exact set evolves with the phasing (see below).

```
CostWeights
  # per-item demand weights (Phase 1)
  lateness, drainage, carrying, excess: float
  # per-machine schedule weights (Phase 1)
  tape_out_single, tape_out_both, family_change: float   # per occurrence
  idle_time: float                                       # per work-hour
  # plant-wide aggregate weights (Phase 2+)
  total_excess, util_imbalance, changeover_total: float

Costing
  score(state) -> float                          # current state's score
  score_after_move(state, move) -> float         # post-commit score, pure
```

`score_after_move` is the loop's hot path. It computes what `score`
would return if `move` were committed, without actually mutating
anything — built on `RlsItem.cost_if(jobs)` for the demand-side
contributions and on inspecting `move.plan` for the schedule-side
changeover contributions.

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
  plan: list[Activity]    # cached output of machine.plan_production

plan(state, costing) -> PlanReport
```

`plan` is the entrypoint. It iterates:

1. **Enumerate** candidate `Move`s from the current state, filtered by
   the decision window — see "Candidate enumeration" below.
2. **If empty**, `state.advance_window()` and re-enumerate. If the
   window has reached the planning horizon and still empty, terminate.
3. **Score** each candidate via `costing.score_after_move(state, move)`.
4. **Commit** the lowest-scoring move via `state.commit_move(move)`. If
   no candidate would improve the score, terminate.
5. **Maintain** the window: if the in-window candidate count fell below
   the configured threshold after the commit, `state.advance_window()`.
6. **Repeat.**

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

## End-to-end workflow

```
state = State(machines, rls_items, start_date)
costing = Costing(weights)
report = plan(state, costing)
# state has been mutated; report summarizes the result
```

The post-call `state` is the deliverable — machines now carry the
committed activities, rls_items now carry the registered jobs.

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
  has been advanced past the planning horizon, or the best candidate
  doesn't decrease the score.

Delivers: a feasible end-to-end planner that respects the
carrying-cost / idle trade-off and naturally spreads high-volume items
across multiple machines via the window mechanism.

### Phase 2 — cross-cutting cost aggregates

- Extend `CostWeights` and `Costing.score` with plant-wide penalty
  terms (total excess, util imbalance, changeover total).
- Avoids globally-bad-but-locally-fine decisions that Phase 1 can't
  see (e.g., committing every cycle to one machine while others idle).

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
