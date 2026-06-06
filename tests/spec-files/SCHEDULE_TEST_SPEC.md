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
`current_status`, `activities`, `jobs`, `schedule_tail`, `next_runout`,
`status_at`, `add_activities`, `add_jobs`. Tests in this phase construct
activity sequences manually (without `plan_production`) and verify the
derived status is correct. The production schedule (`jobs` / `add_jobs`)
and `plan_production`'s `Job` output are covered from Phase 2 on, where
`Job` records are produced.

### 1.1 Construction and initial state

1. `id` and `prefix` are correct
2. `initial_status` is built from constructor args
    - each field set as expected, `as_of == start`, `is_idle == True`,
      `current_item == init_item`, `current_family == init_item.family`
3. `current_status == initial_status` immediately after construction
4. `activities` is an empty tuple
5. `schedule_tail == initial_status.as_of`
6. `next_runout` matches a hand-computed value for the initial state
7. `jobs` is an empty tuple

### 1.2 Per-activity-type status update

One test per activity type. In each, start from a known initial state, add
exactly one activity, and verify `current_status` against a hand-computed
expected. Also verify `current_status == status_at(activity.end)` to confirm
the cached tail matches the walked value.

1. `Knit`
    - lbs consumed from each bar in proportion to `top_pct` / `btm_pct`
    - `current_item == knit.item`
    - `as_of == knit.end`, `is_idle == True`
