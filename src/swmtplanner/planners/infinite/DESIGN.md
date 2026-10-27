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
  `RlsItem.start_date`. It is when the machines' starting state was
  identified.
- `change_date: datetime` (>= `start_date`, default equal to it) — when
  the plant can first change a machine over. Time passes between the
  scheduler running, the plan reaching the floor, and a changeover
  actually being possible; meanwhile every machine keeps running what it
  is running. The loader (`run.load_inputs`) runs each machine up to
  `change_date` on its current item before the planner sees it —
  `Machine.run_until`: the roll in progress plus every whole roll that
  starts before `change_date`, committed like any move (machine schedule,
  the item's demand, the inventory); a machine with nothing to run idles
  to `change_date` — so every schedule tail is at or past it and no
  changeover can be placed earlier. A machine on an item it **cannot
  run** (not in the style's machine list — see "An item the machine
  cannot run" in `schedule/DESIGN.md`) has nothing to run: it idles to
  `change_date`, then stands at its tail with no run-up and no fill,
  open to every item it can run (its one decision point is
  `schedule_tail`; the current item is never a candidate on it), and a
  move taking it elsewhere pays no recovery cost (see "Recovery cost").
  The load echoes each such machine.
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
  inventory: dict[BeamSetDesc, list[BeamSet]]
                                    # the plant's beam-set stock, keyed by
                                    # physical description (see
                                    # schedule/DESIGN.md "Beam-set inventory");
                                    # empty when no beam_sets input was given
  capacity: ChangeoverCapacity      # the plant's rations per day: changes of
                                    # any kind, tape-outs, pattern changes (see
                                    # schedule/DESIGN.md "Changeover capacity");
                                    # unlimited when no changeover_capacity
                                    # input was given
  window_end: datetime              # right edge of the decision window
  reference_week_idx: int           # right edge of the priority "urgent" bucket
  # tuneable thresholds and step sizes (window_advance_amount,
  # carrying_avoidance_margin, candidate_threshold,
  # reference_advance_amount, reference_threshold,
  # planning_horizon_buffer, frozen_window, eoq_threshold_rolls,
  # eoq_batch_rolls)
  commit_move(move) -> None
  advance_window() -> None          # extends window_end forward
  advance_reference_week() -> None  # extends reference_week_idx forward
```

`State` is a thin container. Its primary purpose is to let any function
take `state` as a single argument rather than threading a half-dozen
dicts through call signatures. It owns three mutation operations:

- `commit_move` applies a chosen `Move` by calling the underlying
  `Machine` (`commit_plan`) and `RlsItem` methods in lockstep — when the
  plan carries a `replaced_job` (the machine's last job recreated with the
  changeover tape-out appended, see `schedule/DESIGN.md` "Job activities"),
  the demand item unregisters the old copy and registers the new one so both
  sides hold the same `Job` — then applies the plan's inventory effect: the sets in `plan.beam_sets_taken` leave `inventory`
  (matched by set id under their physical description) and those in
  `plan.beam_sets_returned` — taped-out sets carrying their remaining lbs
  and the tape-out's end as `avail_date` — are added back. Candidate plans
  are enumerated against the same `inventory` and never mutate it, so only
  the committed move changes the stock. Likewise the plan's
  `capacity_taken` slots are booked on `capacity`; candidates are planned
  against the committed bookings and never book.
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
   - One `tape_out_both` per `TapeOut(bars='both')`. An `Unhang` (a
     never-threaded set taken off again) costs nothing.
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
   - **Priority cost** — for each move, sum the *predicted lateness*
     of every higher-priority regular order under the assumption that,
     if the planner doesn't address them now, each ships one week
     after the earliest decision point on a different machine. Each
     order's predicted lateness has the same shape as realized
     lateness (share of the gross order × the week-linear-then-doubling
     factor). Weighted by `w.priority`. The result is an opportunity
     cost: the higher-priority orders being deferred by this move. See
     "Priority cost" below for the formula.
   - **Level-loading cost** — `work_hours_delta × w.level_loading` per
     move, where the delta is from the earliest decision point in the
     candidate pool. Encourages spreading work across machines instead
     of piling onto the one that happens to score lowest in isolation.
   - **Old-machine cost** — `w.old_machine` per move that targets a
     legacy machine (`not Machine.is_new`) when at least one of the
     same item's candidates targets a new machine. New machines are
     faster and easier to change over, so we'd rather route work to
     them whenever the candidate pool offers the choice.
   - **Restart cost** — `w.restart` per move that targets a **standing**
     machine (`Machine.standing`: stood down by the plant and not yet
     given a job by this plan — see "Standing machines" in
     `schedule/DESIGN.md`). The plant stands a machine down because it
     is not needed; waking it costs crew time and is only worth it when
     the demand cannot be met on time on the machines already running.
     The weight is in the lateness units, so a restart is chosen exactly
     when it saves more predicted lateness than it costs. It is charged
     on the first move only — once the machine has a job it is running,
     and later moves on it pay nothing here — so a woken machine is kept
     busy rather than woken again. A standing machine never used stays
     out of every output (it has no work, like an idle machine).

   - **Recovery cost** — a move that takes a machine out of the set
     able to make some items cheaply (a tape-out loses the old yarn's
     items, an old machine's pattern change loses the old family's) is
     charged the predicted lateness of the open demand on those items
     that the remaining cheap machines cannot cover on time, at the fill
     time it would take to get the items back on a machine — weighted
     across the recovery routes the plant has available (style change,
     runner change, pattern change, tape-out) and their slot waits.
     Weighted by `w.recovery`. See "Changeover capacity" below.

   See "Plant-wide coordination" and "Changeover capacity" below. Future
   cross-cutting terms — once real-data behavior tells us these aren't
   enough — may include plant-wide total excess, per-machine utilization
   imbalance, and aggregate changeover time.

```
CostWeights
  # per-item demand weights (Phase 1)
  lateness: float                                        # per whole order per day late (share of the gross order × days shape)
  drainage, carrying, excess: float                      # per lb-day / per lb
  # per-machine schedule weights (Phase 1)
  tape_out_single, tape_out_both: float                  # per occurrence
  style_change, runner_change, pattern_change: float     # per changeover, by type
  idle_time: float                                       # per work-hour
  waste_lbs: float                                       # per lb of discarded Waste
  # cross-cutting weights (Phase 2)
  priority: float                                        # per whole higher-priority order per predicted day late (same units as lateness)
  level_loading: float                                   # per work-hour delta from earliest DP
  old_machine: float                                     # per move on a legacy machine when a new one is candidate-available
  restart: float                                         # per move that wakes a standing machine (its first job); lateness units
  # changeover-capacity weight
  recovery: float                                        # per whole stranded order per predicted day late (same units as lateness)

Costing
  score(state) -> float                                  # current state's score (no ctx — cross-cutting costs are per-move)
  score_after_move(state, move, ctx, debuglog=None) -> float   # post-commit score, pure; with a DebugLog, also records the per-component cost breakdown into the log
```

`ctx` is a `ScoringContext` (see "Plant-wide coordination" below) that
bundles the priorities dict, the earliest DP time, and the
new-machine-availability dict so the scorer can compute the
cross-cutting cost contributions without re-running the priority sort
or the candidate-wide min-DP scan. Only `score_after_move` consumes
`ctx`; `score(state)` reports the per-item + per-machine portion of the
score for a state with no in-iteration move under consideration (e.g.,
the post-loop final score in `PlanReport.total_score`).

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
Holds the eligible-order types (`RegularOrder`, `SafetyOrder`), the
order identity (`OrderKey`), the scoring bundle (`ScoringContext`), and
the priority ranker (`assign_priorities`). The costing layer consumes a
`ScoringContext` but doesn't own its construction — `coordination/`
does, so the priority sort and the shape of the cross-candidate inputs
can evolve without touching `costing/` or `loop/`. See "Plant-wide
coordination" below for the mechanism.

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

0. **Start from the prior plan** (once, before the loop, when the run
   has one — see "Sticking to the prior plan"): recommit every prior job
   inside the frozen window whose order is still urgent and open, so the
   loop plans only what is left.
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
  # the prior plan's jobs, each with its fate in this run (empty without
  # a prior plan) — see "Sticking to the prior plan"
  prior: tuple[PriorCommit, ...]
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

## Sticking to the prior plan

A plan the floor has been following should not be thrown away by the
next run: a machine the previous plan had changing over on Wednesday
should still change over on Wednesday, not be re-decided on Monday to
something that scores a little better. The run is given the previous
plan and starts from it: every prior job inside the **frozen window**
whose order is **still urgent and open** is recommitted before the loop
plans anything, and the loop then schedules only the demand that is
left. Nothing else is held — a prior job for a later week, for an order
since filled, or beyond the window is left to the loop to re-decide.

**The prior plan is a retimed plan.** The config names the previous
plan's schedule JSON (`prior_plan`) **after** `plan retime` has realigned
it to today's status — rolls already doffed consumed, early changes and
wrong-style machines dealt with, the remaining jobs re-timed from the
status. Realigning is the retimer's whole job and the planner does none
of it: it reads the file as it is (the schedule-JSON job reader the
retimer uses, `planners/retime.prior_jobs`), so the usual morning is
`plan retime` on yesterday's plan, then `plan infinite` with the retimed
plan as `prior_plan`. The result is, per machine, the prior jobs in order
with their item, roll count, target order, due date and start time. A job
with no target order (a run-up job) is never recommitted — the load's own
run-up covers the current item. The planner's config and the retime's
should describe the same morning (same dates, machines file and
inventory), or the prior jobs' times will not line up with the machines
the planner loads.

**Which prior jobs are kept.** A prior job is kept when the order it was
raised for is still **urgent and open** in this run: the item's regular
order with the job's `due_date` has `week_idx <= reference_week_idx`
(this week's and next week's demand, at the reference week's starting
value of 1) and remaining lbs. Last week's plan was made for last week's
demand; what it decided for the demand that is now due is kept, and
everything else — a job for a later week, a safety job, an order since
filled — is re-decided by the loop, which sees today's demand. How many
of the kept changes the floor can take in a day is bounded separately,
by the change ration (see "Changeover capacity"): a kept job whose change
the day cannot take waits for the next slot, knitting the current item
meanwhile where the plant still wants it, exactly as a loop move does.

Demand moves between weeks from one run to the next, so the matching is
by **item and due date**, not order id: order ids count weeks from each
run's `start_date`, so `P3@AU8154` last week is `P2@AU8154` this week,
while the due date is the same date in both. The schedule JSON carries
each job's `due_date` for this.

**The frozen window** bounds how far into the prior plan the pre-pass
looks: `state.frozen_window`, a duration in the `state` block, keeps
only prior jobs whose aligned **start** is before `start_date +
frozen_window`. A job starting at or past that is left `open` with the
note `outside the frozen window` — the loop re-decides it. Left unset
(`None`, the default) the window is unbounded and every needed prior job
is recommitted.

**The pre-pass.** Before the loop's first iteration, the prior jobs are
walked in **prior start order across machines** (so an earlier tape-out
claims its ration slot before a later one, as the prior plan laid them
out). Each is a `PriorCommit`:

```
PriorCommit
  machine: str
  prior_job: str           # the job's id in the prior plan
  item: str
  rolls: int               # whole rolls left on it after alignment
  order: str | None        # the prior plan's target order id
  due_date: datetime | None
  start: datetime          # its aligned start
  status: 'open' | 'consumed' | 'dropped'
  job_id: str | None       # the job this run committed for it
  note: str                # why it was dropped, or left open

State.prior: dict[str, list[PriorCommit]]     # per machine, in start order
```

For each, in that order:

- a job whose order is urgent and open is planned with
  `plan_production(item, rolls × tgt_wt, 'schedule_tail', tgt_order=<the
  matched order's id>, prior_job=<its prior id>, fill=<the current item's
  fill>)` against the inventory and the rations — the changeover, if the
  machine is on another item, happens at its schedule tail, as the retime
  replays it, and waits for a slot (filled with the current item, see
  "Filling a slot wait") when the day's are taken — committed through
  `State.commit_move`, and marked `consumed` with the new job's id (the
  new `Job` records the prior job it came from, `Job.prior_job`, written
  to the schedule JSON as `prior_job`). The prior roll count is kept
  whatever the demand now is — the job was sized when the floor started
  following it — and the demand it produces flows to the item's orders
  as any job's does, so a later prior job for the same order may find it
  filled;
- a job whose order is open but past the reference week is left `open`
  with the note `not urgent`; one whose order has no remaining lbs is
  `dropped (order filled)`; a safety job, one whose order the run cannot
  match by item and due date, or one for an item the run does not have
  is `dropped (no such order)`; one starting at or past the frozen
  window's end is left `open` with the note `outside the frozen window`;
  one whose item the machine can no longer run, or that
  `plan_production` refuses, is `dropped` with the reason. Every job left
  `open` is the loop's to re-decide.

Because the walk is in start order, a machine's prior sequence inside
the window is kept whole except where a job is dropped, in which case
the jobs after it move up to the tail. The loop then runs exactly as
before on the state the pre-pass left — the recommitted jobs are ordinary
committed jobs to it. The decision window and reference week are
untouched by the pre-pass.

**Outputs.** `PlanReport.prior` lists every prior job with its fate;
the xlsx gains a `prior_jobs` sheet (machine, prior_job, item, rolls,
order, due_date, start, status, job_id, note) and the CLI prints the
counts after the score. The debug log records nothing for the pre-pass —
its `iteration_log` rows are the scored iterations.

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
target_lbs = safety_target - safety_pool          # safety order
target_lbs = max(order_lbs, open_demand(item))    # regular order
    # order_lbs         = remaining_lbs of the targeted (earliest unmet) order
    # open_demand(item) = Σ remaining_lbs over the item's unmet regular
    #   orders with week_idx <= state.reference_week_idx
if regular and unique_setup(item) and target_lbs <= eoq_threshold_rolls × tgt_wt:
    target_lbs = batched_demand(item)             # economic order quantity, below
    move.lbs   = target_lbs                       # the batch is not capped at the week
else:
    move.lbs   = min(target_lbs, producible_cap)
```

#### Open-demand sizing

A regular move is sized to the item's whole open demand — every unmet
regular order through the reference week, the same "should be in
production now" bucket that makes an order urgent in `eligible_orders`
— rather than to the one order it targets. This holds whether the move
changes the machine's item or continues it; a safety order is its gap.
The targeted order (`tgt_order`, the earliest unmet week) is unchanged;
the demand views allocate the extra rolls to the later weeks in their
normal way, so carrying and excess still apply to them, and the
carrying-avoidance idle is still driven by the earliest order's due
date.

The reason is the setup. A tape-out or pattern change is charged once,
at the move that makes it; nothing in the score remembers it afterwards
and nothing values leaving the machine on the yarn. Sized to one order,
a move could be a single roll: on the 2026-09-30 inputs I4, I9 and K10
were each taped both bars for one 740-lb roll of week-0 AU4583 on
10-01, sat idle, and were taped again for AU7389H on 10-09 while
10,360 lbs of AU4583 for weeks 1 and 2 went unmade. Sized to the open
demand, the same move is a week's worth of AU4583 (the cap still
applies), the setup is scored against the run it actually buys, and the
machine stays on the yarn until the backlog it was set up for is
covered.

Continuations are sized the same way on purpose. A first cut sized only
the changeover moves and left a continuation at its single order, and
that mismatch cost yarn the other way: K10 started on AU6563 with
1,480 lbs of week-0 demand, made one roll, and then its 740-lb AU6563
continuation lost to a 2,960-lb AU4583 changeover on the same machine;
the last AU6563 roll was bought with a tape-out on I3 two weeks later.
With both sized to open demand the comparison is like for like, and a
machine already on the right yarn brings its whole backlog to it. Where
an item has only one week open the two sizes coincide, so this does
not push machines further ahead than before.

The demand bucket is the reference week, not the decision window: the
decision window is about which machines are free (time), the reference
week is about which demand the planner considers due (weeks), and it is
the latter that answers "how much of this item should this machine
run". A future regular (past the reference week) is sized to itself.

#### Economic order quantity for unique setups

Open-demand sizing still leaves one case where the setup is bought for
almost nothing: an item that needs a roll or two a week and is the
**only item that runs its yarn**. Nothing else can follow it on the
machine, so every week's roll or two costs a tape-out in and a tape-out
out. For such an item the planner batches the demand instead — an
economic order quantity — and sizes the move to several weeks at once.

An item's **setup** is the pair of physical beam-set descriptions its
bars call for (`BeamSetDesc.physical` of its top and bottom labels —
split lease aside, denier by class). The setup is **unique** when no
other item among the run's demand items (`state.rls_items`) has the same
pair; items without demand this run are not counted, since nothing will
be scheduled on their yarn anyway. `coordination.unique_setups(state)`
is the set of such item ids, built once per enumeration.

When a regular move's open-demand size for a unique-setup item is
**`eoq_threshold_rolls` rolls or fewer** (3 by default), the move is
sized to `batched_demand(item)` instead: the item's unmet regular
orders in week order — the open ones and then the later weeks — summed
until the total reaches **`eoq_batch_rolls` rolls** (4 by default) or
every order on the schedule has been pulled in. The batch is then
rounded down to whole rolls as any move is, so an item with 2½ rolls of
demand in total still makes 2. A batched move is **not capped at the
week**: the cap exists to keep ordinary moves to a week's worth so the
decision window can spread work, and a batch is by construction more
than a week's worth — cutting it back would defeat the batching. Both
thresholds are `State` tunables settable in the config's `state` block;
`eoq_threshold_rolls = 0` switches batching off, since no move is sized
at zero rolls.

Everything else about the move is unchanged: it targets the earliest
unmet order (`tgt_order`, `week_idx`), the carrying-avoidance idle is
driven by that order's due date, and the demand views allocate the
later rolls to the later weeks, where carrying and excess apply to them
as usual — the batch is scored against the carrying it causes, which is
the right trade against the tape-outs it saves. Safety orders are never
batched (a safety gap is already the whole top-up), and an item whose
setup another item shares is sized as before, since the machine can
change to the other item without a tape-out.

The default cap window is `[effective_start, end_of_iso_week)`. When
fewer than **three work days** of that week remain at `effective_start`
— fewer than `3 × workcal.hours_per_day` work hours, 72 on the plant's
round-the-clock weekday calendar — the cap end is the end of the
*following* ISO week instead. A machine whose tail lands on a Wednesday
afternoon would otherwise be offered only the two days left in the week,
and the planner was seen putting a single roll of a very large order at
the end of such a machine's week; sized through the next week, the move
is a run worth setting up for. (The rule replaces a narrower one that
extended the window only when not even one roll fit; that case still
extends, since under three days remain whenever one roll does not fit.)

`Machine.producible_lbs_through(item, end, start)` accounts for the
required preamble, any forced idle (below), mid-stream beam reloads,
and non-work hours via `workcal`. The legacy
`Machine.producible_lbs_in_week(item, year, week, start)` remains as
a thin wrapper for callers that want a single-ISO-week cap.

### Filling a slot wait

A move that changes a machine's item may have to wait for a ration slot
(see "Changeover capacity"). Rather than idle the machine, every such
candidate is planned with a **fill**, `plan_production(..., fill=Fill(rolls,
tgt_order))`: the preamble may knit whole rolls of the machine's current
item while it waits, as far as the plant still wants that item
(`schedule/DESIGN.md`, "Filling a slot wait"). The fill is sized to the
current item's **whole open demand** — the remaining lbs of all its
regular orders, any week, plus its safety gap when the pool is below
target — rounded **up** to whole rolls, so the machine runs until that
demand is completely filled or the slot comes, whichever is first; its
`tgt_order` is the item's earliest open regular order, else its safety
order. A move that continues the current item, a machine whose current
item has no open demand, a machine with no current item, and a machine
on an item it cannot run (`Machine.can_run_current_item` False — it has
nothing to fill with) get no fill (`None`). The producible cap is laid out with the same fill, so the move
is sized to what is left of the week after it.

The fill is part of the candidate: its rolls are a job of the current
item in `plan.jobs`, so the score sees their production (lateness and
carrying on the current item's orders) and the shorter idle together with
the change itself, and a machine that would have to wait is compared on
what it would actually do. There is no fill-less twin of the candidate:
idling a machine that holds yarn for an item the plant wants is never
the better plan. The pre-pass plans prior jobs with the same fill.

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

RegularOrder
  item, week_idx, due_date, order_id
  lbs: float                                               # remaining (unmet) lbs of the week
  gross_lbs: float                                         # the week's demand as loaded, before on-hand is netted — the priority cost values lateness as lbs / gross_lbs

ScoringContext
  priorities: dict[OrderKey, int]                          # for priority assignment
  regular_orders_by_key: dict[OrderKey, RegularOrder]      # for priority cost — looks up due_date, remaining lbs and gross lbs
  earliest_dp_excluding: dict[str, datetime]               # machine_id → earliest candidate DP NOT on that machine; missing key ⇒ no other machine has a DP this iteration
  earliest_dp_time: datetime                               # for level-loading (global min DP)
  new_machine_avail: dict[Greige, bool]                    # for new-machine preference
  cheap_sets: dict[str, frozenset[str]]                    # for recovery cost — machine_id → items it can run at its tail with no tape-out and no pattern change
  urgent_by_item: dict[str, list[RegularOrder]]            # for recovery cost — urgent regulars with remaining lbs, by item

assign_priorities(state: State) -> dict[OrderKey, int]
build_new_machine_avail(
    state: State, candidates: list[Move],
) -> dict[Greige, bool]
build_earliest_dp_excluding(
    state: State, candidates: list[Move],
) -> dict[str, datetime]
build_context(state: State, candidates: list[Move]) -> ScoringContext
```

The submodule is the natural home for everything that *defines
relationships across the plant*: the `OrderKey` identity, the
plant-wide priority sort, the new-machine availability sweep, the
per-machine "earliest other DP" computation, and the bundle the
scorer reads from. Level-loading's only cross-candidate input is
`earliest_dp_time`, which `build_context` computes as
`min(dp_time(c) for c in candidates)`. New-machine preference's input
is `new_machine_avail`, built by `build_new_machine_avail`. Priority
cost's cross-candidate inputs are `regular_orders_by_key` (derived from
`eligible_orders(state)`) and `earliest_dp_excluding`, built by
`build_earliest_dp_excluding` — see the sections below for the details.

## Reference week

`state.reference_week_idx` is the right edge of the "urgent" bucket in
eligibility (see "Per-item eligible orders"): a regular order with
`week_idx <= reference_week_idx` is urgent and takes precedence over the
item's safety order; one further out yields to safety replenishment
first. It is the lever that controls how far out a regular order has to
be before safety jumps the queue — we should not discourage scheduling
safety stock when only future regular demand remains, because that would
force the planner to schedule next-month demand *this* week even though
the safety pool is empty.

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
order has to be before safety jumps the queue (see "Reference week"
above for how it advances).

`safety_pool` and `safety_target` come from each `RlsItem`'s safety
view as currently committed — i.e., the final pool after all
already-registered jobs and on-hand are allocated through the buckets.
That's a coarse proxy for "how at-risk is this item" but it's a single
number per item that's already computed; we can refine later if real
data shows the planner mis-ordering things.

### Priority cost

The priority cost reframes "did the planner take a higher-priority
move first?" as an *opportunity cost*: every higher-priority regular
order the move skips is assumed to be deferred until **one week after
the earliest decision point on another machine** in the candidate
pool, and is charged the standard lateness shape for that deferral.

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
  fill_time = other_dp + 7 days
  days_late = (fill_time - O.due_date) in days           # ≤ 0 ⇒ no charge
  return (O.lbs / O.gross_lbs) × lateness_factor(days_late)
```

Notes:

- **Regular orders only.** Safety orders contribute no priority cost
  for now — their "miss" cost is drainage, which has a different
  temporal shape that doesn't compose cleanly into this per-move sum.
  Future work may revisit.
- **One week past the next free machine.** The proxy for "when will
  this order get made if not now" is the earliest decision point on a
  machine other than the move's own, plus a week: the next free
  machine picks it up, and a week of work on that machine is a fair
  guess at what stands between it and the order's last roll. An order
  whose due date is further out than that is not predicted late and
  costs nothing to defer; an order already past due is charged from
  its due date to that fill time. An earlier version used `max(due +
  1 day, other_dp)`, which made every skipped order look fillable the
  moment a machine freed up and so under-charged deferral.
- **Self-machine excluded.** `earliest_dp_excluding[machine_id]`
  drops every candidate on the move's own machine — that machine is
  committed to this move and can't simultaneously fill the higher-
  priority order. Missing key (no other machine has a DP this
  iteration) falls back to `earliest_dp_time` (the global min, which
  equals the move's own DP).
- **Same shape as `w.lateness`.** `(lbs / gross_lbs) ×
  lateness_factor(days_late)` is exactly how the raw view values a
  late delivery (share of the gross order × the week-linear-then-
  doubling factor — see "Costs" in `demand/DESIGN.md`), so the priority
  cost and the realized-lateness cost are directly comparable once the
  weights are applied: `w.priority` is the cost of one whole
  higher-priority order predicted one day late, just as `w.lateness` is
  the cost of one whole order delivered one day late. Setting the two
  equal is the natural starting point. `RegularOrder.gross_lbs` carries
  the week's demand as loaded for this purpose.
- **Move identity.** `Move` already carries `week_idx`, so the cost
  layer forms `OrderKey(move.item.id, move.week_idx)` directly to
  look up the move's own rank. `week_idx = None` (safety move) is a
  valid key. A move whose key is not in `priorities` (hand-built in
  tests) pays nothing.
- **Debug log.** With a `DebugLog`, each deferred order is a
  `priority_detail` row (`late_day` = the predicted days late, `cost`
  = the weighted contribution) under the candidate's `priority`
  summary row — see `debuglog/DESIGN.md`.
- **Heuristic.** The "one week past the next free machine" assumption
  is a proxy, not a prediction. Reality could fill the order earlier
  (via window advance bringing more candidates in) or later (via
  repeated commits piling up). Real-data tuning will show whether this
  proxy needs to evolve.
- **What was tried instead.** Through 2026-10-01 the priority cost was
  replaced by a *lateness floor*: every item's uncovered demand was
  charged, inside the lateness term, at the earliest time the machines
  holding its yarn could knit it, with a capacity-aware predictor. It
  was dropped because it behaved perversely under tuning — a shorter
  linear window or a higher lateness weight made *more* pounds late,
  and it drove machines across yarn families and back — and because
  the per-item prediction counted the same machines' capacity for
  every item on a shared yarn. The priority cost above is the simpler
  rule it had replaced.

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

## Changeover capacity

Changes are rationed (see `schedule/DESIGN.md`, "Changeover capacity").
Plant-wide, the floor can absorb only so many **changes** of any kind in
a day — tape-outs, pattern changes, runner changes and new machines'
style changes together, one unit per machine changed — the `change`
resource, five a day by default, counted against the day the change
starts whichever shift that is. (A week that began with sixteen changes
at once stopped the plant for three days; five a day, with the rest
following on later days, is the lesser harm.) Beneath that, the tape-out
and pattern-change rations of their own: two tape-out bars and three
pattern changes a day, both between 08:00 and midnight (first and second
shift), none at all on weekends. The machine model makes the rations
**real** — a plan that needs a slot the day no longer has waits for the
next one, and while it waits it knits its current item when the plant
still wants it (see "Filling a slot wait" under "Candidate enumeration")
and stands idle otherwise; the wait shows up as later rolls and any idle
time, which the existing lateness and idle costs already price. The
planner adds two things on top: the bookkeeping that makes candidates see
the committed bookings, and one cost term — the recovery cost — that
charges a move for the demand it strands and the slots a recovery would
need. Using a slot carries no charge of its own: the rations are hard
limits and the wait they cause is already priced by lateness and idle
time.

### Bookkeeping

`State.capacity` is the plant's `ChangeoverCapacity`. Candidate
enumeration passes it to `plan_production` next to the inventory, so
every candidate is laid out against the slots the committed moves have
already taken; `commit_move` books the chosen plan's `capacity_taken`.
The pre-pass's recommits book first, in the prior plan's start order.
The greedy commits in score order, not time order, so a move committed
later can find the day's units taken by a move whose change actually
falls later that day; the later move then waits for tomorrow. Score order
roughly follows urgency, so this is accepted for now and the report (the
`changeovers` sheet) shows every wait so the ordering can be judged.

### Recovery cost

A tape-out or a pattern change takes a machine out of the set of machines
that can make some items *cheaply* — with neither a tape-out nor a pattern
change. If the open demand on those items can still be made on time by the
machines left in that set, the move costs nothing here. If it cannot, some
machine will have to be converted back later, and what that takes depends
on what the plant has: a new machine on the same yarn is a five-minute
style change, an old machine on the same yarn in another family is a
rationed pattern change, a machine on another yarn is a rationed tape-out.
The recovery cost is the predicted lateness of the stranded demand at the
fill time those routes imply, weighted by how many machines each route
offers.

**The cheap set.** For every machine, from its `schedule_tail`:

```
cheap(m) = { items I : I's yarn fits m's bars at its tail (the preamble's fit test), and
                       (m.is_new  or  I's pattern family == m's current item's family) }
```

A new machine's cheap set is everything on its yarn; an old machine's is
its yarn and its pattern family. A machine on an item it **cannot run**
(`Machine.can_run_current_item` False) has an **empty** cheap set: it is
knitting nothing the plant can use, so no move on it strands anything —
its recovery cost is 0 whatever it changes to — and it covers no other
machine's departure. (It still counts as a route for getting an item
back, by what it holds on its bars.) `ctx.cheap_sets` holds these for
the iteration. For a move on machine `M` to item `B`:

```
lost(M, B) = cheap(M at its tail) − cheap(M after the move)      # items M could make cheaply and no longer can
```

A tape-out loses the old yarn's items (less any `B`'s yarn also serves); an
old machine's pattern change loses the old family's items on the same
yarn; a runner change or a new machine's style change loses nothing.

**What is stranded.** For each `I` in `lost(M, B)` with urgent open demand
(`ctx.urgent_by_item[I]`, the regular orders through the reference week
with remaining lbs), walk its orders in due-date order and ask whether the
machines still able to make `I` cheaply can cover them on time:

```
others = cheap-set holders of I, excluding M
for O in urgent orders of I, by due_date:
    cap         = Σ over m in others of lbs m can knit of I from its tail to O.due_date
                  (rate of I on m × work hours), less what earlier orders of I took
    uncovered_O = max(0, O.remaining_lbs − cap)
```

All covered ⇒ `recovery(I) = 0`: the current machines on that yarn and
pattern carry it, and the move is free to leave. (The last-holder rule is
the special case `others = ∅`.)

**What getting it back takes.** The uncovered pounds need a recovery move
on some other machine. Four routes, each with the machines it could use
(`n_r`, machines other than `M` that can run `I`) and the earliest it could
deliver (`t_r`), with every slot wait read from `state.capacity`:

| route | machines `n_r` | earliest fill `t_r` |
|---|---|---|
| style change | new machines on `I`'s yarn | earliest tail among them (they are the cheap set, already booked to the horizon, so in practice the end of the urgent window) |
| runner change | old machines on `I`'s yarn in `I`'s family | as above |
| pattern change | old machines on `I`'s yarn in another family | next free pattern-change slot at or after the earliest of their tails |
| tape-out | machines on another yarn that can run `I` | next free both-bar tape-out slot at or after the earliest of their tails, plus a pattern-change slot when that machine is old and in another family |

Every route is a change, so each `t_r` is then pushed to the next free
`change` slot at or after it; a day already full of changes delays every
recovery alike.

```
p_r         = n_r / Σ_r n_r                                 over routes with n_r > 0
fill_r      = t_r + 7 days                                   the priority cost's "a week of work" lead
recovery(I) = Σ_r p_r × Σ_O (uncovered_O / O.gross_lbs) × lateness_factor(days(fill_r − O.due_date))

recovery_cost(move) = w.recovery × Σ over I in lost(M, B) of recovery(I)
```

So many new machines on the yarn put most of the weight on the style
route and the fill comes soon, so leaving costs little; few new machines
and several old ones in other families shift the weight to the pattern
route, whose fill waits on the three-a-day ration; a unique yarn has only
the tape-out route, whose fill waits on the two-bars-a-day ration, and
leaving it is expensive. A day already full of tape-outs pushes every
recovery fill out and makes leaving dearer.

Notes:

- **Same units as lateness.** `w.recovery` is the cost of one whole
  stranded order predicted one day late; `lateness` is the natural
  starting value.
- **Overlap with the priority cost.** An order charged here may also be
  in the priority cost's sum when it outranks the move. That double
  counting is accepted: jumping the queue and stranding a yarn are
  different mistakes.
- **Routes count machines, not capacity.** The route weights are head
  counts, deliberately: the question is which kind of conversion the
  plant is likely to end up making, not how much each could knit. The
  capacity question is answered once, by the cheap set, in the stranding
  step.
- **Per iteration / per move.** `cheap_sets`, the route machine lists per
  yarn and family, and `urgent_by_item` are built once in `build_context`;
  the per-move work is `lost(M, B)` and the capacity walk over those few
  items, memoised per `(M, B's yarn, B's family)`.
- **Heuristic.** It prices a departure by what the plant has on hand to
  undo it, not by predicting the planner's later moves.

### Reporting

The xlsx has a `changeovers` sheet: a `period` row per `(resource, day)`
that was booked — `period_start` / `period_end`, `capacity`
(`units_per_period`), `used`, and `activities` as `machine:id@HH:MM` —
and a `wait` row per slot wait (an `Idle` with a `reason`): `machine`,
`resource`, `start`, `end`. A `change` unit is read off the schedule as
one per preamble that changed the machine: one per changeover activity
(`StyleChange` / `RunnerChange` / `PatternChange`), plus one per
`TapeOut` with no changeover activity before the next `Knit` (a
same-item tape-out of a foreign bar), listed by that activity. The
`schedule` sheet's `desc` reads `waiting for change slot` (or `tape_out`
/ `pattern_change`) on such an idle, and the schedule JSON carries the
idle's `reason`. A job that filled a wait is marked on the `production`
sheet (`fill`) and in the JSON, and the CLI prints how many jobs filled
waits and with how many rolls. The tape-out report's candidate lines
show the slot the tape-out landed in, the recovery cost and the items
the move strands, so a questionable tape-out can be read against what it
cost. The Gantt (`scripts/make_gantt.py`) gets a per-day strip of units
used of capacity, the `change` count read the same way.

