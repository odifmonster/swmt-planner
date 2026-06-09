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
    - read through the accessors: `beam('top') == init_top_beam`,
      `lbs_remaining('top') == init_top_lbs`, `threaded('top') == True`, and
      symmetrically for `'btm'` (a machine begins threaded and running on
      both bars)
    - `as_of == start`, `is_idle == True`, `current_item == init_item`,
      `current_family == init_item.family`
3. `current_status == initial_status` immediately after construction
4. `activities` is an empty tuple
5. `schedule_tail == initial_status.as_of`
6. `next_runout` matches a hand-computed value for the initial state
7. `jobs` is an empty tuple

### 1.2 Per-activity-type status update

One test per activity type. In each, start from a known pre-state, apply
exactly one activity, and verify the resulting status against a hand-computed
expected. Read per-bar values through the accessors (`beam(bar)`,
`lbs_remaining(bar)`, `threaded(bar)`), never the old `top_*`/`btm_*` fields.

For the activities addable from the machine's natural initial state (threaded,
full beams) — `Knit`, `Waste`, `Doff`, `TapeOut`, the changeovers, `Idle` —
add the single activity via the machine and also verify
`current_status == status_at(activity.end)` (the cached tail matches the
walked value). `Hanging` and `Threading` require a non-initial pre-state (a
*removed* / *hung* bar), so build that pre-state with `Status.create` and
exercise the pure `apply_activity` transition directly.

1. `Knit`
    - lbs consumed from each bar in proportion to `top_pct` / `btm_pct`
      (`lbs_remaining('top')` / `lbs_remaining('btm')` drop accordingly)
    - each bar's `beam` and `threaded` unchanged
    - `current_item == knit.item`
    - `as_of == knit.end`, `is_idle == True`
2. `Waste`
    - empties the named `bar`: `beam(bar) -> None`, `lbs_remaining(bar) -> 0`,
      and `threaded(bar) -> False`; the **other** bar (beam + lbs + threaded)
      is unchanged (no proportional consumption — the yarn is dropped unknit,
      not run)
    - `current_item` is unchanged — `Waste` does not switch the item
    - `Waste` is zero-duration, so `as_of == waste.start == waste.end`
    - one sub-case per `bar` value: `bar='top'` clears top, `bar='btm'`
      clears btm
    - `Waste` carries `beam` (the discarded yarn SKU); it is stored data
      and does not affect the status transition (which only empties `bar`)
3. `Doff`
    - fieldless (mirrors `Idle`): advances `as_of == doff.end`,
      `is_idle == True`
    - everything else unchanged (`beam`, `lbs_remaining`, `threaded` on both
      bars, `current_item`) — a `Doff` is machine time only
4. `TapeOut`
    1. `bars='top'`: `beam('top') -> None`, `lbs_remaining('top') -> 0`,
       `threaded('top') -> False`; btm unchanged
    2. `bars='btm'`: symmetric; top unchanged
    3. `bars='both'`: both bars cleared
    - `current_item` unchanged in all three cases
    - `TapeOut` carries `top_beam` / `btm_beam` (the SKU removed from each
      affected bar, `None` for an untouched bar); stored data for future
      inventory tracking, not consulted by the status transition
5. `Hanging` (pre-state: target bar(s) **removed** — built via `Status.create`)
    1. `bars='top'` from a removed top bar: `beam('top') == activity.top_beam`,
       `lbs_remaining('top') == activity.top_lbs`, `threaded('top') == False`
       (loaded but not yet routed); btm unchanged
    2. `bars='btm'`: symmetric, from `activity.btm_beam` / `activity.btm_lbs`
    3. `bars='both'` from two removed bars: both bars loaded, both left
       un-threaded
    - `current_item` unchanged
    - (the guard that `Hanging` requires a removed bar is covered in §1.3)
6. `Threading` (pre-state: target bar(s) **hung** — loaded, not threaded)
    1. `bars='top'`: `threaded('top') -> True`; `beam('top')` and
       `lbs_remaining('top')` unchanged (only the threaded flag flips)
    2. `bars='btm'`: symmetric
    3. `bars='both'`: both bars flipped to threaded
    - `current_item` unchanged
    - (the guard that `Threading` requires a hung bar is covered in §1.3)
