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

**`Roll.knits` provenance (every case above).** For each recorded `Roll`,
assert `roll.knits` is exactly the `Knit` activity object(s) that wound it —
in order and **by identity** (the same `Knit` instances that appear in
`plan.activities`, not just equal values). A single-`Knit` roll holds a
one-tuple; a swap-straddled roll (cases 4, 7) holds the two `Knit`s it was
wound across, pre-swap then post-swap. Across the whole `Job`, concatenating
every `Roll.knits` reproduces the loop's full `Knit` sequence in order, and no
`Knit` is shared between two rolls (`Waste` / `Hanging` / `Threading` / `Doff`
never appear in `knits`). The logical branches are already covered by the cases
above; this adds the link assertion to each rather than new scenarios.

### 2.4 `start_at` mode behavior

**`tgt_order` stamping (all modes).** The optional `tgt_order` argument is
recorded on the **new-item `Job` only**. Pass a sentinel id and assert that
`Job`'s `tgt_order` equals it; the `'next_runout'` run-up `Job` always carries
`tgt_order=None` regardless of the argument. When `tgt_order` is omitted, the
new-item `Job`'s `tgt_order` is `None`. `tgt_order` has no effect on the
activity stream.

1. `start_at='schedule_tail'`
    - the first emitted activity's `start == current_status.as_of`
    - no run-up activities of the current item
    - `plan.jobs` contains exactly one `Job` (the new item)
    - that `Job`'s `tgt_order` equals the passed `tgt_order` argument (and is
      `None` when omitted)
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
    - **`tgt_order`**: the new-item `Job` carries the passed `tgt_order`; the
      run-up `Job`'s `tgt_order` is `None`
    - **run-up `Roll.knits`**: each run-up roll is a single uninterrupted
      `Knit` (no beam work in the run-up), so every run-up `Roll`'s `knits` is
      a one-tuple holding that roll's `Knit` (by identity, from
      `plan.activities`)
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
      `Job`, carrying the passed `tgt_order`
4. `start_at='next_runout'` with `item == current_status.current_item`
    - `plan_production` raises `ValueError` (the same-item guard): that mode
      requires a real changeover, and the new item already matches the
      machine's current item. The error is raised before any activity is
      emitted. (`'schedule_tail'` mode has no such restriction — producing the
      current item from the tail is covered by §2.2 case 1 / §2.4 case 1.)

### 2.5 Purity and commit

1. `plan_production` does not mutate `current_status`, `activities`,
   `jobs`, or the schedule tail
    - call twice with the same args; the two plans must be shape-equal on
      both halves — `plan.activities` (same types, item refs, `lbs`,
      durations) and `plan.jobs` (same item refs, `tgt_order`, per-`Roll`
      `lbs` / `completion_time` offsets, and per-`Roll` `knits` count and
      shape) — allowing only auto-incremented activity / job ids to differ
      (the two runs' `knits` reference each run's own fresh `Knit` instances,
      so compare them positionally against that run's `plan.activities`, not
      by identity across runs)
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

These cases focus on the **activity-stream / preamble** shape. The `Job`-level
provenance is unchanged from §2.4 and not re-asserted per case here: two `Job`s
(`run_up_job`, `new_item_job`), the new-item `Job` carrying the passed
`tgt_order` and the run-up `Job` `None`, and each `Roll.knits` holding the
`Knit`(s) that wound it (run-up rolls one each). At least one §3.2 case should
still assert these once to confirm they hold under a non-trivial changeover.

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


## Phase 5 — Changeover capacity