### Configuration

```
"changeover_capacity": {                 # optional; absent ⇒ unlimited
    "change":         {"units_per_period": 5, "window": [0, 24]},   # machines changed, any kind
    "tape_out":       {"units_per_period": 2, "window": [8, 24]},
    "pattern_change": {"units_per_period": 3, "window": [8, 24]}
}
```

Any subset of the three may be given; a kind left out is unlimited, so
the block can carry the plant-wide `change` cap alone, or the per-kind
rations alone, or both.

and one new weight, `recovery`, in the lateness units (one whole
stranded order one day late); `lateness` is the natural starting value.

## End-to-end workflow

```
state = State(machines, rls_items, start_date, inventory)
# `inventory` = the loaded beam sets grouped by `desc.physical`, every set
# available at start_date (empty dict when the config has no `beam_sets`)
costing = Costing(weights)
report = plan(state, costing)
# state has been mutated; report summarizes the result
```

The post-call `state` is the deliverable — machines now carry the
committed activities, rls_items now carry the registered jobs.

## CLI entry point

The `plan` console script (`planners/cli.py`) is a `typer` app with two
subcommands. `plan infinite` (`planners/infinite/run.py`) runs the planner
end-to-end; it takes one required positional argument — a path to a
**run-config JSON** — plus a set of optional override flags:

