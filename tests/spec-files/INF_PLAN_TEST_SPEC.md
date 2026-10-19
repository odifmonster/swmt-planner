# Specification of coverage of infinite planner tests

These tests target the `planners/infinite/` submodule across the phases
laid out in `planners/infinite/DESIGN.md`. Phase 1 covers the greedy
planner: state, costing, candidate enumeration, and the main loop.
Later phases (2: cross-cutting cost aggregates, 3: local search) get
their own sections once those phases are implemented.

## Phase 1

### 1.1 State

The state module is a thin container with two mutation operations,
`commit_move` and `advance_window`. The tests below verify those
operations against hand-built `Move`s — the "is the right plan
generated" question belongs to the candidate-enumeration section, not
here.

#### 1.1.1 Construction

1. The provided `machines`, `rls_items`, `start_date`, and `window_end`
   are stored as-is and accessible via the corresponding fields.
2. `window_advance_amount` defaults to 24h when omitted; a custom value
   is stored unchanged.
3. `carrying_avoidance_margin` defaults to 24h when omitted; a custom
   value is stored unchanged.

#### 1.1.2 `commit_move` routing

`Move.plan` is a `ProductionPlan(activities, jobs)`. `commit_move`
appends `plan.activities` to `machine.activities` (advancing
`current_status`), appends `plan.jobs` to `machine.jobs`, and registers
those same `Job` records on each `rls_item` (grouped by `job.item.id`)
via `register_jobs`. No activity by itself touches any `rls_item` —
only `Job` records do.

These tests are about `commit_move`'s routing; the per-type status-
update math and the `Job` / `Roll` construction are covered by
`tests/machine_tests.py`.

1. **Activity stream** — for each activity type (`Knit`, `Doff`, `Waste`,
   `TapeOut` over all three `bars`, `Hanging` and `Threading` over all
   three `bars`, the three changeover classes (`StyleChange` /
   `RunnerChange` / `PatternChange`), `Idle`): the activity appears in
   `machine.activities` and no `rls_item.jobs` is touched.
2. **Job records** — a plan whose `jobs` holds a `Job(item, rolls)`
   routes that `Job` into `machine.jobs` and into `rls_item.jobs` for
   `job.item.id` (item and rolls match). A move whose two jobs target
   two different items registers each on its own `rls_item`.
3. **Empty production** — a plan with activities but empty `jobs`
   leaves every `rls_item.jobs` untouched (and `machine.jobs` empty).

#### 1.1.3 Multiple `commit_move` calls accumulate

1. Two consecutive moves on the same machine: `machine.activities`
   lists both moves' activities in order; `current_status.as_of`
   advances correctly across both.
2. Moves on different machines update each machine independently; the
   untouched machine's `activities` are unchanged.
3. Two moves whose Jobs land on the same `rls_item` (e.g., the same
   item produced on two different machines): the `rls_item.jobs` list
   accumulates Jobs from both calls.
4. Two moves whose Jobs land on different `rls_item`s: each
   `rls_item.jobs` accumulates only its own Jobs; the others are
   untouched.

#### 1.1.4 Canonical run-up + transition + new-item plan

A single `Move` whose plan begins with a run-up of the machine's
current item, hits a beam runout, swaps to a new item, and produces the
new item. The plan's **activity stream** (`plan.activities`) is, in
order:

- `Knit`/`Doff` pairs of `A` — one per whole roll produced before the
  changeover (each roll is a `Knit` then its `Doff`). The run-up emits
  **whole rolls only** — no `Waste` of a partial roll (unlike the old
  fabric-waste model where a sub-half roll was discarded at the runout).
- changeover preamble for the leftover bars — a `TapeOut` and/or a
  zero-duration `Waste` (discarding a below-threshold yarn residue from a
  bar) plus a re-thread (`Hanging` + `Threading`) for each bar whose
  leftover yarn doesn't match `B`. Any preamble `Waste` is a yarn discard
  and produces **no** `Job`.