7. Changeovers — `StyleChange`, `RunnerChange`, `PatternChange`
    - one sub-case per type; all three share the **same** status transition
      (they differ only in duration/cost): `current_item == activity.to_item`
      (and therefore `current_family` reflects the new family)
    - both bars' beams, remaining lbs, and threaded flags all unchanged
8. `Idle`
    - `as_of == activity.end`, `is_idle == True`
    - everything else (`beam`, `lbs_remaining`, `threaded` on both bars,
      `current_item`) unchanged
    - note: `status_at(t)` for `t` strictly inside an `Idle` activity
      returns `is_idle=False` because the Idle is itself an activity in
      progress; this is consistent with the "any activity in progress"
      semantics of the flag

### 1.3 `add_activities` sequencing

1. Adding multiple activities in one call applies them in order
    - use a realistic preamble: `TapeOut('both') + Hanging('both') +
      Threading('both') + StyleChange + Knit` (the remove -> hang -> thread
      sequence with the `'both'` batching the machine emits)
    - assert `current_status` matches the manually computed final state
2. Adding activities in multiple calls produces the same `current_status`
   as adding them in one call (incremental cache equals one-shot cache)
3. `activities` reflects the full appended history in order

**Beam-swap guard rails (`apply_activity` sequencing).** A swap must run
remove -> hang -> thread; `apply_activity` raises `ValueError` when the steps
are out of order. A bar is *removed* when `beam(bar) is None` **or** its
usable yarn is gone (`lbs_remaining(bar) <= BEAM_FLOOR_LBS`, i.e. usable
`<= 0`), and *hung* when a fresh set is loaded but not yet threaded (not
removed and not threaded). A `'both'` activity checks each bar independently
and raises if **either** bar fails its guard.

4. `Hanging('top')` / `Hanging('btm')` require the target bar **removed**:
    1. allowed (no raise) when `beam(bar) is None` (e.g. after a
       `TapeOut`/`Waste`) — the fresh set loads, `threaded(bar) == False`
    2. allowed when usable yarn is gone (`lbs_remaining(bar) <=
       BEAM_FLOOR_LBS`) even with a beam still mounted (knit down to the
       floor)
    3. raises when the bar still holds a usable set (`beam(bar) is not None`
       **and** `lbs_remaining(bar) > BEAM_FLOOR_LBS`) — e.g. hanging onto the
       machine's full, threaded initial bar
    4. raises when the bar is already *hung* (a second `Hanging` before the
       `Threading` — still not removed)
5. `Hanging('both')` checks both bars:
    1. accepted when **both** bars are removed — both load, both left
       un-threaded
    2. raises when only one bar is removed and the other still holds a usable
       set — the `'both'` guard fails on the non-removed bar; test both
       arrangements (top-removed/btm-not and btm-removed/top-not)
    3. raises when one bar is removed and the other is already *hung* — again
       the guard fails on the non-removed bar
6. `Threading('top')` / `Threading('btm')` require the target bar **hung**
   (loaded, not yet threaded):
    1. allowed (no raise) on a hung bar — `threaded(bar)` flips to `True`
    2. raises when the bar is **already threaded** (the machine's threaded
       initial state, or threading the same bar twice)
    3. raises when the bar is **not yet hung** — removed but with no
       `Hanging` first (e.g. `Threading` straight after a `TapeOut`)
7. `Threading('both')` checks both bars:
    1. accepted when **both** bars are hung — both flip to threaded
    2. raises when only one bar is hung and the other is already threaded —
       the `'both'` guard fails on the threaded bar; test both arrangements
    3. raises when only one bar is hung and the other is still removed — the
       guard fails on the removed bar
8. Out-of-sequence multi-activity adds (sequence applied via
   `add_activities`):
    1. in order succeeds: `[TapeOut('top'), Hanging('top'), Threading('top')]`
       moves top removed -> hung -> threaded onto the fresh beam
    2. thread-before-hang raises: `[TapeOut('top'), Threading('top')]`
       (bar removed, not hung)
    3. double-hang raises: `[TapeOut('top'), Hanging('top'), Hanging('top')]`
       (second hang onto a hung bar)
    4. post-`Waste` in order succeeds: `[Waste('top'), Hanging('top'),
       Threading('top')]` — `Waste` removes the bar (beam -> None) just like a
       `TapeOut`, so the same remove -> hang -> thread sequence applies
    5. post-`Waste` out of order raises: `[Waste('top'), Threading('top')]`
       (bar removed by the waste, not hung)
    6. post-knit-to-floor in order succeeds (happy path only): a `Knit` that
       draws one bar down to `<= BEAM_FLOOR_LBS` removes it, so
       `[Knit(...), Hanging(bar), Threading(bar)]` re-threads that bar — the
       failing branch depends solely on whether the bar is in a hangable
       state, already fully covered by items 4–7