```
plan infinite <config.json>
    [--start-date YYYY-MM-DD]
    [--products PATH] [--workcal PATH] [--machines PATH]
    [--demand PATH]   [--weights PATH]
    [--output-dir DIR]
    [--verbose]
```

`plan variants` (`planners/variants_cmd.py`) builds the two variant files
the run-config's `variant_map` / `variant_masters` keys point at, from the
plant's variant table and the master list (see `products/variants.py`):

```
plan variants <input-dir>            # holds greige-master-styles.json + variants.tsv
    [--masters PATH] [--variants PATH] [--styles PATH]
    [--out-dir DIR]                  # default: <input-dir>
    [--quiet]
```

The master list names each master style's **representative variant**; that
variant's table row defines the master (per bar: runner length, ends, split
lease, yarn — the split-lease pair being the two bars threaded one in, one
out, whatever their merge codes; every other bar is a set of its own, and a
row using more than two distinct merges is excluded), and another row is a
variant of the master when it matches
the representative on every bar — same construction and beam count, the
same yarn as the planner tells yarns apart (denier class, colour, cationic
or recycled finish, textured or flat), and the same runner length: exactly, or failing
an exact match with any master, within 2 on every bar, the row going to the
nearest such master by summed runner-length distance (a tie is ambiguous
and excluded; older constructions share the style number but sit further
off and are no longer used). It writes `greige-variant-map.json` (each master also recording its
representative), `greige-variant-masters.json` and the audit report
`greige-variants-report.txt` — which names, for every row that matched no
master, the nearest one and what differed — and prints the report unless
`--quiet`. When `greige-styles.json` is present its beam-set labels are
cross-checked against the representatives'. Re-run it whenever the master
list or the variant table changes — the planner reads the generated files as
they are, and a machines entry whose variant maps to a master not in the
styles falls to `NONE`.