2. `Waste`
    - empties the named `bar`: that bar's beam → None and its
      `lbs_remaining` → 0; the **other** bar (beam + lbs) is unchanged
      (no proportional consumption — the yarn is dropped unknit, not run)
    - `current_item` is unchanged — `Waste` does not switch the item
    - `Waste` is zero-duration, so `as_of == waste.start == waste.end`
    - one sub-case per `bar` value: `bar='top'` clears top, `bar='btm'`
      clears btm
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
      BeamLoad(btm) + StyleChange + Knit`
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

`next_runout` is the end of the **last whole roll** the current beams can
finish above the floor — the same whole-roll stopping point the run-up uses,
so the prediction matches the activities a `'next_runout'` plan emits. It is
**not** the instant a beam first crosses the floor. The usable yarn on each
bar is `lbs_remaining - BEAM_FLOOR_LBS`; the prediction is
`floor(min(top_usable / top_pct, btm_usable / btm_pct) / tgt_wt) * tgt_wt /
rate` work-hours past `as_of`. Every hand-computed expectation below
subtracts `BEAM_FLOOR_LBS` from each bar's lbs, divides by its pct, then
**rounds down to whole rolls** before converting to time.

1. Computed against the initial state (choose lbs so the usable yarn is
   **not** a whole-roll multiple, to distinguish the whole-roll boundary
   from the raw floor-crossing point)
    1. top limits: `top_usable / top_pct < btm_usable / btm_pct`; expect
       `floor(top_usable / top_pct / tgt_wt)` whole rolls' worth of time
    2. btm limits
    3. Both simultaneous (equal ratios after the floor subtraction)
2. After a `Knit` that updates lbs, `next_runout` reflects the new state
   (whole-roll count recomputed from the reduced usable yarn)
3. After a `BeamLoad` of one bar, `next_runout` reflects the refilled lbs
   (less the floor, rounded down to whole rolls)
4. After a `StyleChange` to a different item, `next_runout` is recomputed
   at the **new** item's rate, pcts, and `tgt_wt`
5. Fewer than one whole roll fits above the floor (`n_rolls == 0`), so the
   changeover is immediately due and the result is `current_status.as_of`:
    1. a bar already at or below `BEAM_FLOOR_LBS` (e.g. both bars at 0 lbs
       after a `TapeOut('both')` with no subsequent `BeamLoad`)
    2. usable yarn above the floor but less than one whole roll
       (`0 < usable / pct < tgt_wt`)
6. Whole-roll agreement: `next_runout` equals the `end` of the run-up
   `Knit`(s) emitted by `plan_production(other_item, …, 'next_runout')` from
   the same state (the two share one whole-roll computation)
7. Workcal interaction: if `as_of` is near the end of a workday, the offset
   crosses the gap to the next workday and the returned datetime is in
   that day

`current_item` is non-nullable: a machine is always programmed to produce
something. There is no "no current item" state to test against.

### 1.6 `add_jobs` / `jobs` (production schedule)

The production schedule is parallel to the activity schedule and carries
no machine-state effect.

1. `add_jobs` appends `Job` records to `jobs` in order; `jobs` reflects the
   full appended history
2. `add_jobs` does **not** change `current_status` (a `Job` records the
   rolls produced, not machine time — only `add_activities` advances the
   status tail)
3. `add_activities` and `add_jobs` are independent: adding activities leaves
   `jobs` untouched, and adding jobs leaves `activities` untouched

## Phase 2 — Partial `plan_production` (same-yarn + same-family only)

`plan_production(item, lbs, start_at)` is added with a deliberate
restriction: `item` must share top yarn id, btm yarn id, and family with
the current item. All other inputs raise. No `TapeOut` or `BeamLoad` is
emitted in the preamble; only a `StyleChange(is_family_change=False)` when
the item differs.

The production loop is fully implemented in this phase. Mid-stream beam
exhaustion still emits `BeamLoad` (a fresh beam of the same yarn).

`plan_production` returns a `ProductionPlan(activities, jobs)`. These tests
assert on both halves: the **activity stream** (`plan.activities` — the
`Knit` / `Waste` / `BeamLoad` / `StyleChange` / `Idle` sequence and each
activity's `lbs`) and the **production records** (`plan.jobs` — the `Job`
objects, each holding the `Roll`s its `Knit`(s) produced). A single `Job`
accumulates rolls across any mid-run `BeamLoad`, so one `Job` can be backed
by more than one `Knit` activity.

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
emitted **activity** sequence shape, item references, and `Knit.lbs` per
activity. The production loop emits `Knit`s (not `Job`s); the `Job` record
is checked separately per the Job-object rule below.

1. Single roll, no mid-stream exhaustion: one `Knit` of the requested lbs
2. Multiple rolls, no mid-stream exhaustion: one `Knit` for the full lbs
   (the loop does not split when beams have capacity)
3. Mid-stream exhaustion exactly at a roll boundary (the pre-roll
   max-waste gate, evaluated when `roll_filled == 0`)
    1. The exhausted bar is reloaded and the other bar is still above
       `MAX_BEAM_WASTE_LBS`:
       `Knit(complete_rolls) + BeamLoad(exhausted) + Knit(remaining)`;
       no `Waste`
    2. The exhausted bar is reloaded **and** the other bar's usable has
       fallen below `MAX_BEAM_WASTE_LBS` at the boundary, so the gate
       co-swaps it: a zero-duration `Waste(other_bar)` (residue discarded)
       plus a `BeamLoad(other_bar)`, in addition to the exhausted bar's
       `BeamLoad`. `Waste.lbs` equals the other bar's usable residue
       (`bar_lbs - BEAM_FLOOR_LBS`); it is not part of the `Job`.
4. Mid-stream exhaustion mid-roll — the in-progress roll **straddles** the
   swap: it keeps winding on the fresh beam and completes as one whole
   roll, so **no `Waste` of the partial roll** is emitted (unlike the old
   half-roll model). The `Knit` before the swap carries whatever lbs were
   wound (not a whole-roll multiple); the straddling roll's
   `completion_time` falls in the `Knit` after the swap.
    1. Single beam load: one bar reaches `BEAM_FLOOR_LBS` mid-roll while
       the other stays above `MAX_BEAM_WASTE_LBS`:
       `Knit(partial) + BeamLoad(bar) + Knit(rest)`
    2. Double beam load: the runout co-swaps the other bar in the same
       operation (bars resolved top-then-btm):
        - other bar below `MAX_BEAM_WASTE_LBS` but not yet at the floor:
          a `BeamLoad` for the runout bar plus `Waste(other) +
          BeamLoad(other)` for the co-swapped bar (its residue a
          zero-duration `Waste`), then `Knit(rest)`
        - both bars reach the floor simultaneously mid-roll: two
          `BeamLoad`s and **no `Waste`**, then `Knit(rest)`
5. Mid-stream exhaustion of the btm bar (single)
6. Both bars exhaust simultaneously
    - set top/btm lbs so they reach `BEAM_FLOOR_LBS` together
      (`top_usable / top_pct == btm_usable / btm_pct`)
    - expect two `BeamLoad`s and **no `Waste`** (both bars sit at the
      floor, so there is no above-floor residue to discard), then
      continuation
7. Cascading exhaustion: the freshly loaded beam also exhausts before the
   request is satisfied (loop iterates more than twice)

**Job object produced by the loop.** `plan.jobs` contains exactly one `Job`
for `item`, regardless of how many `Knit`s back it. Its `total_lbs` equals
the requested lbs and `total_rolls` equals the expected roll count (`Waste`
lbs are **not** part of the `Job`). The backing-`Knit` count distinguishes
the no-reload and reload cases:

- Cases 1–2 (no mid-job `BeamLoad`): exactly **one** `Knit` activity
  corresponds to the single `Job`.
- Cases 3–7 (one or more mid-job `BeamLoad`s): **multiple** `Knit`
  activities correspond to the single `Job`, with roll `completion_time`s
  strictly increasing across the boundary. At a roll-boundary swap (3)
  whole rolls complete on each side; at a mid-roll swap (4) a single roll
  is wound across two `Knit`s and completes in the later one. Every
  recorded `Roll` is a whole `tgt_wt` roll regardless of where the `Knit`s
  split.

### 2.4 `start_at` mode behavior

1. `start_at='schedule_tail'`
    - the first emitted activity's `start == current_status.as_of`
    - no run-up activities of the current item
    - `plan.jobs` contains exactly one `Job` (the new item)
2. `start_at='next_runout'`
    - run-up emits `Knit`(s) of `current_item` for **whole rolls only**,
      stopping before any roll the beams can't finish above the floor; it
      emits **no `Waste`** and **no beam work** of its own (each bar keeps
      its leftover usable yarn)
    - then, in Phase 2's same-yarn case, the preamble has no
      `TapeOut`/`BeamLoad` — just a `StyleChange` if
      `to_item != current_item`
    - then the new item's production loop
    - **two `Job`s produced**: a run-up `Job` of `current_item` (its whole
      rolls) followed by the new item's `Job`, in that order —
      `plan.jobs == (run_up_job, new_item_job)`
3. `start_at='next_runout'`, run-up yields no whole roll
    - the current item's usable yarn is less than one whole roll
      (`producible < tgt_wt`), so the run-up emits **nothing** (no `Knit`,
      no `Waste`) and creates no run-up `Job`
    - **one `Job` produced**: `plan.jobs` contains only the new item's
      `Job`

### 2.5 Purity and commit

1. `plan_production` does not mutate `current_status`, `activities`,
   `jobs`, or the schedule tail
    - call twice with the same args; the two plans must be shape-equal on
      both halves — `plan.activities` (same types, item refs, `lbs`,
      durations) and `plan.jobs` (same item refs, per-`Roll` `lbs` and
      `completion_time` offsets) — allowing only auto-incremented activity
      / job ids to differ
2. After `add_activities(plan.activities)`, `current_status` matches the
   status computed by manually applying each activity in the plan
3. After `add_jobs(plan.jobs)`, `machine.jobs` contains exactly those `Job`
   records and `current_status` is unchanged by them (Jobs carry no
   machine-state effect)

### 2.6 Timing

1. Each activity's `start` equals the previous activity's `end` (or
   `current_status.as_of` for the first activity)
2. Durations match the design's duration table
    - `Knit`: `lbs / item.get_rate_on_mchn(machine.id)`
    - `Waste`: zero duration (`start == end`) — the yarn is swapped out
      unknit, not run
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
      semantics, just like Knit/changeover durations)
3. Idle precedes the run-up in `'next_runout'` mode (it is the very first
   activity, ahead of `Knit`s of the current item)
4. Idle precedes the preamble in `'schedule_tail'` mode (it is the very
   first activity, ahead of any `StyleChange`)
5. `idle_for < timedelta(0)` raises `ValueError`

## Phase 3 — Complete `plan_production`

The yarn-and-family restriction is lifted. Behavior previously rejected now
produces the appropriate `TapeOut` / `Waste` / `BeamLoad` / `StyleChange`
sequence, per the four-state per-bar preamble rule: each bar resolves from
its `usable = bar_lbs - BEAM_FLOOR_LBS` and whether its yarn matches the new
item.

### 3.1 Changeover preamble — per-bar resolution

Each bar resolves independently into one of four actions: load-only
(empty), keep (matching yarn), tape-out + load (mismatch worth preserving),
or waste + load (mismatch to discard). Cases 1–4 isolate one action by
pairing a mismatched/empty bar with a matching one, all within the same
family (`StyleChange(is_family_change=False)`):

1. Top mismatched, `usable > MAX_BEAM_WASTE_LBS`; btm matches:
   `TapeOut('top') + BeamLoad(top) + StyleChange(is_family_change=False)`
2. Btm mismatched, `usable > MAX_BEAM_WASTE_LBS`; top matches: symmetric —
   `TapeOut('btm') + BeamLoad(btm) + StyleChange(is_family_change=False)`
3. Top mismatched, `usable <= MAX_BEAM_WASTE_LBS` (discard); btm matches:
   `Waste('top') + BeamLoad(top) + StyleChange(is_family_change=False)` —
   the `Waste` is zero-duration, `Waste.lbs == top_usable`
   (`top_lbs - BEAM_FLOOR_LBS`), and `Waste.item == current_item` (the
   outgoing item whose yarn is discarded)
4. A mismatched bar that is empty / at the floor (`usable <= 0`):
   `BeamLoad(bar)` only — no `TapeOut`, no `Waste`

Cross-bar combinations:

5. Both bars mismatched, both `usable > MAX_BEAM_WASTE_LBS`, same family:
   one `TapeOut('both') + BeamLoad(top) + BeamLoad(btm) +
   StyleChange(is_family_change=False)` (not two single tape-outs)
6. Both bars mismatched, top `usable > MAX` (tape) and btm
   `usable <= MAX` (waste): `TapeOut('top') + Waste('btm') +
   BeamLoad(top) + BeamLoad(btm) + StyleChange` — **no** `TapeOut('both')`,
   since only one bar tapes out
7. A matching bar is never taped or wasted even when near-empty: pair a
   matching bar with `0 < usable <= MAX_BEAM_WASTE_LBS` against a
   mismatched bar — the matching bar gets **no** preamble activity (its
   near-empty swap, if any, is deferred to the production loop's pre-roll
   gate)

Family dimension (beam work resolves as above; only the `StyleChange` flag
differs):

8. Same yarn on both bars, different family:
   `StyleChange(is_family_change=True)` only; no beam work
9. Different yarn on both bars, different family:
   `TapeOut('both') + BeamLoad(top) + BeamLoad(btm) +
   StyleChange(is_family_change=True)`

### 3.2 `start_at='next_runout'` with non-trivial changeovers

The run-up stops on a whole-roll boundary and emits no beam work, so **both**
bars reach the preamble carrying leftover usable yarn (the limiting bar with
less than one roll's worth, the other possibly more). The preamble then
resolves each bar with the **same four-state rule as §3.1** — there is no
guaranteed-empty bar as in the old drain-to-empty model. Verify:

1. Both bars' leftover yarn mismatches the new item and both are
   `usable > MAX_BEAM_WASTE_LBS`:
   `TapeOut('both') + BeamLoad(top) + BeamLoad(btm) + StyleChange` —
   confirms `TapeOut('both')` **is** reachable in `'next_runout'` mode
   (it was impossible under the old model, where a bar was always drained
   empty by the run-up)
2. The limiting bar's leftover is `usable <= MAX_BEAM_WASTE_LBS` (waste)
   while the other bar is `usable > MAX` (tape): `TapeOut(single) +
   Waste(other) + BeamLoad(top) + BeamLoad(btm) + StyleChange`
3. One bar's leftover yarn matches the new item (same yarn), the other
   mismatches: the matching bar is kept (no activity); the other resolves
   per its state
4. A bar whose leftover lands at or below the floor (`usable <= 0`) gets
   `BeamLoad(bar)` only — possible when the run-up's limiting bar stops
   right at the floor
5. `StyleChange` is emitted whenever `to_item != current_item`, with
   `is_family_change` matching the family comparison
6. Run-up regression: the run-up itself emits only whole-roll `Knit`(s) of
   `current_item` — no `Waste`, no beam work; all leftover-yarn handling is
   the preamble's job

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
    - capacity reflects what is producible before each bar reaches its
      **floor** (`usable = lbs - BEAM_FLOOR_LBS`), with each forced
      mid-stream `BeamLoad` time deducted from available hours, rounded
      down to whole rolls
    - a max-waste residue discard adds a zero-duration `Waste` (no machine
      time beyond the `BeamLoad`), so swapping a near-empty bar early does
      not change the time budget — only the `BeamLoad`s do
3. Multiple mid-stream `BeamLoad`s fit within the week: returned capacity
   correctly subtracts each `BeamLoad` interval

### 4.2 Preamble required

1. A changeover preamble (yarn and/or family) fits within the week and
   leaves time for production: returned capacity =
   floor((available - preamble_time) × rate / tgt_wt) × tgt_wt, where
   `preamble_time` counts `TapeOut` and `BeamLoad` durations — a `Waste`
   residue discard is zero-duration and adds nothing
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

### 4.6 `start` parameter

1. `start=None` (default) matches passing `start=current_status.as_of`
   explicitly — same result for the same machine/item/week
2. `start > current_status.as_of` inside the window delays production:
   the result equals what's producible from `start` through `week_end`,
   minus any preamble
3. `start` later than `current_status.as_of` but before `week_start`
   collapses to "production begins at `week_start`" (same result as
   `start=None` when `as_of < week_start`)
4. `start >= week_end` returns 0
5. `start < current_status.as_of` raises `ValueError`
