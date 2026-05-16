# Specification of coverage of schedule module tests

These tests target the `Machine` class as it grows through four
implementation phases. Unlike the demand spec — which distributed coverage
across separate classes (`RawView`, `SafetyAwareView`, `RlsItem`) — every
phase here exercises the same class, with each phase layering new behaviors
on top of the previous.

Each phase below lists the test coverage to write **after** that phase is
implemented and before moving to the next. Tests written for an earlier
phase remain valid; later phases do not re-test earlier behavior except
where noted as a regression check.

## Phase 1 — Status tracking and `next_runout`

The current implementation. The class has: constructor, `initial_status`,
`current_status`, `activities`, `next_job_end`, `next_runout`, `status_at`,
`add_activities`. Tests in this phase construct activity sequences manually
(without `plan_production`) and verify the derived status is correct.

### 1.1 Construction and initial state

1. `id` and `prefix` are correct
2. `initial_status` is built from constructor args
    - each field set as expected, `as_of == start`, `is_idle == True`,
      `current_item == init_item`, `current_family == init_item.family`
3. `current_status == initial_status` immediately after construction
4. `activities` is an empty tuple
5. `next_job_end == initial_status.as_of`
6. `next_runout` matches a hand-computed value for the initial state

### 1.2 Per-activity-type status update

One test per activity type. In each, start from a known initial state, add
exactly one activity, and verify `current_status` against a hand-computed
expected. Also verify `current_status == status_at(activity.end)` to confirm
the cached tail matches the walked value.

1. `Job`
    - lbs consumed from each bar in proportion to `top_pct` / `btm_pct`
    - `current_item == job.item`
    - `as_of == job.end`, `is_idle == True`
2. `Waste`
    - same consumption math as `Job`
    - `current_item` is unchanged — `Waste` does not switch the item
3. `TapeOut`
    1. `bars='top'`: top beam → None, `top_lbs_remaining` → 0; btm unchanged
    2. `bars='btm'`: btm beam → None, `btm_lbs_remaining` → 0; top unchanged
    3. `bars='both'`: both bars cleared
    - `current_item` unchanged in all three cases
4. `BeamLoad`
    1. `bar='top'`: `top_beam == activity.beam`, `top_lbs_remaining == activity.lbs`
    2. `bar='btm'`: same for btm
    - the unaffected bar's fields are unchanged
    - `current_item` unchanged
5. `StyleChange`
    - `current_item == activity.to_item` (and therefore `current_family`
      reflects the new family)
    - beam fields and remaining lbs all unchanged
6. `Idle`
    - `as_of == activity.end`
    - everything else (`top_beam`, `btm_beam`, `top_lbs_remaining`,
      `btm_lbs_remaining`, `current_item`) unchanged
    - note: `status_at(t)` for `t` strictly inside an `Idle` activity
      returns `is_idle=False` because the Idle is itself an activity in
      progress; this is consistent with the "any activity in progress"
      semantics of the flag

### 1.3 `add_activities` sequencing

1. Adding multiple activities in one call applies them in order
    - use a realistic preamble: `TapeOut('both') + BeamLoad(top) +
      BeamLoad(btm) + StyleChange + Job`
    - assert `current_status` matches the manually computed final state
2. Adding activities in multiple calls produces the same `current_status`
   as adding them in one call (incremental cache equals one-shot cache)
3. `activities` reflects the full appended history in order

### 1.4 `status_at`

1. `status_at(initial_status.as_of) == initial_status`
2. `status_at(t)` for `t` in a gap between two activities (none in progress)
   returns the post-previous-activity state with `as_of=t`, `is_idle=True`
3. `status_at(t)` for `t` strictly inside an activity
   (`activity.start <= t < activity.end`) returns the **pre-activity** state
   with `as_of=t`, `is_idle=False`
4. Boundary cases at activity end
    - `status_at(t)` for `t == activity.end` returns the **post-activity**
      state with `is_idle=True` (end is inclusive of the post state, not of
      the in-progress range)
5. `status_at(t)` for `t` past the tail returns the current tail status with
   `as_of=t`, `is_idle=True`
6. `status_at(t)` for `t < initial_status.as_of` raises `ValueError`

### 1.5 `next_runout`

1. Computed against the initial state
    1. top exhausts first: `top_lbs / top_pct < btm_lbs / btm_pct`
    2. btm exhausts first
    3. Both simultaneous (equal ratios)
2. After a `Job` that updates lbs, `next_runout` reflects the new state
3. After a `BeamLoad` of one bar, `next_runout` reflects the refilled lbs
4. After a `StyleChange` to a different item, `next_runout` is recomputed
   at the **new** item's rate and pcts