`plan styles <input-dir> [--out PATH] [--prior PATH]`
(`planners/styles_cmd.py`) generates `greige-styles.json` from the master
list, `variants.tsv` and `knit-machine-master.json`. The master list is the
authoritative list of styles; each record takes its gauge, width and
`beam_cfg` (labels, weight shares, runner lengths) from the master's
representative variant, its `rack_wt` from the **average** over the
master's variants, and its `pattern` from the stitch patterns its two
**sets** knit — the single-bar set's stitch and the split set's two
half-bar stitches in bar order, independent of which bar carries which set
(a style that flips top and bottom is the same pattern); masters with the
same set stitches share a family letter, handed
out `A`, `B`, … in the order the list first shows each pattern (`Z` is
`NONE`'s). Its
`machine_rates` cover every machine in the knit-machine master that can run
it — gauge equal; the machine at least as wide as the style (the master's
`width` in inches against the style's); the 75-denier set on the top bar
needs a `tall` machine — at the nominal rate above, from the machine's
one `rpm`. `safety` — and `tgt_wt` when present — come
from the master list's own records, where the safety target is maintained;
a value the list lacks comes from the previous styles file (`--prior`,
default the output file when it exists), and failing that from the
defaults, 740 lbs and two rolls, which is reported. The `NONE`
placeholder is carried over and written first; a master the two-set model
cannot define (`AU1148G36`, one merge on both bars) is skipped and reported.

`plan manual <config.json> <steps.json> [--output-dir DIR]`
(`planners/manual_cmd.py`) rebuilds a hand-made schedule from a step file
on the same run-config and writes `manual_schedule_<start date>.json` in the
schedule-JSON format — see `planners/manual/DESIGN.md`.

`plan retime <config.json> <prior plan.json> <tickets.json> [--output-dir DIR]
[--keep-sets]` (`planners/retime_cmd.py`) carries an existing plan forward
to the current machine status without re-deciding it — the same jobs and
rolls, re-timed from the config's new dates and machines file, the sets
handed out from its inventory in runout order, or, with `--keep-sets`,
the prior plan's sets kept where they still can be and only its `NEW…`
placeholders filled — and writes the usual `knit_plan_<date>.xlsx` /
`.json` plus `retime_<date>.txt`; see `planners/retime/DESIGN.md`.

`plan machines <runtime-export.json> <input-dir> [--out PATH] [--base PATH]`
(`planners/machines_cmd.py`) converts the plant's runtime export into a
machines JSON (default `<input-dir>/machines-new.json`). The export covers
the whole floor, one record per machine with `is_new`, a tagged quantity
per bar — `{"unit": "time", "val": "HH:MM"}` of running time left on the
set, excluding stops (the new line), or `{"unit": "lbs", "val": …}` of yarn
left on the set as the legacy line's beam tracking computes it, `0` meaning
an empty bar waiting for its next set — and `racks_on_roll`, the racks
already wound on the roll in progress. (The older form — `top-rem` /
`btm-rem`, `racks-to-doff` = racks *left*, optional `item` and set numbers
— is still read.) The export never names the item or the mounted sets:
those come from a **base** machines file (`--base`, defaulting to the
output file when it exists), whose `init_item` and `init_top_set` /
`init_btm_set` objects are carried over verbatim, so refreshing the runtime
numbers never loses the plant's merge and vendor. The result is the
**intersection** of the two files: a machine in only one of them is dropped
and reported (export-only has no item; base-only has no fresh numbers).
The export covers the whole floor; a machine whose item's bars do not group
into exactly two merges — a 2-bar style with one merge on both bars, or a
three-merge construction — cannot be an automotive style (ours are always
a single-bar set plus a split-lease pair) and is skipped and reported
rather than written, as is a machine whose item the variant table does not
have at all (one down for `OVERHAUL`). A machine running a variant the mapping excluded is
still written and flagged; the planner loads it as `NONE`.
Pounds come from the variant table, the knit-machine master and the greige
styles: racks/hour = rpm × 60 / 480; lbs/rack = `rack_wt` / 100; a `time`
bar's lbs = hours × racks/hour × lbs/rack × that bar's share of the weight
(bars grouped by merge, the group holding bar 1 being the bottom), a `lbs`
bar is taken as is; `init_roll_lbs` = racks_on_roll × lbs/rack, the lbs
already **wound** on the roll (the old `racks-to-doff` form, racks left,
is converted: the master's `tgt_wt` − racks left × lbs/rack, floored at
0). The machines loader turns the wound lbs into the model's roll
remaining from the item's `tgt_wt` (see File I/O in schedule/DESIGN.md;
a roll past target is about to be doffed and counts as between rolls).
Re-run it whenever the floor data is refreshed; it is the source of the
`init_*` fields the machines loader reads. It writes the mounted sets in the
bare set-number form; a machines file produced by the plant's own tooling
may instead give `{"set_no", "merge", "vendor"}` objects, which the loader
also accepts (see `schedule/DESIGN.md`, File I/O).

The input resolution is shared: `run.load_config(config)` /
`run.load_inputs(cfg, config_dir, start_date=…, overrides=…)` return an
`Inputs` record (greiges, variant files, inventory, workcal, demand,
machines, weights, the blacklist), used by `plan infinite` and by the manual
scheduler so a config loads identically in both. The `blacklist`
(`products.Blacklist`: merge codes, vendor names and set numbers, each as a
string, whitespace trimmed, compared case-insensitively) is handed to the
beam-set and machine loaders, so every set built from the export or an
assigned-sets record is stamped `blacklisted` when its merge, its vendor or
its set number is on it, and the load echoes how many merges, vendors and
sets are listed, how many stock sets were withheld, and each blacklisted
set found mounted on a machine or queued at one (the queued ones are passed
over when their bar next hangs; the mounted ones make their bar foreign, so
the machine's first plan tapes them out — see "Blacklisted merges" in
schedule/DESIGN.md). The load also echoes each assigned set applied to a
bar as **hung** (`"status": "hung"`, and whether the first plan threads
or unhangs it), each assigned-sets record it **dropped because the
machines file already has that set mounted** on a bar (the mounted set
wins — see File I/O in schedule/DESIGN.md: the record names the set,
where it was assigned and where it actually is) and how many queued sets are staged at their machines
against still in the warehouse. The run's change-date advance (the
load's own run-up) is that first plan, so a hung set that fits is
threaded at the start date, before the planner decides anything. It also
echoes every large (40 in) set found mounted on or queued at an old
machine, which cannot take it (see "Large beams" in schedule/DESIGN.md),
and every machine found on an item it cannot run (the style's machine
list leaves it out), which idles until the planner changes it (see
"Inputs" above). The machines file's **`status`** (see File I/O in
schedule/DESIGN.md) is applied at load too: machines on **`overhaul`**
are left out of the run entirely — not in `Inputs.machines`, so not in
any decision, ration, recovery route or output — and the load echoes
them; machines **`standing`** are loaded with `standing=True`, echoed as
such, idle to the change date, and join the candidate pool like any
other machine but with the restart cost on their first move (above), so
they are used only when needed and otherwise never appear in the plan.
(A standing machine still counts in the recovery cost's cheap set for
the yarn it holds: it can make those items after a restart.) The
blacklist file is either a JSON list of merge codes
as the export writes them (`"292286"`, `"292286BAD"`, `"299029-A"`, …) or
an object with any of three lists:

