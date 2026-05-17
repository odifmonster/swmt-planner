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

#### 1.1.2 `commit_move` per activity type

Each test builds a `Move` whose plan contains the activity (or a small
sequence containing that activity), calls `commit_move`, and verifies
that the machine's `activities` and any affected `rls_item.jobs`
reflect the commit. Activities that don't produce a `Job` should
appear on the machine but should not touch any `rls_item`.

These tests are about `commit_move`'s routing behavior; the per-type
status-update math is already covered by `tests/machine_tests.py`.

1. `Job` — appears in `machine.activities`; the corresponding
   `rls_item.jobs` gains it; lbs and item match.
2. `Waste` — appears in `machine.activities`; no `rls_item` is touched.
3. `TapeOut` — covers all three `bars` values (`'top'`, `'btm'`,
   `'both'`). Each appears in `machine.activities`; no `rls_item` is
   touched.
4. `BeamLoad` — covers both `bar` values (`'top'`, `'btm'`). Each
   appears in `machine.activities`; no `rls_item` is touched.
5. `StyleChange` — covers both `is_family_change` values (`False`,
   `True`). Each appears in `machine.activities`; no `rls_item` is
   touched.
6. `Idle` — appears in `machine.activities`; no `rls_item` is touched.

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
new item. Specifically, in order:

- `Job(A, run-up_lbs)` — produced before the beam exhaustion.
- optional `Waste(A, partial_lbs)` — the partial roll discarded at the
  runout.
- `BeamLoad(...)` — for the bar(s) that exhausted.
- `StyleChange(from=A, to=B)` — transition to the new item.
- `Job(B, new_item_lbs)` — production of the new item.

Built by calling `Machine.plan_production(B, lbs, start_at='next_runout')`
on a machine whose initial state has beams arranged to force the
exhaustion to occur partway through a roll.

After `commit_move`:

1. `machine.activities` contains all of the above activities in order;
   `machine.current_status` reflects the post-plan state (new beam(s)
   loaded, `current_item == B`, beam lbs decremented by B's
   consumption).
2. `state.rls_items[A.id].jobs` contains the run-up `Job(A)`.
3. `state.rls_items[B.id].jobs` contains the new `Job(B)`.
4. Each `rls_item`'s safety and raw views have been recomputed with
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

### 1.2 Costing