5. After a `TapeOut('both')` with no subsequent `BeamLoad`, both bars have
   0 lbs and `next_runout == current_status.as_of` (immediate)
6. Workcal interaction: if `as_of` is near the end of a workday, the offset
   crosses the gap to the next workday and the returned datetime is in
   that day

`current_item` is non-nullable: a machine is always programmed to produce
something. There is no "no current item" state to test against.

## Phase 2 — Partial `plan_production` (same-yarn + same-family only)

`plan_production(item, lbs, start_at)` is added with a deliberate
restriction: `item` must share top yarn id, btm yarn id, and family with
the current item. All other inputs raise. No `TapeOut` or `BeamLoad` is
emitted in the preamble; only a `StyleChange(is_family_change=False)` when
the item differs.

The production loop is fully implemented in this phase. Mid-stream beam
exhaustion still emits `BeamLoad` (a fresh beam of the same yarn).

### 2.1 Input acceptance

1. Same item as `current_item`: accepted
2. Different item with same yarn (both bars) and same family: accepted
3. Different top yarn only: rejected
4. Different btm yarn only: rejected
5. Different family with same yarn on both bars: rejected
6. Different yarn AND different family: rejected

### 2.2 Preamble shape (within accepted inputs)

1. `to_item == current_item`: no preamble activities (production loop only)
2. `to_item != current_item` but same-yarn + same-family: exactly one
   `StyleChange(is_family_change=False)` with duration equal to
   `simple_change_duration`; no `TapeOut` or `BeamLoad`

### 2.3 Production loop

For all of these, request a multiple of `item.tgt_wt` and verify the
emitted sequence shape, item references, and lbs per activity.

1. Single roll, no mid-stream exhaustion: one `Job` of the requested lbs
2. Multiple rolls, no mid-stream exhaustion: one `Job` for the full lbs
   (the loop does not split when beams have capacity)
3. Mid-stream exhaustion exactly at a roll boundary
    - `Job(complete_rolls) + BeamLoad(top) + Job(remaining)`
    - no `Waste` emitted
4. Mid-stream exhaustion mid-roll
    - `Job(complete_rolls) + Waste(partial) + BeamLoad(top) + Job(remaining)`
5. Mid-stream exhaustion of the btm bar (single)
6. Both bars exhaust simultaneously
    - set top/btm lbs so `top_lbs / top_pct == btm_lbs / btm_pct`
    - expect two `BeamLoad`s after the partial-roll/Waste (if any), then
      continuation
7. Cascading exhaustion: the freshly loaded beam also exhausts before the
   request is satisfied (loop iterates more than twice)

### 2.4 `start_at` mode behavior

1. `start_at='next_job_end'`
    - the first emitted activity's `start == current_status.as_of`
    - no run-up activities of the current item
2. `start_at='next_runout'`
    - run-up emits `Job`(s) of `current_item` for complete rolls until
      beam exhaustion, plus a `Waste` of `current_item` for any partial
    - then `BeamLoad` for the exhausted bar(s) (no `TapeOut`)
    - then `StyleChange` if `to_item != current_item`
    - then the new item's production loop

### 2.5 Purity and commit

1. `plan_production` does not mutate `current_status`, `activities`, or the
   schedule tail
    - call twice with the same args; the two plans must be activity-shape
      equal (same types, item refs, lbs, durations), allowing only the
      auto-incremented activity ids to differ
2. After `add_activities(plan)`, `current_status` matches the status
   computed by manually applying each activity in the plan

### 2.6 Timing

1. Each activity's `start` equals the previous activity's `end` (or
   `current_status.as_of` for the first activity)
2. Durations match the design's duration table
    - `Job` / `Waste`: `lbs / item.get_rate_on_mchn(machine.id)`
    - `BeamLoad`: `BEAM_LOAD_DURATION`
    - `StyleChange`: `simple_change_duration` (Phase 2 only emits the
      simple variant)
3. All times respect `workcal`: a request that would span a non-work
   interval has its activities pushed past the gap

### 2.7 `idle_for` parameter

1. `idle_for=timedelta(0)` (default): no `Idle` activity emitted
2. `idle_for > 0`: first emitted activity is an `Idle` of that duration
    - its `start` equals `current_status.as_of`
    - its `end - start` reflects work-hour offset (matches workcal
      semantics, just like Job/changeover durations)
3. Idle precedes the run-up in `'next_runout'` mode (it is the very first
   activity, ahead of `Job`s of the current item)