```json
{"merges":  ["292286", "292286BAD", "299029-A"],
 "vendors": ["Unifi Manufacturing, Inc"],
 "sets":    ["2-3824", "W2-2637"]}
```

`merges` are merge codes, `vendors` the yarn vendor's name as the export
writes it, `sets` set numbers. Every entry is compared trimmed and
case-insensitively and matches **exactly** the thing it names: a code's
`BAD` or `-A` variants are listed in their own right, and so are a
vendor's spellings (`Unifi Manufacturing, Inc` and `Unifi/Nanya` are two
vendors). A set is blacklisted when any one of the three names it.

### Run-config JSON

A top-level object with six required keys, plus optional `variant_masters`,
`variant_map`, `beam_sets` and `database` entries:

```
{
    "start_date": "YYYY-MM-DD[ HH:MM:SS]",     # always inline; local time; a
                                               # bare date means midnight
    "change_date": "YYYY-MM-DD[ HH:MM:SS]",    # optional (default start_date):
                                               # when the plant can first change
                                               # a machine over — see Inputs
    "mode": "exact" | "planning",              # optional (default exact) — see
                                               # "Planning mode"
    "products":   <path-string | list of greige objects>,
    "workcal":    <path-string | workcal object>,
    "machines":   <path-string | list of machine objects>,
    "variant_masters": <path-string | {variant name: master id}>,
                                               # optional; lets `machines`
                                               # name plant variants in
                                               # `init_item` (see
                                               # schedule/DESIGN.md, File I/O)
    "variant_map": <path-string>,              # optional; the per-master
                                               # merge-combination -> variant
                                               # file (products.variants)
    "beam_sets":  <path-string | list of beam-set objects>,
                                               # optional; the plant's beam-set
                                               # inventory (products.read_beam_sets):
                                               # set_no, merge, vendor, received,
                                               # lbs, beams, ends, denier, luster,
                                               # desc, assigned, size (the beams'
                                               # "<diam> x <width>" in inches; a
                                               # 40 in set fits only new machines
                                               # — schedule/DESIGN.md "Large beams")
    "assigned_sets": <path-string | list of {set_no, merge, vendor, machine, bar,
                                              denier, luster, desc, ends, beams,
                                              lbs, received, size, status}>,
                                               # optional; sets assigned to a
                                               # machine bar. `status` is
                                               # "inventory" (still in the
                                               # warehouse; the default) or
                                               # "staged" (at the machine) — both
                                               # queue on the bar — or "hung": on
                                               # the bar, not threaded, so the
                                               # first plan threads it without a
                                               # hang, or unhangs it when it does
                                               # not fit (see schedule/DESIGN.md,
                                               # File I/O).
                                               # The yarn fields are the export's;
                                               # they describe a set the export
                                               # lacks
    "blacklist":  <path-string | list of merge codes | blacklist object>,
                                               # optional; yarn flagged for quality:
                                               # a list is merge codes; an object
                                               # {"merges": [...], "vendors": [...],
                                               #  "sets": [...]} (each optional) also
                                               # names whole vendors and individual
                                               # set numbers. A set carrying any of
                                               # them is never hung by the planner
                                               # (see schedule/DESIGN.md,
                                               # "Blacklisted merges"); absent ⇒ none
    "demand":     <path-string | list of demand objects>,
    "weights":    <path-string | weights object>,
    "changeover_capacity": <object>,           # optional; the rations of changes, tape-outs
                                               # and pattern changes per day (see
                                               # "Changeover capacity"); absent ⇒ unlimited
    "prior_plan":  <path-string>,              # optional; the previous plan, already
                                               # retimed to today's status (`plan
                                               # retime`), whose urgent jobs the
                                               # planner recommits before planning
                                               # — see "Sticking to the prior plan"
    "state":      <path-string | object>,      # optional; `State` tunables by field name
                                               # (see below); absent ⇒ the defaults
    "database":   <db-config object>           # optional; only used with --verbose
}
```

**`state` block.** Any `State` tunable can be set by its field name:
`candidate_threshold`, `reference_threshold`, `reference_advance_amount`,
`reference_week_idx`, `eoq_threshold_rolls`, `eoq_batch_rolls` (integers
— the last two the economic-order-quantity thresholds, see "Move sizing";
3 and 4 by default) and the four durations
`window_advance_amount`, `carrying_avoidance_margin`,
`planning_horizon_buffer` and `frozen_window` (how far into the prior
plan the pre-pass recommits — see "Sticking to the prior plan"; unset
means unbounded). JSON has no duration type, so a duration is written as
a number of **hours** or as a string with a unit — `"48h"`, `"3d"`,
`"2w"`, `"90m"` — or as `"HH:MM"`; negative values are allowed. A field
left out keeps the `State` default (24 h, 24 h, 4 weeks and unbounded
for the four durations). The block can also come from the
`--state-cfg` CLI option.

**Clock.** The planner's clock is the plant's **local time**: `start_date`,
the export's `received` dates, every activity time and the xlsx report are
all local wall-clock time, and the working calendar's days, weekends and
holidays are local days (its `cal_shift` is not a time-zone offset but
where the plant's day begins relative to midnight — see `support.workcal`).
The plant's systems store timestamps in **UTC**: an export's timestamps
must be converted to local time before the planner reads them (for now on
the input files themselves; doing it in the loaders is the intended next
step), and the schedule JSON converts back to UTC on the way out (see
"Schedule JSON").

**Planning mode.** `"mode": "planning"` asks for a coarse plan — how many
rolls of what to run on each machine before switching it — rather than
exact runout and doff times. It is a process-wide switch
(`support.planning_mode`, set by `load_inputs` before any input is read)
that changes three plant-wide facts: doffing, hanging and threading take
0.01 h each (tape-outs and changeovers keep their real durations, so a
changeover still costs what it costs); there is no beam-set stock — the
`beam_sets` and `assigned_sets` inputs are ignored, a taped-out set is
never returned, and every set a changeover needs is invented — and every
set, mounted or invented, starts with 1,000,000 lbs, so a set only ever
comes off a machine because a changeover needs different yarn, never
because it ran out; and machines run at 65 % efficiency (`planning_mode.EFFICIENCY`)
instead of the model's `RUNNING_EFFICIENCY` of 76.5 %. The
model, the loop and the outputs are otherwise unchanged; the schedule JSON
still has times, they just no longer claim to be the floor's. `"exact"`
(the default, and what the tests exercise) is the full model.

A greige object's `machine_rates` are **nominal** lbs per hour of running
time: `rate = rpm × 60 / 480 revs per rack × rack_wt / 100`, with the
machine's rpm from the knit-machine master (900 on the legacy line, 2200 on
the new line, 1500 for a wide style — over 200" — on a new machine). They
carry no efficiency factor: the machine model scales every rate by
`schedule.machine.RUNNING_EFFICIENCY` (0.765; 0.65 in planning mode), so the
efficiency is one constant to edit rather than a number baked into every
style's rate matrix. The styles file itself is generated by `plan styles`
(see "CLI entry point").

`variant_masters` is the variant -> master translation written by
`products.variants.write_variant_masters` (built from the plant's variant
table). Without it, an `init_item` that is not a master id resolves to
the `NONE` greige.

`variant_map` (written by `products.variants.write_variant_map`) is what
lets the schedule name the exact variant a knit produces: it supplies the
merges on each machine's initial bars (from the `init_item` variant) and is
handed to every `Machine`, which stamps `Knit.variant` from the merges on
its bars. `beam_sets` is the inventory export; each set is labelled through
the `variant_map`'s merge table (`products.read_beam_sets`), keeps its
`vendor`, and enters the planner's stock available from its `received`
timestamp (`YYYY-MM-DD HH:MM:SS[.fff]`, local time — see "Clock") — so an export
newer than `start_date` puts sets received in between into stock at the
moment they arrived, and a record without `received` is on hand from
`start_date`. Both are optional: without them the planner invents every
beam set it hangs (as before) and no knit carries a variant.

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

Connection settings for the SQL Server store the verbose `DebugLog` is persisted
to. **Only consulted when `--verbose` is set**; a non-verbose run ignores it, and
it may be omitted entirely. The planner connects as the **writer** login (SQL
authentication; `SELECT,INSERT`), so the block names a single connection
directly — `host` / `port` / `name` / `user` / `password` — plus three optional
ODBC settings whose defaults are shown:

```
"database": {
    "host": "127.0.0.1",
    "port": 1433,
    "name": "swmtinfinite",
    "user": "swmt_writer",
    "password": null,                            # null → SWMT_DB_PASSWORD
    "driver": "ODBC Driver 17 for SQL Server",   # optional
    "encrypt": "no",                             # optional
    "trust_server_certificate": "yes"            # optional
}
```

The read-only investigation app is a separate concern with its own
**reader**-login connection from `SWMT_DASHBOARD_CONFIG` (see
`swmtplanner/dashboard/DESIGN.md`); read-only is enforced by that login's SQL
Server permissions. Any field may be left out of the file and supplied by
environment variable (`SWMT_DB_HOST` / `_PORT` / `_NAME` / `_USER` /
`_PASSWORD` / `_DRIVER` / `_ENCRYPT` / `_TRUST_SERVER_CERTIFICATE`), with the
environment winning — so a committed config can hold non-secret defaults and
leave the password to the environment. (The read-only app uses a separate
`SWMT_DASHBOARD_*` namespace, so the writer's `SWMT_DB_*` variables never bleed
into it.) The block is normally **inline** in the main config file, but
`--db-conn` can override it (path or inline JSON) for a one-off run. Both the
writer and the reader connect through the dashboard's shared
`config.connection_string` / `config.connect` (pyodbc), so the ODBC details live
in one place. The debug schema and write path are in **Debug-log persistence to
SQL Server** below; the read-only viewer is `swmtplanner/dashboard/DESIGN.md`.

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
| `--verbose`    | `-v`  | flag; persist the run's `DebugLog` to SQL Server (see **Debug-log persistence to SQL Server** below) |

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

After the plan the CLI prints the score, the unmet (item, week) count and
— when any — the **assigned sets passed over**: per machine and bar, each
plant-staged set a hang could not use — skipped because its yarn did not
fit the requirement then (it stays queued for a later hang), or dropped
because its merge is blacklisted or it is too large for the machine —
with the requirement, the hang time, the reason and whether it was kept
or dropped (`PlanReport.queue_passed_over`, from
`Machine.queue_passed_over`; see "Assigned sets and bar queues" in
schedule/DESIGN.md). It then writes a
single Excel workbook at
`<output_dir>/knit_plan_<YYYYMMDD>.xlsx` where the YYYYMMDD is the
resolved `start_date`. Eight sheets:

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
  activity across all machines that did any work: a machine whose only
  activity for the whole run is `Idle` (nothing could be planned on it)
  is left out of this sheet, of `collapsed_sched` and of the schedule
  JSON (`schedule_json.has_work`). The `desc` cell names physical beam sets
  where an activity touches one: a `Hanging` / `TapeOut` / `Unhang` /
  `Waste` shows, per bar, the set's planner label, set number and merge
  (an invented set reads `NEW…` with no merge), a `Hanging` also the lbs
  hung and a `TapeOut` or `Unhang` the lbs returned; a `Knit` shows the
  item, its variant when known, and
  the set number and merge on each bar (`top #1-1243 6268G / btm #…`).
