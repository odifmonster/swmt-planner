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

6. **Multiple machines, mixed** — state contains several machines, at
   least one in each of the four single-machine states above
   (excluding the "no machines" empty case). Verify each machine's
   contribution lands in the output and machines whose decision points
   are entirely out of window contribute nothing.

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