Covers `schedule/capacity.py` (`ChangeoverCapacity`, `CapacityView`,
`capacity_from_dict`) and the slot waits `plan_production` emits when it is
given a capacity (see "Changeover capacity" and "Changeover capacity
slots" in `schedule/DESIGN.md`). Fixtures: the weekday 24-hour calendar
(`work_days 0–4`, `day_start 0`, `day_end 24`) with Columbus Day
(2026-10-12) as a holiday, and the plant defaults — tape-outs 2 bars per
period, pattern changes 3 per period, both windowed 08:00–24:00. The
plant-wide change cap (`change`: 5 a day, windowed 00:00–24:00) is
rationed only in the items that name it (5.1.8, 5.2.9, 5.5.10–12, 5.6).

### 5.1 Periods

1. **Inside the window** — a Tuesday 10:00 is in Tuesday's period:
   `period_of` returns `day` = that date, `start` 08:00, `end` 24:00.
2. **Third shift** — Tuesday 03:00 is in no period (`period_of` is
   `None`); `next_period` is Tuesday 08:00–24:00.
3. **Exactly at the period end** — Tuesday 24:00 (= Wednesday 00:00) is
   in no period; `next_period` is Wednesday's.
4. **Weekend** — Saturday 10:00 has no period; `next_period` is Monday's.
5. **Holiday** — Monday 2026-10-12 has no period; `next_period` from
   Friday 10-09 24:00 is Tuesday 10-13's.
6. **Window clipped to the work day** — on a calendar whose day ends at
   22:00, the period ends at 22:00, not 24:00; a window that clips to
   nothing (`day_end` before the window start) yields no period that day.
7. **`cal_shift`** — with a non-zero calendar shift, the period bounds
   move by the shift and `period_of` agrees with `offset_work_hours`'s
   notion of the day.
8. **Change periods** — the `change` resource's period is the whole
   working day: Tuesday 03:00 is inside Tuesday's period, 00:00–24:00;
   Saturday has none and `next_period` is Monday's.

### 5.2 `next_slot`

1. **Free period, inside the window** — `not_before` Tuesday 10:00, a
   2-hour single: the slot is 10:00 (slots are not pre-timed).
2. **Before the window opens** — Tuesday 03:00: the slot is 08:00.
3. **Does not fit before the period ends** — Friday 22:00, a 3-hour
   double: Monday 08:00; a 2-hour single at the same moment fits at
   22:00.
4. **Units exhausted** — Friday with 2 tape-out units booked: a single
   requested Friday 09:00 lands Monday 08:00; with Friday 10-09 full it
   lands Tuesday 10-13 08:00 (holiday skipped).
5. **Partial booking** — one unit booked: a single fits today, a double
   goes to the next period.
6. **Pattern changes** — three booked on a day: the fourth goes to the
   next period; the kinds do not share units (a full tape-out day leaves
   pattern changes free).
7. **Unrationed** — a kind with no resource returns `not_before`
   unchanged, and `ChangeoverCapacity(None, {})` never waits for anything.
8. **Over-allowance** — `units > units_per_period` raises `ValueError`.
9. **Changes** — with five changes booked on a Tuesday, the sixth lands
   at Wednesday 00:00; the change units are separate from both per-kind
   rations (a full change day leaves tape-outs free and vice versa).

### 5.3 Bookings and `CapacityView`

1. `book` adds to the `(kind, day)` count; `release` subtracts and never
   goes below zero; `bookings()` lists only non-zero entries; booking an
   unrationed kind is a no-op.
2. A `CapacityView` over a base with `extra` bookings reports
   `booked = base + extra` and finds slots accordingly, while the base
   is unchanged; `bookings()` merges the two.
3. `book` / `release` on a view raise `TypeError`.
4. Booking on the base after the view was made is visible through the
   view (the view reads the base live).

### 5.4 `capacity_from_dict`

1. `None` → no resources (nothing rationed).
2. A full block (`units_per_period`, `window`) builds the matching
   `Resource`s; a kind given as `"default"` takes `DEFAULT_RESOURCES`
   (`change` is 5 a day over 00:00–24:00); a kind without `window` takes
   the default window.
3. A kind left out of the block is unrationed.
4. An unknown kind raises `ValueError`; resources without a work calendar
   raise `ValueError`.

### 5.5 `plan_production` slot waits

Two-machine-free arithmetic: a machine whose preamble needs a tape-out,
planned with and without a capacity.

1. **No capacity** (default) — the plan is identical to Phase 3's: no
   `Idle` is inserted and `capacity_taken` is empty.
2. **Slot free** — the tape-out starts where the preamble reached it, no
   `Idle`, and `capacity_taken` holds one `('tape_out', day, units, start)`
   with `units` 1 for a single bar and 2 for `'both'`.
3. **Slot not free** — with the day's tape-out units already booked, an
   `Idle(reason='tape_out slot')` runs from the preamble moment to the
   next period's start, the `TapeOut` starts there, and every later
   activity shifts by the wait; the `Idle` belongs to no `Job` (it is in
   neither the replaced job's activities nor the new item's).
4. **Third-shift arrival** — a tape-out reached at 03:00 waits until
   08:00 the same day.
5. **Pattern change** — an old machine's cross-family changeover books one
   `pattern_change` unit; with three already booked that day the
   `PatternChange` waits for the next period behind an
   `Idle(reason='pattern_change slot')`, and the re-thread before it is
   not delayed. A `RunnerChange` and a new machine's `StyleChange` book
   nothing and never wait.
6. **Both kinds in one preamble** — a both-bar tape-out and a pattern
   change each take their own slot; with only the tape-out day full the
   plan waits once, before the tape-out, and the pattern change follows
   in the same new period.
7. **`'next_runout'` mode** — the wait is measured from the run-up's end,
   not the schedule tail.
8. **Purity** — planning books nothing: `capacity.booked` is unchanged
   after `plan_production`, and planning the same move twice yields the
   same slot.
9. **`producible_lbs_through`** with a capacity counts the wait against
   the window: a full day's tape-out slots reduce the lbs producible this
   week by the wait's work hours.
10. **The change unit** — with the change cap rationed and free, a
    preamble that tapes out, or changes item without a tape-out (a runner
    change, a new machine's style change, a pattern change), takes one
    `('change', day, 1, start)` slot at the moment the preamble began,
    before its beam work; a plan that continues the current item on
    matching yarn, or only re-threads an empty bar, takes none.
11. **One unit per preamble** — a both-bar tape-out with a pattern change
    books one change unit, beside its own tape-out and pattern-change
    units when those are rationed too.
12. **Waiting for a change slot** — with the day's five changes booked, an
    `Idle(reason='change slot')` runs from the preamble moment to
    midnight, the tape-out (or the changeover activity, when there is no
    tape-out) starts there, every later activity shifts by the wait, and
    the change unit is booked on the new day.

### 5.6 Filling a slot wait

`plan_production(..., fill=Fill(rolls, tgt_order))` (see "Filling a slot
wait" in `schedule/DESIGN.md`). Fixture: the wait machine on A (2800 /
1800 lbs, 100 lbs per hour, 100-lb rolls) changing to D at Tuesday
10:00 with the day's five changes booked, so the change slot is
Wednesday 00:00.

1. **No fill** (the default) — the wait is idle, as in 5.5.
2. **Filling** — with `Fill(3, 'P1@AU0001')`, three `Knit(100)` + `Doff`
   pairs of A run from 10:00, then an `Idle(reason='change slot')` to
   midnight, then the tape-out; `plan.jobs` is a fill job of A — 3 rolls,
   `tgt_order` `'P1@AU0001'`, `fill=True`, activities the knits, doffs
   and the tape-out — followed by D's job, whose activities begin at the
   re-thread; the `Idle` belongs to neither; `replaced_job` is None.
3. **Until the slot** — with `Fill(100, ...)`, rolls are knit while each
   starts before midnight; the last ends after it, the tape-out follows
   its doff with no `Idle`, the change unit is booked on the Wednesday,
   and D's job is still the `lbs` asked for.
4. **Beam-limited** — with yarn for only two whole rolls on a bar, the
   fill stops at two, no set is hung, and the rest of the wait is idle.
5. **Run-up job extended** — a plan that first finishes a roll in
   progress puts the fill rolls on that run-up job: one job of A with
   `fill=True` and the finished roll plus the fill's; the tape-out is
   appended to it.
6. **One budget across waits** — with the change day and the tape-out day
   both full, `Fill(4, ...)` knits four rolls in all across the two
   waits.
7. **`'next_runout'` mode** — the run-up having run the beams out, nothing
   fills and the wait is idle.
8. **The producible cap** — `producible_lbs_through(D, ..., fill=)` lays
   the window out with the fill: D's lbs through Wednesday are at most
   the fill-less figure, and equal those of a plan started at the fill's
   overrun past the slot (eleven 80-minute rolls from 10:00 end 40
   minutes after midnight).

## Phase 6 — Reported sets: foreign bars and passed-over assigned sets

Covers the loader's descriptions of mounted and assigned sets
(`schedule/io.py`, `products.beam_set_from_record`), the machine model's
treatment of a bar whose reported set does not fit the current item
("Foreign bars" in `schedule/DESIGN.md`) and the pass-over of a queued set
that does not fit ("Assigned sets and bar queues"). Fixtures: the
`machine_tests.py` items and beams (`_ITEM_A` needs `40D BLACK 1000X4` on
top and `60D WHITE 1000X4` on the bottom), a `VariantMapFile` built in
memory with two merges — `M1` → `40D BLACK`, `M2` → `40D RED` — and no
masters, and a minimal machines-file entry for `M1` on `_ITEM_A`.

### 6.1 `beam_set_from_record`

1. **Merge known to the map** — a record with merge `M1`, ends 1000,
   beams 4, lbs 900 and `received` gives a set described `40D BLACK
   1000X4`, `known_merge`, `lbs = 900`, `avail_date` the receipt, the
   record's vendor, denier, luster and type, `assigned` per the flag.
2. **Merge unknown** — merge `ZZ` with denier 40, luster `SD`, desc `POLY`
   normalises to `40D WHT` (per `normalize_merge`), not `known_merge`.
3. **Not polyester** — a record whose yarn normalises to nothing returns
   `None`, and `beam_sets_from_list` leaves it out of the dict.

### 6.2 Mounted-set descriptions (`machines_from_list`)

Each case loads one machine on `_ITEM_A` and inspects
`initial_status.beam('top')`.

1. **Export holds the set** — `init_top_set = {set_no: 'S1', merge: 'M2'}`
   with `beam_sets` holding `S1` as `40D RED 1000X4`: the bar's set is
   described `40D RED 1000X4` (the export's), with the export's denier /
   luster / type, and does not fit the item (the bar is foreign).
2. **Merge known, export lacks the set** — `init_top_set = {set_no: 'S2',
   merge: 'M2'}` and no export: the description is the merge's yarn at the
   label's construction, `40D RED 1000X4`; with merge `M1` instead it is
   `40D BLACK 1000X4` and fits.
3. **No yarn evidence** — a set with no merge, or a merge the map does not
   know, or no `init_top_set` at all: the description is the item's label
   (`40D BLACK 1000X4`), as before; the same when no `variant_map` is
   passed.
4. **Recipe merge** — a machine named by variant whose recipe supplies the
   merge (through `variant_map.masters`) describes the bar with that
   merge's yarn, which fits by construction.
5. **Roll in progress on a foreign bar** — `init_roll_lbs = 300` with the
   top set foreign (case 2, merge `M2`): `initial_status.roll_lbs_remaining
   == 0`; with a fitting set it is 300.

### 6.3 Assigned-set records (`machines_from_list`, `assigned_sets`)

1. **Export form** — a record for `M01` bar 2 (the top) with merge `M2`
   and the export's yarn fields: `initial_status.queue('top')` holds one
   set described `40D RED 1000X4`, `assigned`, with the record's lbs and
   receipt; it does not fit `_ITEM_A`'s top.
2. **Export holds the set** — the same set number in `beam_sets` (same
   vendor): the queue holds the export's object, whatever the record's
   yarn fields say.
3. **Older form** — a record with only `set_no`, `merge`, `vendor`: the
   queue holds a set described by the bar's requirement with a fresh-beam
   weight (as before); the same when no `variant_map` is passed.
4. **Not polyester** — a record whose yarn normalises to nothing is left
   out of the queue; the records behind it keep their order.
5. **Other machines** — records for machines not in the list are ignored,
   and a bar-1 record goes to `btm`, any higher bar to `top`.

### 6.4 Foreign bars in the machine model

Machines built with `_make_machine(init_top_beam=_ALT_TOP_BEAM)` — a
`30D RED 1000X4` set that does not fit `_ITEM_A`'s top — unless stated.

1. **Construction zeroes the roll** — `init_roll_lbs_remaining = 300` with
   a foreign top: `initial_status.roll_lbs_remaining == 0`; the bar is
   still reported `threaded` with its lbs.
2. **No run-up** — `whole_rolls_before_runout == 0` and `next_runout ==
   start` with plenty of lbs on both bars; with both bars fitting the
   same lbs give the usual rolls.
3. **Preamble tapes out the foreign set** — `plan_production(_ITEM_A, 1
   roll, 'schedule_tail')` on the same item: the activities open with
   `TapeOut('top')` carrying the foreign set and its lbs, then
   `Hanging('top')` + `Threading('top')` of a fitting set, then the knit;
   no changeover activity (the item is unchanged); the set is in
   `beam_sets_returned` with its lbs.
4. **Waste below the limit** — the foreign top holding `BEAM_FLOOR_LBS +
   10` lbs is dropped with `Waste('top')` instead of a tape-out.
5. **`'next_runout'` mode** — a changeover to `_ITEM_B` emits no run-up
   roll (no current-item `Job`), the tape-out first, then the new item's
   preamble; the foreign set's tape-out attaches to no job (nothing
   produced the previous item).
6. **Both bars foreign** — a single `TapeOut('both')` and a `'both'`
   re-thread.
7. **`producible_lbs_through`** on the current item counts no run-up lbs:
   its figure for a window is strictly less than the same machine's with
   a fitting top set, by at least the tape-out's and re-thread's hours of
   production.

### 6.5 Passing over a queued set

Machines built with `init_top_queue` holding sets of the
`machine_tests.py` fixtures; `Q_BAD` is a `30D RED 1000X4` set, `Q_OK` a
`40D BLACK 1000X4` one, both `assigned`.

1. **Dropped and recorded** — a top queue `(Q_BAD,)` and a plan that
   re-threads the top (the top run down to the floor): the `Hanging`
   mounts the automatic pick (stock, or an invented set), its
   `passed_over == (('top', Q_BAD),)`, and `plan.queue_passed_over` holds
   one `PassedOver` with `bar 'top'`, `beam_set Q_BAD`, `wanted` the
   item's top requirement and `at` the hang's start. `beam_sets_returned`
   does not list `Q_BAD`.
2. **The next queued set is considered** — queue `(Q_BAD, Q_OK)`: the hang
   mounts `Q_OK`, passes over only `Q_BAD`, and the status after the
   hang has an empty top queue.
3. **A fitting front is untouched** — queue `(Q_OK, Q_BAD)`: `Q_OK` is
   hung, nothing is passed over, `Q_BAD` stays queued.
4. **Commit keeps it** — after `commit_plan`, `current_status.queue('top')`
   no longer holds `Q_BAD`, `status_at(hang end)` agrees, and
   `Machine.queue_passed_over` holds the record; a second plan on the
   machine does not report it again. Two commits that each pass a set
   over accumulate in commit order.
5. **Purity** — `plan_production` leaves `current_status.queue('top')`
   unchanged until committed.
6. **`Status.drop_queued`** — drops the front and nothing else (`as_of`,
   bars, item unchanged); raises `ValueError` on an empty queue.
7. **Applying a `Hanging` with `passed_over`** removes the named sets
   from their bars' queues wherever they sit, and then pops the front if
   it is the set hung; a set already absent is a no-op.
8. **Manual assignment still locked** — with `Q_OK` at the front, an
   `assign` naming another set raises as before; with `Q_BAD` at the
   front, the assignment is honoured after the pass-over.

### 6.6 Blacklisted merges

`BeamSet.blacklisted`, `products.normalize_blacklist` / `is_blacklisted`,
the loaders' `blacklist=` and the two rules of "Blacklisted merges" in
`schedule/DESIGN.md`. Fixtures: the Phase 6 loader fixtures (`_load`,
`_entry`, `_record`, `_VMAP`, whose merge `M1` is `_ITEM_A`'s top yarn)
and the 6.5 queued machine.

1. **The flag** — a set built with `blacklisted=True` fits nothing, even
   the requirement its twin without the flag fits; `returned` keeps the
   flag and `relabelled(like)` takes `like`'s; `BeamSet.new` is never
   blacklisted; `worth_stocking` is False for a blacklisted set however
   many lbs it holds, so `build_inventory` leaves it out.
2. **Codes** — `normalize_blacklist` of a list gives a `Blacklist` of
   merge codes, trimmed, upper-cased, empties dropped; `is_blacklisted`
   matches trimmed and case-insensitively and exactly (`292286` is not
   `292286BAD`), never for `None`, and takes a plain collection as merge
   codes; `beam_set_from_record` / `beam_sets_from_list` stamp a record
   whose merge is listed and leave the others.
2a. **Vendors and sets** — `normalize_blacklist` of an object with
   `merges`, `vendors` and `sets` fills the three lists (a missing key is
   empty; an unknown key or a non-list value raises `TypeError`, as does
   a bare string); `covers` / `is_blacklisted` match a set by its vendor
   (exactly: `Unifi Manufacturing, Inc` is not `Unifi/Nanya`) or its set
   number, a `None` vendor or set number matching nothing; the loaders
   stamp an export record by vendor and by set number, an assigned-set
   record by vendor, and a mounted set by set number
   (`machines_from_list`), each leaving an unlisted twin alone.
3. **A mounted set is a foreign bar** — `machines_from_list` with a
   blacklist naming the mounted top set's merge: the machine's top beam is
   `blacklisted`, `whole_rolls_before_runout == 0`, `next_runout` is the
   start, and `plan_production` on the current item opens with
   `TapeOut('top')` carrying the set, then re-threads the bar; the set is
   not in `beam_sets_returned`. Without the blacklist the same entry runs
   up as usual.
4. **A queued set is passed over** — a queue front that fits the bar but
   is blacklisted is passed over with `reason 'blacklisted'` and the next
   queued set considered; a non-fitting front's record reads `'does not
   fit'`; an assigned-set record built by the loader with a listed merge
   comes out `blacklisted`.
5. **A manual assignment is refused** — `assign={'top': [S]}` naming a
   blacklisted set that would otherwise be in stock raises `ValueError`.

### 6.7 Hung and queued-set status

The assigned-sets record's `status` (`machines_from_list`), the hung bar
in the machine model (`init_*_threaded`, "Hung bars") and the `Unhang`
activity. Fixtures: the Phase 6 loader fixtures and the `machine_tests.py`
sets.

1. **Status parsing** — a record without `status` is `inventory`; `staged`
   / `hung` are accepted trimmed and case-insensitively; any other value
   raises `ValueError`. A queued set carries its status as `location`
   (`'inventory'` / `'staged'`), whether built from the record or taken
   from the export; a hung set's `location` is empty and it is not
   `assigned`.
2. **A hung set replaces the bar** — an entry naming `init_top_set` S0
   with 200 lbs and a `hung` record for bar 2 naming S2 (900 lbs): the
   machine's top beam is S2 at 900 lbs, `threaded('top')` is False, the
   roll in progress is zeroed, and the top queue is empty; the machines
   file's `init_top_lbs` is ignored. Two `hung` records for one bar raise
   `ValueError`; a hung record whose yarn normalises to nothing raises.
3. **A hung bar in the model** — `Machine(..., init_top_threaded=False,
   init_roll_lbs_remaining=50)`: `roll_lbs_remaining` is 0,
   `whole_rolls_before_runout` is 0, `next_runout` is the start; the
   plan for the current item opens `Threading('top')` then `Knit` — no
   `Hanging`, no `TapeOut` — and the `Threading` is in the new job's
   activities.
4. **Batching** — both bars hung: one `Threading('both')`; the top hung
   and the bottom empty: `Hanging('btm')` then `Threading('both')`.
5. **A hung set that does not fit** — a foreign top (`_ALT_TOP_BEAM`)
   hung: the plan opens `Unhang('top')` with `start == end`, carrying the
   set at all its lbs, then `Hanging('top')` + `Threading('top')`; the
   set is in `beam_sets_returned` with those lbs; with the per-kind and
   change rations given, `capacity_taken` is empty (no tape-out unit, no
   change unit for the current item); a blacklisted hung set is unhung
   and not returned. Both bars hung and foreign give one `Unhang('both')`.
6. **Guard rails** — applying an `Unhang` to a threaded bar, or to an
   empty one, raises `ValueError`; on a hung bar it empties it (beam None,
   lbs 0, not threaded).
7. **No job** — the `Unhang` is in neither the previous nor the new job's
   activities (like `Waste`); `replaced_job` is None.

### 6.8 Large beams

`BeamSet.size` / `is_large`, `products.parse_size`, `Machine.accepts` and
the places the rule is applied ("Large beams" in `schedule/DESIGN.md`).
Fixtures: the Phase 6 loader fixtures; `_LARGE` is a `40D BLACK 1000X4`
set of size `40 x 42`, `_SMALL` one of `21 x 42`; machines built with
`is_new` True or False.

1. **Size** — `parse_size` reads `40 x 42`, `40x42`, `21.5 x 42"` and a
   two-element list, gives None for nothing and raises on `big`; a record
   with `size` builds a set with `size`, `diameter` and `is_large` (40 or
   more); one without has `size` None and is not large. `returned`,
   `relabelled` and `located` keep the size.
2. **`accepts`** — a new machine accepts every set; an old one every set
   but a large one; a set of unknown size is accepted everywhere.
3. **Pull order** — `stock_order` puts a large set before an older small
   one and otherwise sorts by receipt then set number; the plan's
   automatic pick on a new machine takes `_LARGE` over an older
   `_SMALL`, on an old machine `_SMALL` with `_LARGE` left in stock; a
   manual `assign` of `_LARGE` on an old machine raises `ValueError`
   (`too large for this machine`) and on a new one is honoured.
4. **Queue** — `_LARGE` at the front of an old machine's queue is passed
   over with reason `'too large for this machine'` and the next queued
   set considered; on a new machine it is hung.
5. **Mounted** — `_LARGE` threaded on an old machine's top: no run-up,
   the roll zeroed, and the first plan tapes it out (`beam_sets_returned`
   holds it) and re-threads; hung and not threaded, it is unhung. On a
   new machine it runs as usual.
6. **Loader and JSON** — a machines-file `init_top_set` the export holds
   with a size comes out with that size; the schedule JSON beam object
   carries `"size": "40 x 42"` and no key for an unknown size.

### 6.9 An item the machine cannot run

`Machine.can_run_current_item` and the run-up rule for a machine whose
current item's machine list leaves it out ("An item the machine cannot
run" in `schedule/DESIGN.md`). Fixture: `_ITEM_X`, `_ITEM_A`'s yarn and
family, runnable on `M2` only; `_ITEM_U` on the `30D RED` / `90D GREEN`
yarn, runnable on `M1`. Machines built with `_make_machine(init_item=
_ITEM_X)` — the fitting `_TOP_BEAM` / `_BTM_BEAM` sets, threaded.

1. **Flag and roll** — `can_run_current_item` is False (True for `_ITEM_A`
   and for `NONE`); `init_roll_lbs_remaining = 50` comes out as
   `initial_status.roll_lbs_remaining == 0`, the bars still threaded with
   their lbs.
2. **No run-up** — `whole_rolls_before_runout == 0`, `next_runout ==
   start`, and `_can_fill_roll` is False, with plenty of lbs on both
   bars.
3. **`run_until`** — one `Idle` from `start` to `t`, no jobs; `None`
   when `t` is not after the tail.
4. **Same-yarn move keeps the sets** — `plan_production(_ITEM_A, 1 roll,
   'schedule_tail')`: no `TapeOut`, `Waste` or `Hanging`; a
   `RunnerChange` then the knit; one job, of `_ITEM_A`. In
   `'next_runout'` mode the same, with no run-up job.
5. **Other-yarn move tapes out the real sets** — `plan_production(_ITEM_U,
   1 roll, 'schedule_tail')`: a `TapeOut('both')` and
   `beam_sets_returned` holding the two sets with 200 and 300 lbs.

## Phase 7 — Assigning sets after planning

Covers `BeamSet.relabelled`, `activity.rebind_sets`, `Status.rebind_sets`,
`Machine.rebind_sets`, `Knit.top_beam` / `btm_beam` and `assign_sets`
("Assigning sets after planning" in `schedule/DESIGN.md`). Fixtures as in
`machine_tests.py`; `R1` is a stock set for `_ITEM_B`'s top (`30D RED
1000X4`, 900 lbs, merge `M1`, vendor `V`), `R2` a second one received a day
later.

### 7.1 Relabelling

1. **`BeamSet.relabelled`** — a placeholder (`NEW…`, 2800 lbs, label `L`,
   available at `t`) relabelled like `R1` has `R1`'s set number, merge,
   vendor, denier, luster, type and `known_merge`, but 2800 lbs, label `L`
   and availability `t`; `assigned` is False.
2. **`rebind_sets` on activities** — a `Knit`, `Waste`, `TapeOut` and
   `Hanging` referencing the placeholder come back with the same id, times
   and lbs and the relabelled set in its place; an activity referencing
   no mapped set (a `Doff`, a `Hanging` of another set) comes back as the
   same object; a `Hanging`'s `passed_over` is untouched.
3. **`Status.rebind_sets`** — a status whose top holds the placeholder
   gets the relabelled set on top with `lbs_remaining`, `threaded` and
   the queues unchanged; one holding no mapped set is returned as is.
4. **`Machine.rebind_sets`** — after a committed plan whose `B` hang
   invented a placeholder, rebinding `{placeholder id: R1}` relabels the
   `Hanging`, the `Knit`s that ran on it and the `TapeOut` that removed
   it in `activities`; the same objects appear in `jobs[].activities` and
   `rolls[].knits`; `current_status.beam('top')` carries `R1`'s number;
   job ids and activity ids are unchanged; `status_at` still replays; an
   empty mapping is a no-op.

### 7.2 Knits carry their sets

1. Every `Knit` a plan emits has `top_beam` / `btm_beam` equal to the sets
   on the bars at its start — the initial sets for the first knit, the
   hung set after a re-thread — so a roll that straddles a swap has two
   knits naming different sets on the swapped bar.

### 7.3 `assign_sets`

Two machines planned with **no inventory** (every hang a placeholder):
`M1` changes to `_ITEM_B` after one roll, `M2` after three; the inventory
holds `R1` and `R2` for `B`'s top.

1. **Runout order** — `M1`'s earlier hang gets `R1` (oldest received),
   `M2`'s gets `R2`; `hangs` lists them in that order with `source
   'stock'`, the placeholder, `plan_lbs` the placeholder's and `set_lbs`
   the set's; `mapping` maps both placeholder ids; both machines are
   rebound (their `Hanging`s name `R1` / `R2`).
2. **Ties** — two hangs at the same moment are walked by machine id, then
   bar.
3. **Availability** — a set received after a hang is not its candidate:
   with `R1` received after `M1`'s hang but before `M2`'s, `M1` stays
   `new` and `M2` takes `R1`.
4. **Pull order** — a large (40 in) set is chosen before an older
   small one on a new machine (`choose_stock`: large first, then oldest
   received, then set number); on an old machine the large set is not a
   candidate and the small one is taken. The outgoing set's merge plays
   no part.
5. **Returned sets** — `M1` changes to `B` and back to `A` (its `B` set
   taped out) before `M2`'s `B` hang; with one `B` set in stock, both
   hangs get it, and `M2`'s `set_lbs` is the set's pounds less what `M1`
   drew (`consumed`); a set returned under `worth_stocking` is not
   offered again.
6. **Shortfall** — a set whose usable pounds are below what the plan
   draws before the bar's next hang reports `short_by` the difference;
   otherwise 0.
7. **Nothing suitable** — a hang with no fitting stock keeps its
   placeholder (`hung None`, `source 'new'`, listed in `still_new`) and
   the machine's `Hanging` still names `NEW…`.
8. **Purity** — `inventory` is unchanged after the call; the plant's
   queued sets (real, hung in pass one) are not touched.

### 7.4 Job provenance

1. `plan_production(..., prior_job='J9')` stamps `prior_job` on the new
   item's `Job` (and not on a `'next_runout'` run-up job); the default is
   None; `Job.with_activities` and `replace` keep it.