(`add_activities` applies activities as it walks, so a raise mid-sequence
leaves the already-applied prefix committed; these tests assert the
`ValueError`, not post-raise machine state.)

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
**not** the instant a beam first crosses the floor. The whole-roll count is
`n_rolls = floor(min(top_usable / top_pct, btm_usable / btm_pct) / tgt_wt)`,
where each bar's `usable = lbs_remaining(bar) - BEAM_FLOOR_LBS`. The time is
then `n_rolls * per_roll` work-hours past `as_of`, where **`per_roll =
tgt_wt / rate + DOFF_DURATION`** — each whole roll costs its knit time *plus*
its `Doff`, so the prediction lands on the run-up's **last `Doff.end`**, not
the last `Knit.end`. `rate` is `item.get_rate_on_mchn(machine.id)`. Every
hand-computed expectation below derives `n_rolls` from the floor-subtracted,
pct-divided, floored usable yarn, then converts via `per_roll` (folding in one
`DOFF_DURATION` per roll) through `workcal.offset_work_hours`.

1. Computed against the initial state (choose lbs so the usable yarn is
   **not** a whole-roll multiple, to distinguish the whole-roll boundary
   from the raw floor-crossing point)
    1. top limits: `top_usable / top_pct < btm_usable / btm_pct`; expect
       `floor(top_usable / top_pct / tgt_wt)` whole rolls, each timed at
       `per_roll`
    2. btm limits
    3. Both simultaneous (equal ratios after the floor subtraction)
2. After a `Knit` that updates lbs, `next_runout` reflects the new state
   (whole-roll count recomputed from the reduced usable yarn)
3. After re-threading one bar (remove -> `Hanging` -> `Threading` to a fresh
   beam), `next_runout` reflects the refilled lbs (less the floor, rounded
   down to whole rolls, each timed at `per_roll`)
4. After a changeover to a different item, `next_runout` is recomputed at the
   **new** item's rate, pcts, and `tgt_wt` (`per_roll` uses the new item's
   rate and `tgt_wt`)
5. Fewer than one whole roll fits above the floor (`n_rolls == 0`), so the
   changeover is immediately due and the result is `current_status.as_of`:
    1. a bar already at or below `BEAM_FLOOR_LBS` (e.g. both bars at 0 lbs
       after a `TapeOut('both')` with no subsequent re-thread)
    2. usable yarn above the floor but less than one whole roll
       (`0 < usable / pct < tgt_wt`)
6. Whole-roll agreement: `next_runout` equals the `end` of the **last `Doff`**
   in the `Knit`/`Doff` run-up emitted by
   `plan_production(other_item, …, 'next_runout')` from the same state — the
   two share one whole-roll computation and both fold in the per-roll doff
   time
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

## Phase 2 — `plan_production` over same-yarn + same-family transitions

> These tests originally targeted a *partial* `plan_production` that enforced
> a same-yarn + same-family restriction and raised on other inputs. The
> implementation is now complete (the restriction was lifted in Phase 3), so
> this phase no longer tests a restriction — it covers `plan_production`'s
> behavior on the **same-yarn + same-family** transition subset (no tape-out
> or waste preamble), with the cross-yarn / cross-family preambles deferred
> to Phase 3. §2.1 (input acceptance) is obsolete; the rest stand as scenario
> coverage.

In this subset the changeover preamble emits **no** beam work — the shared
yarn carries over — only a changeover activity (`StyleChange` on a new
machine, `RunnerChange` on a legacy machine) when the item differs. The
production loop is fully exercised here; mid-stream beam exhaustion emits a
re-thread (`Hanging` + `Threading`) of a fresh beam of the same yarn.