- the changeover activity (`StyleChange` / `RunnerChange` / `PatternChange`,
  selected by the machine's `is_new` and the `A`→`B` family comparison) —
  transition to the new item.
- `Knit`/`Doff` pairs of `B` — production of the new item.

and its **production records** (`plan.jobs`) are the run-up `Job(A)`
(the whole rolls of `A`) followed by the new-item `Job(B)`.

Built by calling `Machine.plan_production(B, lbs, start_at='next_runout')`
on a machine whose initial state has at least one whole roll of `A`
producible above the floor, with leftover yarn on the bars that does not
match `B` (so the changeover preamble does real beam work).

After `commit_move`:

1. `machine.activities` contains all of the above activities in order;
   `machine.current_status` reflects the post-plan state (new beam(s)
   loaded, `current_item == B`, beam lbs decremented by B's
   consumption).
2. `machine.jobs` contains both `Job` records (`Job(A)` then `Job(B)`).
3. `state.rls_items[A.id].jobs` contains the run-up `Job(A)`.
4. `state.rls_items[B.id].jobs` contains the new `Job(B)`.
5. Each `rls_item`'s safety and raw views have been recomputed with
   their respective jobs — the relevant orders' `allocated_lbs`
   reflects the new commitment, and view-level cost trackers
   (`lateness`, `drainage`, `carrying`, `excess`, `safety_pool`)
   reflect the post-commit values rather than the pre-commit ones.

#### 1.1.5 `advance_window`

1. `advance_window()` extends `window_end` by `window_advance_amount`.
2. Two consecutive `advance_window()` calls extend cumulatively
   (`window_end + 2 × window_advance_amount`).
3. A `State` constructed with a custom `window_advance_amount` advances
   by that value, not the default.

#### 1.1.6 `State.capacity` and booking

1. **Default** — a `State` built without `capacity` holds a
   `ChangeoverCapacity` with no resources: `limits('tape_out')` and
   `limits('change')` are None and nothing is ever booked.
2. **Booking on commit** — committing a move whose plan carries
   `capacity_taken` books each slot's units on `state.capacity`
   (`booked(kind, day)` rises by `units`); a plan with no slots books
   nothing.
3. **Candidates read the bookings** — with the tape-out ration in place
   and the day's units booked, `enumerate_candidates` returns a
   changeover candidate whose plan waits (an `Idle` with a reason before
   its `TapeOut`), while a continuation candidate on the same machine
   does not.

### 1.2 Costing

`Costing.score` and `Costing.score_after_move` are weighted sums of
values that have already been computed and tested elsewhere (demand
views' cost trackers, machine activity counts and `Idle` durations).
Coverage here verifies that the right quantities are combined with the
right weights and that `score_after_move` stays pure — not the
underlying numerics themselves, which are covered by the demand-view
and machine tests.

A few scenarios suffice, arranged so each of the eleven Phase-1 weights
produces a non-trivial contribution at least once (the single
`family_change` weight is now three: `style_change` / `runner_change` /
`pattern_change`). In each test below,
the weights for *covered* components are set to distinguishable values
(e.g., 1, 10, 100) so a misweighting shows up as a wrong total; the
other weights are set to 0.

#### 1.2.1 Lateness, drainage, single tape-out, idle

Setup:
- An `RlsItem` with `on_hand_lbs` well below its `safety_target` so
  that no jobs results in non-zero `drainage` against the safety view.
- A machine whose committed plan contains a `TapeOut('top')` (or
  `'btm'`), a re-thread (`Hanging` + `Threading`, both unweighted), an
  `Idle` of known work-hour duration, and a `Knit` whose `Job` record has
  a roll completing past the earliest order's `due_date` (producing
  non-zero `lateness` in the raw view).

Assert: `score(state)` equals
`w_lateness × raw_view.lateness + w_drainage × safety_view.drainage
+ w_tape_out_single + w_idle_time × idle_work_hours`.

Components covered: `lateness`, `drainage`, `tape_out_single`,
`idle_time`.

#### 1.2.2 Changeover types and double tape-out

The single `family_change` weight split into three by changeover class
(`style_change` = new machine; `runner_change` = legacy same-family;
`pattern_change` = legacy cross-family). Each sub-case isolates one
changeover weight (and, in the first, `tape_out_both`); the re-thread
(`Hanging` + `Threading`) is unweighted, and all four demand-view
trackers are 0 (no unmet weekly demand, safety pool at target).

1. **Legacy cross-family full changeover** — a legacy machine whose
   committed plan is the canonical full changeover: `TapeOut('both')`, a
   `'both'` re-thread, and a `PatternChange`. Assert `score(state)
   == w_tape_out_both + w_pattern_change`. Covers `tape_out_both`,
   `pattern_change`.
2. **Legacy same-family changeover** — a legacy machine transitioning to
   a same-family item with different yarn (so beam work occurs); the
   changeover is a `RunnerChange`. With the `tape_out_*` weights set to 0,
   assert `score(state) == w_runner_change`. Covers `runner_change`.
3. **New-machine changeover** — a `Machine(is_new=True)` whose plan
   contains a `StyleChange` (the only changeover class a new machine
   emits, regardless of family). Assert `score(state) == w_style_change`.
   Covers `style_change`.

#### 1.2.3 Waste (discarded yarn)

Setup:
- A machine whose committed plan contains one or more `Waste` activities
  with known `lbs` (e.g. a changeover preamble that discards a
  below-threshold leftover bar, or a production-loop max-waste swap).
- No other schedule-side contributions and no demand-side contributions
  (every other covered weight set to 0).

Assert: `score(state)` equals `w_waste_lbs × Σ Waste.lbs` summed across the
machine's `Waste` activities. Because `Waste` is zero-duration, it
contributes nothing to `idle_time` or any time-based term — only the per-lb
charge.

Components covered: `waste_lbs`.

#### 1.2.4 Excess

Setup:
- An `RlsItem` whose committed jobs total more than weekly demand plus
  the safety target, so `safety_view.excess > 0`.
- No schedule-side contributions (no `TapeOut`, no changeover, no
  `Idle`, no `Waste`).

Assert: `score(state)` equals `w_excess × safety_view.excess`.

Components covered: `excess`.

#### 1.2.5 Carrying

Setup:
- An `RlsItem` with a committed `Job` whose rolls all complete well
  before the target order's `due_date - lead_time`, so
  `safety_view.carrying > 0`.
- No schedule-side contributions.

Assert: `score(state)` equals `w_carrying × safety_view.carrying`.

Components covered: `carrying`.

#### 1.2.6 `score_after_move`

For any of the above scenarios (or a similar one), with a chosen
`Move`:

1. **Equivalence**: `Costing.score_after_move(state, move)` returns
   the value that `Costing.score(state)` returns *after*
   `state.commit_move(move)`. Compute both and assert equality within
   float tolerance.
2. **Purity**: snapshot every `machine.activities` and every
   `rls_item.jobs` in the state before calling `score_after_move`;
   verify they're unchanged after the call returns. Also verify the
   view trackers (`raw_view.lateness`, `safety_view.drainage` /
   `carrying` / `excess` / `safety_pool`) are unchanged.

#### 1.2.7 Priority cost

The priority cost is the opportunity-cost estimate the cost layer
charges per move for deferring higher-priority regular orders — see
"Priority cost" in `planners/infinite/DESIGN.md` for the full
formula. Each scenario below asserts on
`Costing._priority_cost(move, ctx)` directly so other weights don't
have to be zeroed (set `w.priority = 1.0` for ease of comparison).

The setups share a four-item state chosen so the priority sort lands
in a predictable order:

- **`U_LOW`** — `safety = 0`, week-1 unmet (urgent at the default
  `reference_week_idx = 1`). The `safety_target == 0` convention
  resolves its safety ratio to `0.0`, so it ranks ahead of any other
  urgent regular sharing its due date.
- **`U_HIGH`** — same week-1 due date as `U_LOW`, but `safety > 0`
  and `on_hand` sized to fill the safety pool to target before
  bucket-1 demand exhausts (e.g. `weekly=[300, 200, 0, 0]`,
  `on_hand=400`, `safety=100`). Safety ratio = 1.0, so it ranks
  behind `U_LOW` within the urgent bucket. No safety order emitted.
- **`SAFETY`** — all weekly demand met; `safety > 0` with `on_hand`
  sized to leave the pool below target. Emits one `SafetyOrder` and
  no regular order.
- **`FUTURE`** — `safety = 0`, week-3 unmet (future regular at
  `reference_week_idx = 1`).

Expected priority ordering: `U_LOW.reg` (rank 1), `U_HIGH.reg`
(rank 2), `SAFETY.safety` (rank 3), `FUTURE.reg` (rank 4).

For all four scenarios, the state has two machines (so
`ctx.earliest_dp_excluding[move.machine_id]` resolves to the other
machine's DP), with the other machine's DP set six days before the
week-1 due date — the predicted fill is that DP plus one week, so every
higher-priority urgent regular is predicted exactly one day late,
`lateness_factor(1) = 1`, and its per-order contribution is its unmet
share of the week, `O.lbs / O.gross_lbs` (1.0 for both `U_LOW` and
`U_HIGH`, whose week-1 demand is entirely unmet).

1. **Highest-ranked move pays no priority cost** — move targets
   `U_LOW`'s week-1 regular (rank 1). No higher-priority order
   exists. Assert `breakdown.priority == 0.0`.

2. **Same-urgency, less-depleted move pays for the more-depleted
   sibling** — move targets `U_HIGH`'s week-1 regular (rank 2). The
   only higher-priority order is `U_LOW.reg`. Assert
   `breakdown.priority == w.priority × (U_LOW.reg.lbs / U_LOW.reg.gross_lbs)
   × lateness_factor(1)` = `w.priority × 1.0`.

3. **Safety move pays for both urgent regulars** — move targets
   `SAFETY`'s safety order (rank 3). The higher-priority pool is
   `U_LOW.reg` and `U_HIGH.reg` (both urgent regulars). Assert
   `breakdown.priority == w.priority × (U_LOW share + U_HIGH share)` =
   `w.priority × 2.0`.

4. **Future-regular move pays the same as the safety move** — move
   targets `FUTURE`'s week-3 regular (rank 4). Higher-priority entries
   are `U_LOW.reg`, `U_HIGH.reg`, and `SAFETY.safety`; the safety
   order is filtered out by the regulars-only scope and contributes
   nothing. Assert `breakdown.priority` equals scenario 3's value —
   `w.priority × 2.0`. Confirms
   safety orders are skipped in the opportunity-cost sum.

#### 1.2.8 Recovery cost

`Costing.recovery_detail(state, move, ctx)` (see "Changeover capacity —
Recovery cost" in the planner design) and the context builders
`build_cheap_sets` / `build_urgent_by_item` / `cheap_set_after`. A
24/7-calendar state with the plant's ration; items that share one yarn
across two pattern families plus one item on a yarn of its own; old and
new machines whose mounted sets are built explicitly.

1. **Cheap sets** — a new machine's cheap set is every item on its yarn;
   an old machine's is its yarn and its current pattern family; an item
   that cannot run on the machine is excluded; `cheap_set_after` for a
   move to another yarn is that yarn's items (family-filtered on an old
   machine); a machine on an item it cannot run has an empty cheap set.
2. **Urgent orders** — `build_urgent_by_item` lists each item's
   remaining-lbs orders through the reference week only, with `lbs` the
   remaining and `gross_lbs` the week's demand, and omits items with
   nothing open.
3. **Nothing lost** — a runner change, a new machine's style change, or
   a move to an item in the same cheap set strands nothing: quantity 0.
4. **Covered elsewhere** — a tape-out off a yarn whose other cheap
   machines can make the open demand by its due date: quantity 0.
5. **Last machine, tape-out route only** — the only machine on a unique
   yarn leaves it with open demand: the other machines are all on other
   yarns, so the fill is the next free both-bar tape-out slot after the
   earliest tail (plus a pattern slot when that machine is old and in
   another family) plus a week, and the quantity is
   `Σ uncovered / gross × lateness_factor(days late)`.
6. **Route weighting** — one new machine on the yarn and two old ones in
   another family: the style route carries weight 1/3 at the horizon, the
   pattern route 2/3 at the next pattern slot, each plus a week; the
   quantity is the weighted sum. Booking the day's pattern slots pushes
   the pattern route's fill and raises the quantity.
7. **Partial coverage** — the remaining cheap machines cover the first
   order but not the second: only the second order's shortfall is
   charged.
8. **Capacity walk is sequential** — the same machine's hours are not
   counted twice across two orders of the item.
9. **Memoised and reported** — two moves on the same machine to the same
   item return the same object from `ctx.recovery_cache`; a context with
   no cheap sets scores 0; `score_after_move` with only `recovery`
   non-zero equals `w.recovery × quantity`; the debug `cost_summary`
   carries a `recovery` row of kind `other`.
10. **An item the machine cannot run** — an old machine set up for `RY2`
    (which cannot run on it): any move on it has quantity 0 with nothing
    stranded; and with a new machine on `RY1` leaving yarn Y against
    `RY1`'s week-1 demand, that machine does not count as cover (the
    quantity is positive), where the same machine on `RY1` would (0).

### 1.3 Candidate enumeration

The `loop/candidates.py` module exposes three functions:
`eligible_decision_points`, `eligible_orders`, and
`enumerate_candidates`. The two listing functions are covered below.

#### 1.3.1 `eligible_decision_points`

1. **Empty state** — no machines in `state.machines`. Output: `[]`.

2. **All machines' decision points out of window** — every machine has
   `schedule_tail > state.window_end` (and therefore
   `next_runout > state.window_end` too). Output: `[]`.

3. **Single machine, both DPs in window, distinct** — beams partially
   used so that `next_runout > schedule_tail`, both within
   `window_end`. Output: two `DecisionPoint`s, one with
   `start_at='schedule_tail'` (time = `current_status.as_of`), one with
   `start_at='next_runout'` (time = `machine.next_runout`).

4. **Single machine, both DPs in window, coinciding** — beams empty,
   so `next_runout == schedule_tail`. Output: a single `DecisionPoint`
   with `start_at='schedule_tail'`; the `next_runout` entry is
   deduplicated.

5. **Single machine, `schedule_tail` in window, `next_runout` out** —
   beams full enough that the forward-extrapolated runout is past the
   window's end. Output: a single `DecisionPoint` with
   `start_at='schedule_tail'`. (The asymmetric "runout in, job_end out"
   case is impossible by `next_runout >= schedule_tail`, so no test for
   it.)

6. **Multiple machines** — state contains several machines, at
   least one in each of the four single-machine states above
   (excluding the "no machines" empty case). Verify each machine's
   contribution lands in the output and machines whose decision points
   are entirely out of window contribute nothing.
    1. All decision points of all machines in window.
    2. Only the next job decision point of all machines in window.
    3. Various subsets of machines where all machines in the subset
       have both decision points in window.
    4. Various subsets of machines where all machines in the subset
       have exactly one decision point (schedule_tail) in window.
    5. Various subsets that have a mix of decision points in window.

#### 1.3.2 `eligible_orders`

For each scenario below, verify the output in two configurations and
confirm both produce the same list of `RegularOrder` / `SafetyOrder`
records (modulo small float tolerance on `lbs`):

- **(a) start state**: construct each `RlsItem` directly in the target
  state via its constructor (`on_hand_lbs`, `weekly_lbs_needed`, item
  `safety`). No jobs registered.
- **(b) via jobs**: construct each `RlsItem` from a baseline (e.g.,
  zero `on_hand`, full demand) and call `register_jobs` to drive the
  RlsItem's views into the same target state.

Each emitted order's `order_id` is also asserted — it is the demand-layer id
the planner threads into `plan_production` as `tgt_order`, captured straight
off the demand object rather than rebuilt: a `RegularOrder` carries the
corresponding `SafetyAwareOrder.id` (`P{week_idx}@{item_id}`), a `SafetyOrder`
the view's `Safety.id` (`S@{item_id}`).

**At most one order per item**, chosen by precedence: **(1) urgent regular** —
the earliest unmet order with `week_idx <= state.reference_week_idx`; else
**(2) safety** — a `SafetyOrder` when the safety pool is below target; else
**(3) future regular** — the earliest unmet order (necessarily past the
reference week). So an item only gets a safety order once its urgent orders are
met *and* it is below safety target; otherwise it gets a regular order.

1. **Fully satisfied item** — no unmet weekly demand and safety pool
   at-or-above target. Output: `[]`.

2. **Unmet week-0 demand only** — week 0 has positive `remaining_lbs`
   in the safety view; weeks 1–3 have zero; safety pool at target.
   Output: one `RegularOrder` for week 0 with the unmet lbs.

3. **Safety below target only** — all weekly orders fully met but
   safety pool below the target. Output: one `SafetyOrder` with lbs =
   `safety_target - safety_pool`.

4. **Urgent regular suppresses safety** — an urgent unmet order (week 0)
   AND safety below target. The urgent regular wins: output is the single
   `RegularOrder` (week 0); the safety order is **suppressed** (one order
   per item).

5. **Earliest-unmet selection** — multiple weeks have unmet demand
   (e.g., week 0 partially unmet, weeks 1–3 fully unmet). Output's
   `RegularOrder` corresponds to the lowest `week_idx` with positive
   `remaining_lbs`. Only one regular order per item, regardless of how
   many weeks are unmet.

6. **Future regular when safety met** — unmet demand only *past* the
   reference week (default 1) with the safety pool at target (e.g. a
   `safety=0` item). Output: one `RegularOrder` for the earliest unmet
   (future) week — the future-regular bucket.

7. **Safety precedes future regular** — no urgent order (unmet only past
   the reference week) **and** safety below target. Output: the single
   `SafetyOrder`; the future regular is suppressed.

8. **Reference week promotes a regular over safety** — the same state as
   scenario 7 but with `reference_week_idx` raised to include that week:
   the order is now *urgent*, so it suppresses the safety order. Output:
   the single (now urgent) `RegularOrder`. (Single config — exercises the
   `reference_week_idx` boundary directly.)

9. **Multiple items, mixed states** — state contains several
   `RlsItem`s, each in a different scenario from 1–7. Output includes
   the appropriate single order for each `RlsItem`, with no cross-talk.
   (Configuration (b) is the natural single test here — the
   constructor-only version is what the earlier scenarios already cover.)

#### 1.3.3 `enumerate_candidates`

1. **Target filtering and idling correctness only**
   - the machine/product configuration for these tests will adhere to the
   following principle: for some greige family $G$, there is a set of machines
   $M_g \subseteq M$ such that for all $g \in G$ and for any machine $m \in M$,
   `g.can_run_on_machine(m)` iff $m \in M_g$. That is, the set of machines can be
   divided into equivalence classes based on what family of greige styles they
   can run.
   - the initial status of all machines and the order sizes should be set such
   that every order can be completed within the week they are targeting.
   - no calls to plan_production emit schedules with runouts
    1. **Trivial case**
       - all greige items belong to the same family.
       - there is one machine programmed to run each item at the start state.
       - no orders trigger idling before production begins.
       - orders assigned to the machine already programmed for that item produce a single `Job` record (one `plan_production` call, no run-up).
    2. **Multiple family case** - assert that no order gets assigned to a
       machine that can't run it, otherwise same setup as in part 1.
    3. **Idling case** - mix of orders across weeks such that some pairs will
       force a machine to idle before production.
2. **Orders correctly capped at one week of production**
   - these tests verify `move.lbs` reflects the producible-in-week cap
   reported by `Machine.producible_lbs_in_week` for the
   `(item, year, week, start=effective_start)` query corresponding to
   the candidate. Setup arranges `order.lbs` large enough that the
   producible cap is the binding constraint (not the order size).
   - covers cases where the existing schedule restricts available
   hours, and where preamble activities (forced run-up, tape-outs,
   changeovers, carrying-avoidance idle) restrict hours.
   - each whole roll costs `per_roll = tgt_wt / rate + DOFF_DURATION`
   work-hours (its knit **plus** its doff), so the roll counts below
   divide the available hours by `per_roll`, not by `tgt_wt / rate`.
    1. **Mid-week schedule tail** — `current_status.as_of` falls
       partway through the current ISO week, leaving partial remaining
       hours. Order's item matches the current item so there's no
       preamble work. `move.lbs` equals
       `floor(remaining_work_hours / per_roll) × tgt_wt`.
    2. **Full changeover preamble** — machine's current item differs
       from the order's in both bars' yarn and in family, forcing
       `TapeOut('both') + a 'both' re-thread (Hanging + Threading) +
       PatternChange` (legacy cross-family) in the preamble. `as_of =
       week_start` so the preamble is the only restriction. `move.lbs`
       equals `floor((week_work_hours - preamble_hours) / per_roll) ×
       tgt_wt` where `preamble_hours = TAPE_OUT_BOTH_DURATION +
       HANGING_BOTH_DURATION + THREADING_BOTH_DURATION +
       PATTERN_CHANGE_DURATION`.
    3. **Carrying-avoidance idle inside the week** — regular order
       whose `due_date - lead_time - margin` falls partway through the
       same ISO week as the decision point. `effective_start` advances
       to that target via the carrying-avoidance idle; with under three
       work days of that week left the cap window runs through the end
       of the following week, so `move.lbs` equals `floor(((next_week_end
       - effective_start) work hours - preamble_hours) / per_roll) ×
       tgt_wt`.
    4. **`'next_runout'` decision point inside the week** — current
       item has partial beams at `as_of = week_start` such that
       `next_runout` falls midway through the week. Order's item shares
       yarn **and** family with the current item so the preamble is a
       single same-family changeover (a `RunnerChange` on a legacy
       machine). `move.lbs` equals `floor(((week_end - next_runout) work
       hours - RUNNER_CHANGE_DURATION) / per_roll) × tgt_wt`. (The cap
       simulation idles from `as_of` to `next_runout` rather than running
       the current item, but the post-`next_runout` budget is the same.)
    5. **Three-day rule** — the cap window is the current ISO week when
       at least `3 × workcal.hours_per_day` work hours of it remain at
       `effective_start`, and runs through the end of the following week
       when fewer do: on the 24/7 calendar a Friday 00:00 tail (72 h
       left) caps at the week, a Friday 01:00 tail (71 h) at next week's
       end; a tail 30 minutes before the week ends, where not even one
       roll would fit, extends likewise.
3. **`'next_runout'` skipped for the machine's current item**
   - Separate setup from §1.3.3.1/.2 (those are arranged so no decision point
     is a `next_runout`). A machine is left mid-run on item `X` with partial
     beams so its `next_runout` is in-window and distinct from `schedule_tail`,
     and `X` itself has unmet demand (so `eligible_orders` emits a
     `RegularOrder` for `X`). A second item `Y` the machine can run also has
     unmet demand.
   - `enumerate_candidates` must **not** emit the (`next_runout`, `X`-order)
     candidate — `plan_production` rejects a same-item `next_runout`. The skip
     is specific to the current item, not a blanket `next_runout` drop. Verify:
       1. no candidate has `start_at == 'next_runout'` and `item == X`
       2. the `schedule_tail` candidate for `X` on that machine **is** present
          (continuing the current item is still enumerated)
       3. a `next_runout` candidate for `Y` (a different in-window item the
          machine can run) **is** present
       4. `enumerate_candidates` returns normally — no `ValueError` escapes

4. **Economic order quantity** (`coordination.unique_setups`, the batching
   in `enumerate_candidates`; "Economic order quantity for unique setups"
   in DESIGN.md)
   1. **`unique_setups`** — the ids of the demand items whose top/bottom
      physical beam-set pair no other demand item shares: a lone item is
      unique; two items on the same yarn are not; a split-lease label and
      its plain twin are the same setup.
   2. **A small unique move is batched** — a unique-setup item with 100 lbs
      a week over six weeks (open demand 2 rolls) is sized to 400 lbs,
      weeks 0 to 3, while its `week_idx`, `order_remaining_lbs` and
      `tgt_order` stay those of the earliest order.
   3. **Not capped at the week** — the same item at 1 lb/h, whose week's
      producible cap is under a batch, is still sized to 400; with
      `eoq_threshold_rolls = 0` (batching off) the move is the capped size.
   4. **All demand pulled in, rounded down** — 60 lbs a week over four
      weeks batches to 240 lbs and the move is 2 whole rolls.
   5. **Above the threshold** — 200 lbs a week (4 open rolls) is sized as
      before, 400; with `eoq_threshold_rolls = 4` and `eoq_batch_rolls = 6`
      it is batched to 600.
   6. **Shared setups and safety orders are not batched** — an item whose
      setup another demand item shares is sized to its open demand; a
      safety order is sized to its gap.

#### 1.3.5 Filling a slot wait

`candidates.fill_for` and the fill the candidates are planned with (see
"Filling a slot wait" in the planner design).

1. **Sizing** — for a machine on `A` changing to `B`: with `A` open 150
   lbs in week 1 and 100 in week 3 and no safety gap, `fill_for` is
   `Fill(3, 'P1@A')` (rounded up to whole rolls, against the earliest open
   order); with only a safety gap of 250, `Fill(3, 'S@A')`; with both, the
   sum of rolls against the regular order.
2. **None** — for a move continuing the current item, a machine with no
   item, an item the run does not have, an item with nothing open, or a
   machine on an item it cannot run (open demand or not).
3. **Candidates carry the fill** — with the day's changes booked, a
   changeover candidate's plan knits the current item while it waits: a
   `fill` job of the current item precedes the new item's job in
   `plan.jobs` and the wait is shorter than the fill-less plan's; a
   continuation candidate on the same machine has no fill job.

#### 1.3.6 A machine on an item it cannot run

`_ITEM_X`: `_ITEM_A`'s yarn and family, runnable on `M2` only; `M1` set
up for it with full bars, with open demand on both `_ITEM_X` and
`_ITEM_A` (see "An item the machine cannot run" in `schedule/DESIGN.md`
and the planner design's Inputs).

1. **One decision point** — `eligible_decision_points` lists only
   `('M1', 'schedule_tail', start)`: the runout coincides with the tail.
2. **Open to what it can run** — every candidate is for `_ITEM_A` at
   `schedule_tail`; none has a job of `_ITEM_X` (no run-up, no fill).

### 1.4 Main loop

The `plan(state, costing)` function orchestrates the greedy loop:
enumerate → score → commit-lowest, advancing the decision window when
the candidate pool drops below `state.candidate_threshold` until the
horizon is reached. The underlying operations
(`enumerate_candidates`, `score_after_move`, `commit_move`,
`advance_window`) are tested in earlier sections; tests here verify
the loop's orchestration behavior.

#### 1.4.1 Termination

Verify the loop terminates without hanging in each of:

1. **Empty state** — `state.machines = {}`, `state.rls_items = {}`.
   Returns immediately with an all-empty `PlanReport` (empty `dict`s
   for `schedules`, `jobs_by_item`, etc.; `total_score == 0.0`).
2. **No machines** — `rls_items` present but `machines = {}`. Returns
   immediately; `unmet_lbs_by_item_week` lists every week's full
   demand for every item.
3. **All demand pre-satisfied** — `on_hand_lbs` for each item already
   covers its demand plus safety. No candidates ever emerge; the loop
   returns having committed nothing.
4. **Re-running on a completed state** — call `plan` twice in
   sequence on the same `(state, costing)`. The second call commits
   no new moves; `schedules`, `jobs_by_item`, `total_score`,
   `cost_components_by_item`, and `unmet_lbs_by_item_week` match
   between the two reports. (`state.window_end` may differ by at most
   one advance step.)

#### 1.4.2 Demand fully placed (capacity available)

Given a plant whose capacity exceeds total demand + safety:

1. **Single item, single machine** — total scheduled lbs (sum of
   `job.total_lbs` over `report.jobs_by_item[item_id]`) ≥
   `sum(weekly_lbs_needed) + item.safety`. Every
   `safety_view.orders[i].remaining_lbs == 0` on
   the post-plan rls_item. `unmet_lbs_by_item_week` is empty.
2. **Single item, multiple eligible machines** — committed activities
   appear on more than one machine (the window mechanism spreads
   work). Total scheduled lbs still ≥ demand + safety.
3. **Multiple items, multiple machines** — each item's demand and
   safety placed; per-machine eligibility is honored (no machine
   commits an item not in its `machines` dict).

#### 1.4.3 Capacity-bound (some demand unmet)

Given a plant whose capacity within the horizon is less than total
demand + safety:

1. **Single bottleneck** — one item with more demand than its
   eligible machines can produce. `unmet_lbs_by_item_week` reflects
   the shortfall; the loop nevertheless commits everything it can
   before terminating.
2. **Item with no eligible machines** — an `RlsItem` whose
   `item.machines` dict shares no keys with `state.machines`. The
   item appears in `unmet_lbs_by_item_week` with the full weekly
   demand (no commits for it). Other items in the state are still
   handled normally.
3. **Tight horizon** — `state.planning_horizon_buffer` set short
   enough that not all demand can be placed before the horizon. The
   loop terminates without advancing past the horizon; whatever
   couldn't be placed surfaces in `unmet_lbs_by_item_week`.

#### 1.4.4 Window advancement

1. **Narrow initial window** — `state.window_end = state.start_date`.
   Fresh machines have `schedule_tail == start_date` and are initially
   in window. After commits push `schedule_tail` past `window_end`,
   the loop calls `advance_window()` to bring more decisions in.
   Verify multiple advances occur during plan execution (e.g.,
   snapshot `state.window_end` before and after `plan`; it should
   have advanced past the initial value).
2. **Threshold-driven advancement** — `state.candidate_threshold`
   set to a value greater than the initial in-window candidate count.
   The loop advances the window aggressively to refill the pool.
   Verify the final `state.window_end` is at or past the value it
   would be if `candidate_threshold == 1`.
3. **Loop stops at horizon** — after `plan` returns,
   `state.window_end <= horizon + state.window_advance_amount` where
   `horizon = _compute_horizon(state)`. A single-step overshoot is
   expected because the loop checks `window_end < horizon` *before*
   advancing.

#### 1.4.5 `PlanReport` snapshot fidelity

For any non-trivial scenario, verify:

1. `report.schedules[m_id]` equals `state.machines[m_id].activities`
   for every machine.
2. `report.jobs_by_item[item_id]` equals
   `state.rls_items[item_id].jobs` for every item.
3. `report.total_score` equals `costing.score(state)` on the post-loop
   state.
4. `report.cost_components_by_item[item_id]` matches each rls_item's
   view trackers (`raw_view.lateness`, `safety_view.drainage`,
   `safety_view.carrying`, `safety_view.excess`).
5. `report.unmet_lbs_by_item_week` contains exactly the (item_id,
   week_idx) pairs where the corresponding
   `safety_view.orders[week_idx].remaining_lbs > 0`, with matching
   lbs values. Pairs with `remaining_lbs == 0` are omitted.
6. `report.rls_items[item_id]` is each item's `RlsItem` (the same object
   `state.rls_items` holds), and its `on_hand_coverage` reflects the
   initial on-hand allocation: for a scenario with positive `on_hand`,
   the covered lbs per order id match the jobs=`[]` allocation (e.g.
   `on_hand` filling week 0 then safety), and `demand - covered` gives
   the remaining-after-on-hand the `demand` sheet reports. (Only the
   `PlanReport` data is checked — the Excel rendering is verified by
   running the program, not in unit tests.)


### 1.5 Changeover report

`report.changeovers_dataframe` over a `PlanReport` (see "Reporting" under
"Changeover capacity" in the planner design).

1. **No ration** — a report whose `capacity` is None or unrationed yields
   an empty frame with the sheet's columns.
2. **Period rows** — one `period` row per `(resource, day)` with a booked
   activity: `capacity` is `units_per_period`, `used` sums the units (a
   `'both'` tape-out counts 2), `activities` lists `machine:id@HH:MM`;
   rows are ordered by day then resource.
   **Change rows** — with the change cap rationed, one `change` unit per
   preamble that changed the machine, listed by its opening tape-out when
   there was one: a both-bar tape-out followed by a pattern change counts
   one change at the tape-out, a tape-out followed by a knit (no
   changeover) counts one, a runner change alone counts one; a wait row
   for an `Idle(reason='change slot')` carries `change`.
3. **Wait rows** — one `wait` row per `Idle` with a `reason`: `resource`
   is the reason without the ` slot` suffix, with `machine`, `start`,
   `end`; a caller idle (no reason) produces no row.
4. **Schedule JSON** — an `Idle` with a reason serialises it under
   `reason`; one without omits the key.
5. **Schedule sheet** — such an idle's `desc` reads `waiting for tape_out
   slot`.

### 1.6 Idle machines left out of the outputs

`schedule_json.has_work` and the writers that use it.

1. `has_work` is False for an empty schedule and for one holding only
   `Idle` activities (with or without a `reason`), True once any other
   activity is present.
2. `schedule_json` and `machines_schedule_json` omit a machine whose
   schedule is idle-only and keep one with work, in the report's order.
3. `schedule_dataframe` and `collapsed_schedule_dataframe` have no rows
   for an idle-only machine.

### 1.7 Assigned sets passed over in the outputs

`build_report`, `run.passed_over_lines` and the schedule JSON.

1. **Report** — `build_report(...).queue_passed_over` maps each machine
   with a non-empty `Machine.queue_passed_over` to that tuple and leaves
   out machines with none; empty when no machine passed anything over.
2. **Run lines** — `passed_over_lines(report)` is empty for an empty
   mapping; otherwise a header counting the sets and one line per set in
   machine order giving machine, bar, hang time, the set number, its
   description and merge (`?` for an unknown merge), the requirement it
   failed and the reason (`does not fit` / `blacklisted`).
3. **Schedule JSON** — a `Hanging` with `passed_over` serialises it as a
   list of `{bar, set_no, merge, vendor, desc, lbs, reason}`; a `Hanging`
   that passed nothing over has no `passed_over` key.
5. **Blacklisted sets** — a beam-set object carries `"blacklisted": true`
   when the set is, and no such key otherwise: the `TapeOut` that takes a
   blacklisted mounted set off a bar shows it, and a passed-over queued
   set's entry reads `reason: blacklisted`.
6. **Hung and queued sets** — a beam-set object carries `"location"`
   (`staged` / `inventory`) for a plant-queued set and no such key
   otherwise; an `Unhang` serialises `bars`, `top_beam`, `btm_beam` like a
   `TapeOut`; the xlsx `desc` of an `Unhang` reads `unhung, never
   threaded: …` with the set and its lbs back.
4. **Knit sets** — a `Knit` serialises `top_beam` / `btm_beam` as
   beam-set objects (null for a bar that held nothing), and the xlsx
   `desc` for a knit reads `<item> [<variant>] top #<set> <merge> / btm
   #<set> <merge>`.

### 1.8 Sticking to the prior plan

`State.prior`, `run.prior_commits`, `loop.recommit_prior`, the
`prior_jobs` sheet and the JSON fields (see "Sticking to the prior plan"
in `planners/infinite/DESIGN.md`). Fixtures: the in-memory state of 1.1
(`_make_machine`, `_make_rls_item`), items `A` and `B` with regular
orders in weeks 1 and 2, `PriorCommit`s built by hand.

1. **`prior_commits`** — prior jobs with a target order and rolls left
   become `PriorCommit`s per machine in start order; run-up jobs (no
   order) and zero-roll jobs are left out; a machine with none has no
   entry.
2. **Recommitting** — `M1` has a prior `A` job of 2 rolls and `A` has
   100 lbs open in week 1: `recommit_prior` commits the rolls on `M1` at
   its schedule tail with the week-1 order's id as `tgt_order` and the
   prior job's id as `Job.prior_job`, marks it `consumed` with the new
   job's id, returns 1, and the order's remaining lbs fall by the rolls'
   weight; a second call commits nothing.
3. **Order of the walk** — prior jobs on two machines are recommitted in
   prior start order across machines, not machine by machine.
4. **Not urgent** — a prior job for the week-2 order (past the reference
   week) is left `open` with note `not urgent` and nothing is committed
   for it; with `reference_week_idx = 2` it is recommitted.
5. **Filled** — a prior job whose order has no remaining lbs is
   `dropped (order filled)`; two prior jobs for one order where the
   first fills it leave the second dropped the same way.
6. **No such order** — a prior safety job (`S@A`), a job whose due date
   matches no order of the item, or a job for an item the run does not
   have is `dropped (no such order)`.
7. **Refused** — a prior job for an item the machine cannot run is
   `dropped` with the error and the walk goes on.
8. **The loop** — `plan` on a state with one urgent prior job commits it
   before its first scored iteration; `PlanReport.prior` lists every
   prior job with its status; `prior_jobs_dataframe` has one row per job
   with those columns and the xlsx carries the sheet only when `prior` is
   non-empty.
9. **Schedule JSON** — a job object carries `due_date` (its target
   order's, from `order_due_dates(report)`; null for a safety or run-up
   job) and `prior_job`; `retime.prior_jobs` reads `due_date` back into
   `PriorJob.due_date` and leaves it None when absent.
10. **The frozen window** — with `frozen_window = 1 day`, an urgent prior
    job starting two days in is left `open` with note `outside the frozen
    window` and nothing is committed; with a 3-day window, or none, it is
    recommitted.
11. **Fill in the pre-pass** — with the day's changes booked, a
    recommitted prior job that changes the machine's item knits the
    current item while it waits: the machine's jobs hold a `fill` job of
    the current item before the recommitted job.

### 1.9 Fills in the outputs

1. **Production sheet** — `production_dataframe` has a `fill` column,
   True for a job that filled a wait and False otherwise.
2. **Schedule JSON** — a job object carries `fill` (true / false).