- `collapsed_sched` — a higher-level, operator-facing view of the same
  per-machine activity schedule, with consecutive activities folded into
  coarse steps (see "Collapsed schedule" below).
- `production` — multi-indexed by `(item, job_id)`, one row per
  committed `Job`: its `total_rolls`, `total_lbs`, `completion`
  (when the job finishes — its last roll's `completion_time`), and
  `tgt_order` — the id of the order the job was raised to target
  (`Job.tgt_order`), **blank** when the job targeted no specific order
  (e.g. a `'next_runout'` run-up job) — and `fill`, true when the job
  (also) knit rolls of the current item while the machine waited for a
  ration slot (see "Filling a slot wait").
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
  - `variant` — `Knit.variant`: the plant variant the merges on the two
    bars identify (comma-separated names when several share the recipe);
    **blank** when a bar's set has no known merge or the pair matches no
    recipe — the knit is then for the generic master only
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
- `late_orders` — flat `(item, week_idx, late_lbs, late_pct, late_fill_date)`,
  one row per `PlanReport.late_orders` entry; `late_pct` is `late_lbs` as a
  percentage of the week's gross demand, the quantity the lateness cost is
  valued on. `late_fill_date`
  reports when the order will finish filling (the latest contributing
  chunk's arrival time), even if some demand remains unmet.
- `prior_jobs` — only when the run had a prior plan: one row per prior
  job (`machine, prior_job, item, rolls, order, due_date, start, status,
  job_id, note`) — see "Sticking to the prior plan".
- `unassign` — the plant-assigned sets the plan found at a machine and
  could not use, which the person entering the schedule should
  **unassign in the system** (and the floor should pull back): one row
  per set, `machine, bar, set_no, merge, vendor, yarn, lbs, state,
  location, when, bar_needed, reason`. Two kinds, told apart by `state`:
  a **`queued`** set the plan **dropped** at a hang — blacklisted, or too
  large for the machine — or **skipped** at one or more hangs because it
  did not fit the bar's requirement then and **never hung by the plan's
  end** (it is still in the bar's queue, `PlanReport.queues_left`; a
  skipped set the machine did get to later is not listed — see
  "Assigned sets and bar queues" in schedule/DESIGN.md). `location` is
  the queue's `staged` / `inventory`, `bar_needed` the requirement at
  the (last) hang that passed it over, `when` that hang's start, `reason`
  the `PassedOver` reason, and `ends_on` the item the machine is on at
  the end of the plan — a skipped set that fits that item may just be
  waiting for a hang beyond the horizon, which the reader can judge; and a
  **`hung`** set — hung on the bar but never threaded — the plan took off
  with an `Unhang` because it did not fit the item the machine was given
  (`when` the unhang's start, `bar_needed` the item's requirement,
  `reason` `does not fit`; a blacklisted or too-large one says so). A set
  the plan **threaded** is not here: it was used. Rows in machine order,
  then by `when`. The sheet is always written, empty when there was
  nothing to unassign, so its absence never has to be interpreted. Both
  `plan infinite` and `plan retime` write the workbook, so the retimed
  plan carries it too; the same sets are also echoed by the load
  (`run.passed_over_lines`), listed in the retime text report and carried
  on the schedule JSON's `Hanging.passed_over` / `Unhang` entries.

When `--verbose` is set, the planner additionally builds and populates
an in-memory `DebugLog` audit trail during the run — see "Verbose
audit log" below.

See `report.py` for the per-sheet layouts.

#### Tape-out decisions (`tape_outs_<date>.txt`)

Alongside the xlsx and JSON the CLI writes a plain-text audit of every
tape-out the planner chose: `plan(..., tape_out_report=path)`. The file
takes the same name suffix as the run's xlsx and JSON — `tape_outs_<date>.txt`
beside `knit_plan_<date>.xlsx`, or `tape_outs_<date>_<n>.txt` when the
run's outputs were numbered because `knit_plan_<date>.xlsx` already
existed — and is truncated before the run starts, since the planner
appends to it one decision at a time. At each
iteration whose winning move carries a `TapeOut`, the block appended lists
the iteration (window end, reference week, candidate count), the chosen
move, and then **every candidate of that iteration** in ascending score —
machine, item, lbs, start point, leading idle, the order week it serves,
the tape-out bars, changeover kind and sets hung it would need, its score
and its gap to the chosen move. It uses the hot path's scores, so it costs
nothing extra and needs no debug log; the per-component breakdown is the
debug log's job.

#### Schedule JSON

Alongside the xlsx, the CLI writes the schedule as JSON (same stem,
`.json`; `schedule_json.py`, `write_schedule_json(report, path)`) — the
machine-readable hand-off of the plan. A list of machine objects:

```
[{"id": "<machine>", "schedule": [<job | orphaned activity>, ...]}, ...]
```

Machines whose only activity is `Idle` are left out, as on the schedule
sheets. `schedule` is chronological and every entry carries `kind` and `id`. A
**job** (`kind: "job"`) is placed at its first activity's start and holds
`item`, `tgt_order`, `due_date` (the target order's due date, null for a
safety or run-up job — what a later run matches the job to its order by,
see "Sticking to the prior plan"), `prior_job` (the prior plan's job this
one recommits, else null), `fill` (true when the job filled a slot wait,
see "Filling a slot wait"), `start`, `end`, `total_lbs`, `rolls` and
`activities` (its `Job.activities` — see `schedule/DESIGN.md` "Job
activities"). A roll
has a derived `id` `<job id>-R<n>` (1-based within the job; `Roll` has no id
of its own), `item`, `variants` (the distinct `Knit.variant` values of its
knits, in order, empty when none is known — a roll straddling a beam swap
can be wound by knits of different variants), `lbs`, `completion_time` and
`knits` (ids of the knits that wound it, which appear in the job's
`activities`). An **orphaned activity** — one no job claims: `Idle`,
`Waste`, a first tape-out with no prior job — appears as a schedule entry
in its own right.

An activity object is `kind` (the class name), `id`, `start`, `end`, then
the type's own fields: `Knit` → `item`, `lbs`, `variant`, `top_beam`,
`btm_beam` (the sets on the bars while it ran); `Waste` → `beam`,
`bar`, `lbs`; `TapeOut` / `Unhang` / `Hanging` → `bars`, `top_beam`, `btm_beam` (null
for an untouched bar), a `Hanging` also `passed_over` — a list of
`{"bar", "set_no", "merge", "vendor", "desc", "lbs", "reason"}` for the
queued sets it **dropped** (blacklisted, too large) — and `skipped` — the
same shape, reason `does not fit`, for the queued sets it looked past and
left queued — each only when there were any; `Threading` → `bars`;
the changeovers → `from_item`,
`to_item`; `Doff` / `Idle` nothing more. A `Greige` reduces to its id; a
`BeamSet` to `{"set_no", "merge", "vendor", "desc", "lbs"}` (`merge` and
`vendor` null for an invented set; `lbs` is the set's pounds at that moment
— hung on a `Hanging`, returned to stock on a `TapeOut` or `Unhang`), plus
`"blacklisted": true` on a set whose merge the run blacklisted (the set a
`TapeOut` took off a bar it was found mounted on, or a passed-over queued
set; the key is left out otherwise), `"location"` on a plant-assigned
set (`"staged"` / `"inventory"`, the assigned-sets record's `status`; left
out otherwise) and `"size"` (`"<diam> x <width>"`) when the set's size is
known. Datetimes are
written the way the plant's systems store them: **UTC**, `YYYY-MM-DD
HH:MM:SS`, whole seconds. The planner's clock is plant local time (see
"Clock"), so the writer converts every timestamp through the plant's zone
(`schedule_json.PLANT_TZ`, America/New_York — daylight saving handled
per timestamp) and truncates the microseconds that rate arithmetic leaves
behind, so a job's `end` and the next activity's `start` still agree.

`PlanReport.jobs_by_machine` (each machine's `Machine.jobs`, in commit
order) is what pairs the jobs with the machine's activity schedule.

#### Collapsed schedule (`collapsed_sched`)

A condensed, operator-facing rewrite of the per-machine activity schedule:
runs of fine-grained activities are folded into a few coarse step types so the
sheet reads as "knit this, swap that, change to this" rather than the full
activity ledger. Built by a new `collapsed_schedule_dataframe(report)` in
`report.py`, written as the `collapsed_sched` sheet.

**Indexing & columns.** Indexed by `machine` (single level, so repeated machine
cells merge in Excel, matching the `schedule` sheet's grouped look); the
remaining columns are **`label`, `start`, `end`, `lbs`, `desc`**. As on the
`schedule` sheet, `lbs` is populated only for knit rows and **blank (NaN) for
every other row** (`_round_int` → nullable `Int64`). Collapsed rows carry **no
id** — `label` names the step instead.

**Collapsing.** Walk each machine's activities in chronological order
(`report.schedules[machine]`, already chronological) and fold maximal runs into
collapsed rows. Every collapsed row inherits `start` from its **first** source
activity and `end` from its **last**. The step types:

- **`knit`** — a maximal run of consecutive `Knit` / `Doff` activities (one
  uninterrupted stretch of knitting + doffing the same style; a beam swap or
  changeover, being neither `Knit` nor `Doff`, ends the run). `lbs` = the **sum**
  of the component `Knit` lbs; `desc` = the **first** `Knit`'s description (the
  greige item id), matching the `schedule` sheet's Knit `desc`.
- **`runout`** — a re-thread block with **no `TapeOut`** (`Waste*` then
  `Hanging` + `Threading`) — a beam was re-hung without breaking into a
  still-usable set. `desc` = the **`Hanging`'s** description; `lbs` blank.
- **`yarn change`** — a re-thread block that **contains a `TapeOut`** (`TapeOut`,
  optional `Waste*`, `Hanging` + `Threading`) — the operator broke into a
  still-usable beamset and swapped it for a different one. Any changeover
  activity is **excluded** (emitted as its own row, below). `desc` = the
  **`Hanging`'s** description; `lbs` blank.
- **`style change` / `runner change` / `pattern change`** — each
  `StyleChange` / `RunnerChange` / `PatternChange` is **left alone** as its own
  row. `label` is the change type; `desc` = its own `'from <item> to <item>'`;
  `lbs` blank.
- **`idle`** — each `Idle` is passed through as its own row (blank `desc`, blank
  `lbs`), left alone like the changeovers.

So a same-style mid-production beam swap reads `knit → runout → knit`; a style
changeover that swaps yarn reads `… knit → yarn change → <style|runner|pattern>
change → knit …`; and a style change onto the *same* yarn reads `… knit →
runout → <…> change → knit …` (no yarn was actually swapped).

**Classifying a re-thread block (runout vs. yarn change).** A re-thread block is
the maximal run of `Waste` / `TapeOut` / `Hanging` / `Threading`. It is a
**`yarn change`** iff it contains a `TapeOut` (the planner taps out only when
breaking into a beamset worth preserving), else a **`runout`** — what matters is
*breaking into* a set, not whether a style change happens to follow. The
classification is **independent of any following changeover**: changing to a new
style on the *same* yarn is a `runout` then a change, not a `yarn change`. The
rare genuine yarn swap with no tape-out (an item change whose mismatched bars
are near-empty and so are `Waste`d rather than taped out) is, by this rule,
shown as a `runout` followed by the change — acceptable, since `yarn change`
specifically captures tape-out break-ins.

**Note.** A re-thread block with **two `Hanging`s** (the two bars re-threaded in
back-to-back single steps) takes the **first** `Hanging`'s `desc`.

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
is persisted to a **SQL Server** store (run-tagged by an auto-incremented
`run_id`); see **Debug-log persistence to SQL Server** below. It is then investigated
through the generic **PyQt6** debug dashboard (`swmtplanner/dashboard/`, a
viewer the planner hands its manifest to — not the planner core).

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

## Debug-log persistence to SQL Server

When `--verbose` is set and a `database` block is configured, the populated
`DebugLog` is persisted to a **SQL Server** store as one row-set per run, tagged
by an auto-incremented `run_id`. The database is shared with other tables, so
this planner's tables are all prefixed **`knit_`**: each manifest `TableSpec`
keeps its **logical** `name` (identical to the `DebugLog` table) and carries the
**physical** `db_name = 'knit_' + name`, which only SQL text uses (see the
dashboard's "Storage mapping"). Temporal columns are stored as **INTs** (a
`datetime` as a `_date`/`_time` pair, a `date` as a single YYYYMMDD) — again a
storage detail the generic mapping hides. This is the **planner-owned** half (the
planner owns its schema and the writer); the read-only investigation app is the
generic `swmtplanner/dashboard/` viewer, which this planner hands its manifest
to.

### The manifest (this planner's concrete schema)

The dashboard's manifest **dataclasses** (`TableSpec` / `Column` / `ForeignKey`)
are generic and defined in `swmtplanner/dashboard/manifest.py`. This planner
builds the **concrete instance** — the single source of truth for its table set,
column types, primary keys, the FK graph, and the FK-topological insert order —
in its own `manifest` (under `planners/infinite/`). Both the writer (to lay out
INSERTs in order) and the dashboard app (handed this manifest, to drive FK
navigation / typing / the table list) use it. It is **not** derived from
`DebugLog.schema` — it adds column *types*, the FK-topological order, and one FK
link `DebugLog.schema` doesn't carry (see below).

### Tables

The ten `DebugLog` tables persist under `knit_`-prefixed physical names
(`db_name`) while keeping their logical `name` — `iteration_log`,
`cost_summary`, `inv_cost_detail`, `sched_cost_detail`, `priority_detail`,
`production`, `demand`, `unmet_demand`, `run_configs`, `iteration_states` — plus
the **`runs`** registry (`knit_runs`; run metadata; owns the auto-incremented
`run_id`; not a `DebugLog` table). `priority_detail` and `unmet_demand` are
key-less (their `order_by` is `move_id, item, week_idx` and `item, week_idx`
respectively). Logical columns are name-for-name identical to the `DebugLog`'s;
physically, each `datetime` column is its `_date`/`_time` INT pair.
The DB also defines two **views** — **`committed_sched`** and
**`committed_prod`** — the committed-move slices of `sched_cost_detail` /
`production` (each `INNER JOIN`ed to the committed `iteration_log` rows). They
are **read-only** (the writer never touches them) and the dashboard reads them.
Each exposes a **subset** of its base table's columns (dropping `move_id` and the
cost columns), and is **keyed by the identity column it carries over** — which is
also an **FK to `sched_cost_detail.activity_id`**, so a committed-view row drills
to its full scheduled-activity detail:

- `committed_sched` (`knit_committed_sched`) — `activity_id` (pk, FK →
  `sched_cost_detail.activity_id`), `machine`, `start`, `end`, `desc` (view
  `ORDER BY machine, start_date, start_time`). The view exposes `start`/`end` as
  their `_date`/`_time` INT pairs, like the base table.
- `committed_prod` (`knit_committed_prod`) — `knit_id` (pk, FK →
  `sched_cost_detail.activity_id`), `roll_id`, `job_id`, `item`, `start`, `end`,
  `lbs` (view `ORDER BY item, knit_id`); `start`/`end` likewise as INT pairs.

They are registered in the manifest as a **`VIEWS`** tuple (resolvable via
`spec_for_name`; each keyed, with an `order_by` that **overrides** the pk to keep
the view's display order) but kept out of the writable `TABLES`/`ALL_TABLES`.

### FK graph (from the DDL)

```
demand.run_id                       → runs.run_id
iteration_log (run_id, order_id)    → demand (run_id, order_id)       # order_id may be NULL
cost_summary (run_id, move_id)      → iteration_log (run_id, move_id)
inv_cost_detail (run_id, move_id)   → iteration_log (run_id, move_id)
inv_cost_detail (run_id, summary_id)→ cost_summary (run_id, summary_id)
sched_cost_detail (run_id, move_id) → iteration_log (run_id, move_id)
priority_detail (run_id, move_id)   → iteration_log (run_id, move_id)
production (run_id, move_id)         → iteration_log (run_id, move_id)
production (run_id, knit_id)         → sched_cost_detail (run_id, activity_id)   # NEW link: a knit IS a scheduled activity
unmet_demand.run_id                 → runs.run_id
```

The `production.knit_id → sched_cost_detail.activity_id` link is **not** in
`DebugLog.schema` (there `knit_id` is just `production`'s PK). The manifest adds
it, so the app can jump from a produced knit to its scheduled activity, and the
writer knows `production` must follow `sched_cost_detail`.

### Insert order (FK-topological)

Parents before children, so the real FK constraints hold:

```
runs → demand → iteration_log → cost_summary → inv_cost_detail
     → sched_cost_detail → production ; priority_detail , unmet_demand (after parents)
```

`demand` is built **last** in the `DebugLog` but must be inserted **before**
`iteration_log` (its `order_id` FK target). So the writer drives insertion from
the manifest's topological order, **not** `DebugLog.tables` declaration order.
Assumption the DDL bakes in: every non-NULL `iteration_log.order_id` appears in
`demand` (it does — `demand` has every regular + safety order; run-up jobs carry
`order_id = NULL`, allowed by the FK).

### The SQL Server schema (provided, user-owned)

The tool **only INSERTs** — never `CREATE`/`ALTER`. The schema below is the DDL
already run; the manifest mirrors it exactly (logical names; the `knit_` prefix
and the INT temporal columns are applied by the storage mapping). The writer
fails fast with a clear message if a table/column is missing.

- `knit_runs` — `run_id BIGINT IDENTITY PK`; `created_at_date INT` /
  `created_at_time INT` (the `created_at` **datetime pair — writer-supplied from
  the wall clock at persist time**; there is no server default); `start_date
  INT` (a **`date`**: YYYYMMDD, **no suffix** — the one date-only column);
  `total_score FLOAT`; `n_unmet INT`; `label NVARCHAR(255)`; `notes
  NVARCHAR(MAX)`.
- **Datetime pairs** (`<stem>_date INT`, `<stem>_time INT`, second precision;
  the stem drops a trailing `_date`): `knit_demand.due_date` / `due_time`,
  `knit_sched_cost_detail.start_date` / `start_time` / `end_date` / `end_time`,
  `knit_production.start_*` / `end_*` likewise,
  `knit_iteration_states.window_end_date` / `window_end_time`; the two views
  expose the same pairs.
- Keyed detail tables carry `PRIMARY KEY (run_id, <pk>)`: `demand(order_id)`,
  `iteration_log(move_id)`, `cost_summary(summary_id)`, `inv_cost_detail(icost_id)`,
  `sched_cost_detail(activity_id)`, `production(knit_id)`,
  `iteration_states(iteration_idx)`, `run_configs(kind, label)`.
- Key-less tables (`priority_detail`, `unmet_demand`) have only the `run_id` FK
  (no PK in the DDL — fine for INSERT-only).
- Reserved words (`rank`, `desc`, `start`/`end` — now `start_date` etc., `value`)
  are reserved in T-SQL too; the writer **bracket-quotes every identifier**
  regardless.

### Write path — `persistence.py`

A single module (under `planners/infinite/`) that persists a populated
`DebugLog` to SQL Server using `DebugLog`'s read API + the manifest. It reuses nothing
beyond the manifest and issues no `CREATE`/`ALTER`.

```
persist_run(
    debuglog, conn,                       # ConnConfig for the WRITER role
    *, start_date, total_score, n_unmet, label=None, notes=None,
) -> int                                  # the new run_id
```

`run.py` resolves the writer `ConnConfig` (from the `database` block's `writer`
sub-block; `ConnConfig`/`DatabaseConfigError`/the resolver are the generic ones
in `swmtplanner/dashboard/config.py`) and pulls the run-metadata scalars off the
`PlanReport`, so `persistence.py` stays decoupled from both the config-block
shape and the `PlanReport` type. `PersistenceError` is the module's error type.

**Algorithm**: connect as the writer through the dashboard's
`config.connect(conn, autocommit=False)` (pyodbc; the import is lazy so the pure
helpers import without the driver) → INSERT the `knit_runs` row with
**`OUTPUT INSERTED.run_id`** (T-SQL has no `lastrowid`; the row carries
`created_at_date`/`created_at_time` from `datetime.now()` and `start_date` as a
YYYYMMDD int) → `run_id = cursor.fetchone()[0]` → for each `spec` in the
manifest's FK-topological order, bulk-`executemany` its run-tagged rows in
chunks (e.g. 5 000) with **`cursor.fast_executemany = True`** → `commit`. On any
exception: `rollback` and raise `PersistenceError` naming the table; `close` in
a `finally`. A failed run leaves nothing behind.

**Pure helpers (no DB — the unit-test surface):** `to_sql(value)` (missing →
`NULL`; `pandas.Timestamp` → `datetime`; numpy scalar → native; else
passthrough), after which the **storage mapping** is applied per column
(`storage.to_storage` — a `datetime` cell becomes **two** cells, a `date` cell a
YYYYMMDD int); `insert_sql(spec)` (`INSERT INTO [knit_x] ([run_id], <physical
columns>) VALUES (?, ?, …)` — **`?` qmark placeholders**, every identifier
bracket-quoted, each `datetime` column expanded to its `_date`/`_time` pair);
and `project_rows(debuglog, spec, run_id)` (yield `(run_id, *storage_cells)` per
row with that expansion applied, exposing a keyed table's PK as a column via
`reset_index()` only when `index.name` is set; empty tables yield nothing). The
SQL text and the cell expansion are asserted directly in unit tests, so the
translation is proven without a server.

**`run.py` wiring**: the `--verbose` block resolves the writer `ConnConfig` from
`cfg['database']` (skip when absent), collects the required `--label` and (vi-
captured) notes, calls `persist_run(...)`, and echoes the new `run_id`.

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
coordination" above for the mechanisms.

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
  SQL Server store is the planner-owned write path (**Debug-log
  persistence to SQL Server** below); investigating it through a PyQt6 app is
  the generic, planner-agnostic dashboard (`swmtplanner/dashboard/`).

The full `DebugLog` table schema, keys/links, and population flow live in
`swmtplanner/debuglog/DESIGN.md`; the SQL Server schema + write path are in
**Debug-log persistence to SQL Server** below; the read-only viewer is
`swmtplanner/dashboard/DESIGN.md`. Delivers an audit trail that turns
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

### Phase 5 — changeover capacity

Rations tape-outs and pattern changes plant-wide (see "Changeover
capacity" above). Three steps, each run against the 2026-10-01 inputs
and compared with the plan before it:

1. **Feasibility.** `schedule/capacity.py` (`ChangeoverCapacity`,
   `CapacityView`); `plan_production(..., capacity=)` waits for slots and
   records `capacity_taken`; `State.capacity` and booking in
   `commit_move`; the run-config block; the manual planner's stagings
   overlay each other's bookings; the `changeovers` sheet and the Gantt
   strip. No new weights.
2. **Recovery cost.** `cheap_sets` and `urgent_by_item` on the context,
   the route machine lists, the stranding walk; the `recovery` weight and
   `cost_summary` label; the tape-out report columns.

A *slot scarcity* term — a charge per unit booked scaled by how full the
period was — was built between the two steps and taken out again: at a
small weight it changed no decision, at a large one it only spread
tape-outs across more days and made the plan worse, and consuming the
ration was never meant to cost anything in itself.

A *threading ration* — eleven threading bars a day covering every
re-thread, runouts included, with a tape-out placed only on a day that
had threadings left for its re-thread — was built after step 2 and taken
out again: the greedy commits in score order, not time order, so the
day's threadings went to whichever move scored first rather than to the
most urgent work, and runouts queued behind changeovers for days. The
team's limit is carried instead by the lower running efficiency
(`RUNNING_EFFICIENCY`, see `schedule/DESIGN.md`).

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