`plan_production` returns a `ProductionPlan(activities, jobs)`. These tests
assert on both halves: the **activity stream** (`plan.activities` — the
`Knit` / `Doff` / `Waste` / `Hanging` / `Threading` / changeover / `Idle`
sequence and each activity's `lbs`) and the **production records**
(`plan.jobs` — the `Job` objects, each holding the `Roll`s its `Knit`(s)
produced, one `Doff` per roll). A single `Job` accumulates rolls across any
mid-run re-thread, so one `Job` can be backed by more than one `Knit`
activity.

### 2.1 Input acceptance — obsolete, not implemented

These tests reflect an earlier development stage where `plan_production`
enforced a same-yarn + same-family restriction and raised on every other
input. That restriction has since been lifted — `plan_production` now plans
arbitrary transitions (the full changeover preamble is covered in Phase 3) —
so there are no accept/reject inputs left to assert. **No tests are written
for this section.** The original cases are kept below only as a record of the
abandoned restriction:

1. ~~Same item as `current_item`: accepted~~
2. ~~Different item with same yarn (both bars) and same family: accepted~~
3. ~~Different top yarn only: rejected~~
4. ~~Different btm yarn only: rejected~~
5. ~~Different family with same yarn on both bars: rejected~~
6. ~~Different yarn AND different family: rejected~~

### 2.2 Preamble shape (same-yarn + same-family transition)

1. `to_item == current_item`: no preamble activities (production loop only)
2. `to_item != current_item`, same yarn on both bars + same family: exactly
   one changeover activity, its type selected by `Machine.is_new`, and **no**
   beam work (`TapeOut` / `Waste` / `Hanging` / `Threading`) — the shared
   yarn carries over:
    1. new machine (`is_new=True`): a single `StyleChange(from_item,
       to_item)` (duration `STYLE_CHANGE_DURATION`)
    2. legacy machine (`is_new=False`): a single `RunnerChange(from_item,
       to_item)` — same family, so the lighter runner reconfigure, not a
       `PatternChange` (duration `RUNNER_CHANGE_DURATION`)

### 2.3 Production loop

For all of these, request a multiple of `item.tgt_wt` and verify the
emitted **activity** sequence shape, item references, and `Knit.lbs` per
activity. Every roll ends in **exactly one `Doff`** and is backed by **at
least one `Knit`** (more than one only when a beam swap splits the roll), so
N whole rolls produce N `Doff`s; the loop flushes the open `Knit` at each
roll boundary before its `Doff`. A mid-stream beam swap is a re-thread —
`Hanging` + `Threading` (batched `'both'` on a co-swap) — never the old
`BeamLoad`. The production loop emits `Knit`/`Doff` pairs (not `Job`s); the
`Job` record is checked separately per the Job-object rule below.

1. Single roll, no mid-stream exhaustion: one `Knit` of the requested lbs
   followed by one `Doff`
2. Multiple rolls, no mid-stream exhaustion: one `Knit` + one `Doff` **per
   roll** (the loop flushes and doffs at each roll boundary), so N rolls
   produce N `Knit`/`Doff` pairs — not a single `Knit` for the full lbs
3. Mid-stream exhaustion exactly at a roll boundary (the pre-roll
   max-waste gate, evaluated when `roll_filled == 0`)
    1. The exhausted bar is reloaded and the other bar is still above
       `MAX_BEAM_WASTE_LBS`: the completed rolls' `Knit`/`Doff` pairs, then
       `Hanging(exhausted) + Threading(exhausted)`, then the remaining
       rolls' `Knit`/`Doff` pairs; no `Waste`
    2. The exhausted bar is reloaded **and** the other bar's usable has
       fallen below `MAX_BEAM_WASTE_LBS` at the boundary, so the gate
       co-swaps it: a zero-duration `Waste(other_bar)` (residue discarded)
       then a single `Hanging('both') + Threading('both')` re-threading both
       bars together. `Waste.lbs` equals the other bar's usable residue
       (`bar_lbs - BEAM_FLOOR_LBS`); it is not part of the `Job`.
4. Mid-stream exhaustion mid-roll — the in-progress roll **straddles** the
   swap: it keeps winding on the fresh beam and completes as one whole
   roll (one `Doff`), so **no `Waste` of the partial roll** is emitted
   (unlike the old half-roll model). The `Knit` before the swap carries
   whatever lbs were wound (not a whole-roll multiple); the straddling roll
   finishes in the `Knit` after the swap, and its `Doff` follows that.
    1. Single re-thread: one bar reaches `BEAM_FLOOR_LBS` mid-roll while
       the other stays above `MAX_BEAM_WASTE_LBS`:
       `Knit(partial) + Hanging(bar) + Threading(bar) + Knit(rest) + Doff`
    2. Double re-thread: the runout co-swaps the other bar in the same
       operation (bars resolved top-then-btm):
        - other bar below `MAX_BEAM_WASTE_LBS` but not yet at the floor:
          `Knit(partial) + Waste(other) + Hanging('both') +
          Threading('both') + Knit(rest) + Doff` (the co-swapped bar's
          residue a zero-duration `Waste`)
        - both bars reach the floor simultaneously mid-roll:
          `Knit(partial) + Hanging('both') + Threading('both') +
          Knit(rest) + Doff` — **no `Waste`**
5. Mid-stream exhaustion of the btm bar (single re-thread of `'btm'`)
6. Both bars exhaust simultaneously
    - set top/btm lbs so they reach `BEAM_FLOOR_LBS` together
      (`top_usable / top_pct == btm_usable / btm_pct`)
    - expect `Hanging('both') + Threading('both')` and **no `Waste`** (both
      bars sit at the floor, so there is no above-floor residue to discard),
      then continuation
7. Cascading exhaustion: the freshly re-threaded beam also exhausts before
   the request is satisfied (loop iterates more than twice)

**Job object produced by the loop.** `plan.jobs` contains exactly one `Job`
for `item`, regardless of how many `Knit`s / `Doff`s back it. Its `total_lbs`
equals the requested lbs and `total_rolls` equals the expected roll count
(`Waste` lbs are **not** part of the `Job`). Every recorded `Roll` is a whole
`tgt_wt` roll, its `completion_time` is the matching `Doff`'s end, and the
`completion_time`s are strictly increasing. The per-roll backing distinguishes
the cases:

- Each roll is backed by **exactly one `Doff`** and **one `Knit`**, except a
  roll split by a mid-roll beam swap, which is wound across **two `Knit`s**
  and completes in the later one (still one `Doff`).
- Cases 1–2 (no mid-job swap): one `Knit` + one `Doff` per roll, N rolls.
- Cases 3, 5, 6 (roll-boundary swap): whole rolls complete on each side of
  the re-thread, each its own `Knit` + `Doff`.
- Cases 4, 7 (mid-roll swap / cascade): at least one roll straddles a
  re-thread and is backed by two `Knit`s.

### 2.4 `start_at` mode behavior

1. `start_at='schedule_tail'`
    - the first emitted activity's `start == current_status.as_of`
    - no run-up activities of the current item
    - `plan.jobs` contains exactly one `Job` (the new item)
2. `start_at='next_runout'`
    - run-up emits `Knit`/`Doff` pairs of `current_item` for **whole rolls
      only**, stopping before any roll the beams can't finish above the
      floor; it emits **no `Waste`** and **no beam work** of its own (each
      bar keeps whatever usable yarn it has left)
    - preamble (Phase 2's same-yarn case): a bar the run-up left **at/below
      the floor** is re-threaded (`Hanging` + `Threading` — the only beam
      work the preamble does here, since the yarn matches); a bar still above
      the floor is kept. Then the changeover (`StyleChange` / `RunnerChange`
      per `is_new`) if `to_item != current_item`
    - then the new item's production loop
    - **two `Job`s produced**: a run-up `Job` of `current_item` (its whole
      rolls) followed by the new item's `Job`, in that order —
      `plan.jobs == (run_up_job, new_item_job)`
    - two scenarios distinguished by **where the fresh beam is hung**:
        1. clean roll boundary — the previous item's beams hold an **exact**
           whole-roll multiple, so the last run-up roll drains the limiting
           bar to the floor (`usable <= 0`). That bar is re-threaded in the
           **preamble** (`Hanging` + `Threading`), so the new item's first
           roll starts on a fresh beam with **no partial roll wound on the
           machine** — every new-item roll is a clean `Knit` + `Doff`, no
           mid-roll straddle. At least one bar ends the run-up at/below the
           floor; this case explicitly does **not** leave both bars above
           `MAX_BEAM_WASTE_LBS`.
        2. interrupted first roll — the last run-up roll exhausts **no** bar:
           it leaves **both** above `MAX_BEAM_WASTE_LBS` (so neither is
           re-threaded in the preamble and the pre-roll gate does not
           pre-swap) but with less than one whole next-item roll of usable
           yarn. The new item's **first** roll therefore starts on the
           leftover yarn and straddles a mid-roll re-thread of at least one
           bar (`Knit(partial) + Hanging + Threading + Knit(rest) + Doff`).
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
2. Durations match the design's duration table (all are **work-hours**
   passed to `workcal.offset_work_hours`)
    - `Knit`: `lbs / item.get_rate_on_mchn(machine.id)`
    - `Doff`: `DOFF_DURATION`
    - `Waste`: zero duration (`start == end`) — the yarn is swapped out
      unknit, not run
    - `Hanging`: `HANGING_SINGLE_DURATION` (single bar) /
      `HANGING_BOTH_DURATION` (`'both'`)
    - `Threading`: `THREADING_SINGLE_DURATION` (single bar) /
      `THREADING_BOTH_DURATION` (`'both'`)
    - changeover (Phase 2 emits the intra-family variants): `StyleChange` →
      `STYLE_CHANGE_DURATION` (new machine), `RunnerChange` →
      `RUNNER_CHANGE_DURATION` (legacy machine)
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
produces the appropriate `TapeOut` / `Waste` / `Hanging` + `Threading` /
changeover sequence, per the four-state per-bar preamble rule: each bar
resolves from its `usable = bar_lbs - BEAM_FLOOR_LBS` and whether its yarn
matches the new item.

### 3.1 Changeover preamble — per-bar resolution

Each bar resolves independently into one of four actions: load-only
(empty), keep (matching yarn), tape-out + re-thread (mismatch worth
preserving), or waste + re-thread (mismatch to discard). A *re-thread* is a
`Hanging` then a `Threading` of that bar (the pair that replaced the old
single `BeamLoad`); when both bars re-thread they batch into a single
`Hanging('both') + Threading('both')`. The trailing changeover here is the
**same-family** type — `StyleChange` on a new machine, `RunnerChange` on a
legacy one (the beam work is identical either way), written below as
`+ changeover`. Cases 1–4 isolate one action by pairing a mismatched/empty
bar with a matching one, all within the same family:

1. Top mismatched, `usable > MAX_BEAM_WASTE_LBS`; btm matches:
   `TapeOut('top') + Hanging('top') + Threading('top') + changeover`
2. Btm mismatched, `usable > MAX_BEAM_WASTE_LBS`; top matches: symmetric —
   `TapeOut('btm') + Hanging('btm') + Threading('btm') + changeover`
3. Top mismatched, `usable <= MAX_BEAM_WASTE_LBS` (discard); btm matches:
   `Waste('top') + Hanging('top') + Threading('top') + changeover` —
   the `Waste` is zero-duration, `Waste.lbs == top_usable`
   (`top_lbs - BEAM_FLOOR_LBS`), and `Waste.beam` is the top bar's beam SKU
   (the outgoing yarn being discarded — `Waste` stores the beam set, not the
   greige)
4. A mismatched bar that is empty / at the floor (`usable <= 0`):
   `Hanging(bar) + Threading(bar)` only — no `TapeOut`, no `Waste`

Cross-bar combinations:

5. Both bars mismatched, both `usable > MAX_BEAM_WASTE_LBS`, same family:
   one `TapeOut('both') + Hanging('both') + Threading('both') + changeover`
   (a single `'both'` tape-out and a single `'both'` re-thread, not two of
   each)
6. Both bars mismatched, top `usable > MAX` (tape) and btm
   `usable <= MAX` (waste): `TapeOut('top') + Waste('btm') +
   Hanging('both') + Threading('both') + changeover` — **no** `TapeOut('both')`
   (only one bar tapes out), but both bars re-thread together
7. A matching bar is never taped or wasted even when near-empty: pair a
   matching bar with `0 < usable <= MAX_BEAM_WASTE_LBS` against a
   mismatched bar — the matching bar gets **no** preamble activity (its
   near-empty swap, if any, is deferred to the production loop's pre-roll
   gate)

Changeover-class dimension (beam work resolves as above; the changeover
**class** is selected by `is_new` + the family comparison — see §3.3 — there
is no `is_family_change` flag). On a **legacy** machine a cross-family
transition emits a `PatternChange`:

8. Same yarn on both bars, cross-family, legacy machine: a `PatternChange`
   only; no beam work
9. Different yarn on both bars, cross-family, legacy machine:
   `TapeOut('both') + Hanging('both') + Threading('both') + PatternChange`

### 3.2 `start_at='next_runout'` with non-trivial changeovers

The run-up stops on a whole-roll boundary and emits no beam work, so **both**
bars reach the preamble carrying leftover usable yarn (the limiting bar with
less than one roll's worth, the other possibly more). The preamble then
resolves each bar with the **same four-state rule as §3.1** — there is no
guaranteed-empty bar as in the old drain-to-empty model. Verify:

1. Both bars' leftover yarn mismatches the new item and both are
   `usable > MAX_BEAM_WASTE_LBS`:
   `TapeOut('both') + Hanging('both') + Threading('both') + changeover` —
   confirms `TapeOut('both')` **is** reachable in `'next_runout'` mode
   (it was impossible under the old model, where a bar was always drained
   empty by the run-up)
2. The limiting bar's leftover is `usable <= MAX_BEAM_WASTE_LBS` (waste)
   while the other bar is `usable > MAX` (tape): `TapeOut(single) +
   Waste(other) + Hanging('both') + Threading('both') + changeover`
3. One bar's leftover yarn matches the new item (same yarn), the other
   mismatches: the matching bar is kept (no activity); the other resolves
   per its state
4. A bar whose leftover lands at or below the floor (`usable <= 0`) gets
   `Hanging(bar) + Threading(bar)` only — possible when the run-up's limiting
   bar stops right at the floor
5. The changeover is emitted whenever `to_item != current_item`, its type
   (`StyleChange` / `RunnerChange` / `PatternChange`) matching `is_new` and
   the family comparison
6. Run-up regression: the run-up itself emits only whole-roll `Knit`/`Doff`
   pairs of `current_item` — no `Waste`, no beam work; all leftover-yarn
   handling is the preamble's job

### 3.3 Changeover type and duration

The changeover **class** is selected by `is_new` and the pattern-family
comparison; each class uses its own module-level duration constant (the
constructor no longer takes per-machine change durations):

1. New machine (`is_new=True`): `StyleChange` regardless of whether the
   family changes — duration `STYLE_CHANGE_DURATION`
2. Legacy machine (`is_new=False`), same family: `RunnerChange` — duration
   `RUNNER_CHANGE_DURATION`
3. Legacy machine, cross family: `PatternChange` — duration
   `PATTERN_CHANGE_DURATION`

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

1. Empty schedule, week entirely after `as_of`: capacity is bounded by the
   week's work hours, with each whole roll costing its knit time **plus a
   `Doff`** (`tgt_wt / rate + DOFF_DURATION` work-hours per roll), rounded
   down to whole rolls
2. Beam capacity limits the count below the time-based maximum
    - capacity reflects what is producible before each bar reaches its
      **floor** (`usable = lbs - BEAM_FLOOR_LBS`), with each forced
      mid-stream re-thread (`Hanging` + `Threading`) time — plus the per-roll
      `Doff` time — deducted from available hours, rounded down to whole rolls
    - a max-waste residue discard adds a zero-duration `Waste` (no machine
      time beyond the re-thread), so swapping a near-empty bar early does
      not change the time budget — only the re-threads (`Hanging` +
      `Threading`) and `Doff`s do
3. Multiple mid-stream re-threads fit within the week: returned capacity
   correctly subtracts each `Hanging` + `Threading` interval (and each
   roll's `Doff`)

### 4.2 Preamble required

1. A changeover preamble (yarn and/or family) fits within the week and
   leaves time for production: returned capacity =
   floor((available - preamble_time) / (tgt_wt / rate + DOFF_DURATION)) ×
   tgt_wt, where `preamble_time` counts the `TapeOut`, re-thread (`Hanging` +
   `Threading`), and changeover durations — a `Waste` residue discard is
   zero-duration and adds nothing
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