`Costing.score` and `Costing.score_after_move` are weighted sums of
values that have already been computed and tested elsewhere (demand
views' cost trackers, machine activity counts and `Idle` durations).
Coverage here verifies that the right quantities are combined with the
right weights and that `score_after_move` stays pure — not the
underlying numerics themselves, which are covered by the demand-view
and machine tests.

A few scenarios suffice, arranged so each of the eight Phase-1 weights
produces a non-trivial contribution at least once. In each test below,
the weights for *covered* components are set to distinguishable values
(e.g., 1, 10, 100) so a misweighting shows up as a wrong total; the
other weights are set to 0.

#### 1.2.1 Lateness, drainage, single tape-out, idle

Setup:
- An `RlsItem` with `on_hand_lbs` well below its `safety_target` so
  that no jobs results in non-zero `drainage` against the safety view.
- A machine whose committed plan contains a `TapeOut('top')` (or
  `'btm'`), a `BeamLoad`, an `Idle` of known work-hour duration, and a
  `Job` whose `end` falls past the earliest order's `due_date`
  (producing non-zero `lateness` in the raw view).

Assert: `score(state)` equals
`w_lateness × raw_view.lateness + w_drainage × safety_view.drainage
+ w_tape_out_single + w_idle_time × idle_work_hours`.

Components covered: `lateness`, `drainage`, `tape_out_single`,
`idle_time`.

#### 1.2.2 Cross-yarn cross-family transition

Setup:
- A machine whose committed plan contains a `TapeOut('both')`, two
  `BeamLoad`s, and a `StyleChange(is_family_change=True)` (the
  canonical full-changeover shape).
- No demand-side contributions (no unmet weekly demand and safety
  pool already at target, so all four demand-view trackers are 0).

Assert: `score(state)` equals `w_tape_out_both + w_family_change`.

Components covered: `tape_out_both`, `family_change`.

#### 1.2.3 Excess

Setup:
- An `RlsItem` whose committed jobs total more than weekly demand plus
  the safety target, so `safety_view.excess > 0`.
- No schedule-side contributions (no `TapeOut`, no
  `StyleChange(is_family_change=True)`, no `Idle`).

Assert: `score(state)` equals `w_excess × safety_view.excess`.

Components covered: `excess`.

#### 1.2.4 Carrying

Setup:
- An `RlsItem` with a committed `Job` whose `end` is well before the
  target order's `due_date - lead_time`, so `safety_view.carrying > 0`.
- No schedule-side contributions.

Assert: `score(state)` equals `w_carrying × safety_view.carrying`.

Components covered: `carrying`.

#### 1.2.5 `score_after_move`

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

### 1.3 Candidate enumeration

The `loop/candidates.py` module exposes three functions:
`eligible_decision_points`, `eligible_orders`, and
`enumerate_candidates`. The two listing functions are covered below.

#### 1.3.1 `eligible_decision_points`

1. **Empty state** — no machines in `state.machines`. Output: `[]`.

2. **All machines' decision points out of window** — every machine has
   `next_job_end > state.window_end` (and therefore
   `next_runout > state.window_end` too). Output: `[]`.

3. **Single machine, both DPs in window, distinct** — beams partially
   used so that `next_runout > next_job_end`, both within
   `window_end`. Output: two `DecisionPoint`s, one with
   `start_at='next_job_end'` (time = `current_status.as_of`), one with
   `start_at='next_runout'` (time = `machine.next_runout`).

4. **Single machine, both DPs in window, coinciding** — beams empty,
   so `next_runout == next_job_end`. Output: a single `DecisionPoint`
   with `start_at='next_job_end'`; the `next_runout` entry is
   deduplicated.

5. **Single machine, `next_job_end` in window, `next_runout` out** —
   beams full enough that the forward-extrapolated runout is past the
   window's end. Output: a single `DecisionPoint` with
   `start_at='next_job_end'`. (The asymmetric "runout in, job_end out"
   case is impossible by `next_runout >= next_job_end`, so no test for
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
       have exactly one decision point (next_job_end) in window.
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

1. **Fully satisfied item** — no unmet weekly demand and safety pool
   at-or-above target. Output: `[]`.

2. **Unmet week-0 demand only** — week 0 has positive `remaining_lbs`
   in the safety view; weeks 1–3 have zero; safety pool at target.
   Output: one `RegularOrder` for week 0 with the unmet lbs.

3. **Safety below target only** — all weekly orders fully met but
   safety pool below the target. Output: one `SafetyOrder` with lbs =
   `safety_target - safety_pool`.

4. **Both unmet demand and safety shortfall** — week 0 partially unmet
   AND safety below target. Output: one `RegularOrder` (week 0) AND
   one `SafetyOrder`.

5. **Earliest-unmet selection** — multiple weeks have unmet demand
   (e.g., week 0 partially unmet, weeks 1–3 fully unmet). Output's
   `RegularOrder` corresponds to the lowest `week_idx` with positive
   `remaining_lbs`. Only one regular order per item, regardless of how
   many weeks are unmet.

6. **Multiple items, mixed states** — state contains several
   `RlsItem`s, each in a different scenario from 1–5. Output includes
   the appropriate orders for each `RlsItem`, with no cross-talk.
   (Configuration (b) is the natural single test here — the
   constructor-only version is what scenarios 1–5 already cover.)

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
       - orders assigned to the machine already programmed for that item emit only one Job.
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
   style changes, carrying-avoidance idle) restrict hours.
    1. **Mid-week schedule tail** — `current_status.as_of` falls
       partway through the current ISO week, leaving partial remaining
       hours. Order's item matches the current item so there's no
       preamble work. `move.lbs` equals
       `floor(remaining_work_hours × rate / tgt_wt) × tgt_wt`.
    2. **Full changeover preamble** — machine's current item differs
       from the order's in both bars' yarn and in family, forcing
       `TapeOut('both') + 2 × BeamLoad + StyleChange(is_family_change=
       True)` in the preamble. `as_of = week_start` so the preamble is
       the only restriction. `move.lbs` equals
       `floor((week_work_hours - preamble_hours) × rate / tgt_wt) ×
       tgt_wt` where `preamble_hours = TAPE_OUT_BOTH_DURATION + 2 ×
       BEAM_LOAD_DURATION + machine.family_change_duration`.
    3. **Carrying-avoidance idle inside the week** — regular order
       whose `due_date - lead_time - margin` falls partway through the
       same ISO week as the decision point. `effective_start` advances
       to that target via the carrying-avoidance idle, shrinking the
       in-week production window; `move.lbs` equals
       `floor((week_end - effective_start work hours - preamble_hours)
       × rate / tgt_wt) × tgt_wt`.
    4. **`'next_runout'` decision point inside the week** — current
       item has partial beams at `as_of = week_start` such that
       `next_runout` falls midway through the week. Order's item shares
       yarn with the current item so the preamble is a single
       `StyleChange(is_family_change=False)`. `move.lbs` equals
       `floor((week_end - next_runout work hours - simple_change_
       duration) × rate / tgt_wt) × tgt_wt`. (The cap simulation
       idles from `as_of` to `next_runout` rather than running the
       current item, but the post-`next_runout` budget is the same.)

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

1. **Single item, single machine** — total scheduled lbs (sum over
   `report.jobs_by_item[item_id]`) ≥ `sum(weekly_lbs_needed) +
   item.safety`. Every `safety_view.orders[i].remaining_lbs == 0` on
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
   Fresh machines have `next_job_end == start_date` and are initially
   in window. After commits push `next_job_end` past `window_end`,
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