4. Idle precedes the preamble in `'next_job_end'` mode (it is the very
   first activity, ahead of any `StyleChange`)
5. `idle_for < timedelta(0)` raises `ValueError`

## Phase 3 — Complete `plan_production`

The yarn-and-family restriction is lifted. Behavior previously rejected now
produces the appropriate `TapeOut` / `BeamLoad` / `StyleChange` sequence.

### 3.1 Inputs previously rejected, by changeover shape

1. Different yarn on top only, same family
    - `TapeOut('top') + BeamLoad(top, new) + StyleChange(is_family_change=False)`
2. Different yarn on btm only, same family
3. Different yarn on both bars, same family
    - `TapeOut('both') + BeamLoad(top) + BeamLoad(btm) + StyleChange(is_family_change=False)`
4. Same yarn on both bars, different family
    - `StyleChange(is_family_change=True)` only; no beam work
5. Different top yarn only, different family
6. Different yarn on both bars, different family
    - `TapeOut('both') + BeamLoad(top) + BeamLoad(btm) + StyleChange(is_family_change=True)`

### 3.2 `start_at='next_runout'` with non-trivial changeovers

After the run-up exhausts one (or both) bars, the changeover preamble
encounters at least one empty bar. Verify:

1. One bar exhausted, the other has matching yarn for the new item
    - emit `BeamLoad(exhausted)` only — no `TapeOut`
2. One bar exhausted, the other has non-matching yarn
    - emit `TapeOut(other) + BeamLoad(other) + BeamLoad(exhausted)`
3. Both bars exhaust simultaneously
    - emit two `BeamLoad`s, no `TapeOut`
4. `TapeOut('both')` is never emitted in `'next_runout'` mode
   (impossible — at least one bar is empty after the run-up)
5. `StyleChange` is emitted whenever `to_item != current_item`, with
   `is_family_change` matching the family comparison

### 3.3 `StyleChange` duration

1. `is_family_change=False` uses `simple_change_duration`
2. `is_family_change=True` uses `family_change_duration`
3. The two durations are independent per machine; constructing two
   machines with different values and planning the same transition
   produces different end times

### 3.4 `TapeOut` duration

1. `TapeOut('top')` / `TapeOut('btm')` use `TAPE_OUT_SINGLE_DURATION`
2. `TapeOut('both')` uses `TAPE_OUT_BOTH_DURATION`

### 3.5 Regression: Phase 2 cases still match Phase 2 expectations

Re-run a representative subset of Phase 2 plan-shape tests against the
Phase 3 implementation; verify the previously-accepted inputs still emit
the same activity sequence.

## Phase 4 — `producible_lbs_in_week`

A pure capacity-reporting query. Does not mutate state.

### 4.1 No preamble required (`current_item == requested item`)

1. Empty schedule, week entirely after `as_of`: capacity bounded by
   week-hours × rate, rounded down to whole rolls
2. Beam capacity limits the count below the time-based maximum
    - capacity reflects what would be produced before runout, with the
      forced mid-stream `BeamLoad` time deducted from available hours,
      rounded down to rolls
3. Multiple mid-stream `BeamLoad`s fit within the week: returned capacity
   correctly subtracts each `BeamLoad` interval

### 4.2 Preamble required

1. Different yarn / family preamble fits within the week and leaves time
   for production: returned capacity = floor((available - preamble_time) ×
   rate / tgt_wt) × tgt_wt
2. Preamble alone exceeds the available work hours: returns 0
3. Preamble fits but leaves less than one full roll of time: returns 0

### 4.3 Workcal alignment

1. `as_of` before the week starts: capacity computed from the week's first
   workday, not from `as_of`
2. `as_of` strictly inside the week: capacity computed from `as_of` to
   week end
3. `as_of` after the week's last workday: returns 0
4. Week contains non-work hours (weekend, holiday): only work hours count
   toward capacity
5. The `(year, week)` argument resolves to the correct ISO Monday–Sunday
   range, including the cross-year edge cases (week 1 of year N can start
   in late December of year N-1; week 52/53 of year N-1 can extend into
   year N)

### 4.4 Determinism and purity

1. Calling `producible_lbs_in_week` does not mutate `current_status`,
   `activities`, or activity-id counters
2. Calling twice with the same args returns the same value

### 4.5 Rounding

1. Returned value is always a whole multiple of `item.tgt_wt`
2. Exactly one roll fits: capacity equals `tgt_wt`, not 0
3. Slightly less than one roll fits: capacity is 0
