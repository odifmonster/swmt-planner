# Specification of coverage of demand module tests

All test specification will be written here, starting with the drainage-focused tests
on FulfillmentViews.

## FulfillmentView tests

Desired test coverage for view objects. RawView's `allocated_lbs` and
view-level `lateness` scalar are already covered; the `RawView` section
below adds coverage for the per-order late-reporting attributes
(`RawOrder.late_lbs` and `RawOrder.late_fill_date`) introduced after the
original RawView suite was written.

### RawView

Per-order late reporting on `RawOrder.late_lbs` and `RawOrder.late_fill_date`,
both written by `RawView.recompute` during the FIFO walk. The view-level
`lateness` scalar and `allocated_lbs` are already covered by the existing
RawView suite; these tests focus on the two new per-order attributes. For
every test, also assert `allocated_lbs` so the late-reporting checks ride
alongside the canonical allocation invariants. Recall that on-hand is stamped
at the first order's `due_date`, so any chunk drawn from on-hand is on-time
for every order it can reach.

1. Empty case
    - No jobs, `on_hand == 0`. Every order has `allocated_lbs == 0`,
    `late_lbs == 0.0`, and `late_fill_date is None`.
2. On-hand only (no jobs)
    1. On-hand fully covers all four weeks' demand
        - Every order fully filled by on-hand. `late_lbs == 0.0` for all
        orders; `late_fill_date == first_due` for all orders.
    2. On-hand partially covers the horizon
        - On-hand exhausts midway through some week N (1 <= N <= 3).
        Orders 0..N have `late_fill_date == first_due` and `late_lbs == 0.0`
        (with order N's `allocated_lbs` being the partial amount). Orders
        N+1..3 have `allocated_lbs == 0`, `late_lbs == 0.0`, and
        `late_fill_date is None`.
3. On-hand + jobs, no late or unfilled orders
    - All four orders fully filled; every contributing chunk arrives at or
    before its target order's `due_date`.
    1. Jobs all end strictly before their target order's `due_date`
        - `late_lbs == 0.0` for every order. `late_fill_date` is the latest
        chunk-arrival time among the chunks that fed that order (either
        `first_due` if on-hand was the last contributor, or the contributing
        job's `end` otherwise).
    2. A job ends exactly on an order's `due_date`
        - Boundary case: `avail_time == due_date` is on-time (not late).
        That order's `late_lbs == 0.0`; `late_fill_date == due_date`.
4. On-hand + jobs, no late orders but some unfilled
    - Total supply < total demand, but everything supplied arrives on time.
    `late_lbs == 0.0` for every order in this group.
    1. Last order partially filled
        - The partially-filled order's `late_fill_date` is the
        `availability_time` of the last chunk that contributed to it. Earlier
        fully-filled orders behave as in section 3.
    2. Last order completely unfilled (no chunk touches it)
        - On that order, `allocated_lbs == 0.0`, `late_lbs == 0.0`, and
        `late_fill_date is None`. Earlier filled orders behave as in section 3.
5. Jobs with late orders
    - Variations where at least one chunk arrives after its target order's
    `due_date`, producing `late_lbs > 0` and a `late_fill_date` past
    `due_date`. Mix of with- and without-on-hand cases.
    1. All four orders filled late, no on-hand
        - Every chunk is a late job. For each order, `allocated_lbs ==
        qty_lbs`, `late_lbs == allocated_lbs` (all of it late),
        `late_fill_date > week.due_date`.
    2. All four orders filled late, on-hand partially fills week 0
        - On-hand covers part of week 0 on-time (stamped at `first_due ==
        week 0's due_date`); the rest of week 0's demand and all of weeks
        1–3 come from late jobs.
            - Week 0: `late_lbs == qty_lbs - on_hand_lbs`, `late_fill_date`
            is the latest late chunk that contributed.
            - Weeks 1–3: `late_lbs == allocated_lbs`, `late_fill_date >
            week.due_date`.
    3. Week 0 fully covered and week 1 partially covered by on-hand; jobs
       fill the rest late
        - Week 0: fully filled by on-hand. `late_lbs == 0.0`,
        `late_fill_date == first_due` (== week 0's due_date).
        - Week 1: on-hand contributes on-time lbs, remainder from late jobs.
        `late_lbs == qty_lbs - (on_hand - week_0.qty_lbs)`, `late_fill_date`
        is the latest late chunk contributing.
        - Weeks 2–3: fully filled by late jobs. `late_lbs == allocated_lbs`,
        `late_fill_date > week.due_date`.
    4. No on-hand; jobs fill weeks 0–1 late but weeks 2–3 on-time
        - Earliest job ends after week 1's `due_date` and its lbs flow to
        weeks 0 and 1 (both late); a later job ends before week 2's
        `due_date` and its lbs flow to weeks 2 and 3 on-time.
            - Weeks 0–1: `late_lbs == allocated_lbs`, `late_fill_date >
            week.due_date`.
            - Weeks 2–3: `late_lbs == 0.0`, `late_fill_date <=
            week.due_date`.
    5. Same as case 4 but on-hand partially fills week 0
        - Week 0: on-hand contributes on-time lbs, remainder from the
        late job. `late_lbs == qty_lbs - on_hand_lbs`, `late_fill_date`
        is the late job's `availability_time` of its last contributing
        chunk.
        - Week 1: fully filled by the late job. `late_lbs ==
        allocated_lbs`, `late_fill_date > week.due_date`.
        - Weeks 2–3: fully filled by the later on-time job. `late_lbs ==
        0.0`, `late_fill_date <= week.due_date`.
    6. Same as case 4 but week 3's demand is partially unmet
        - Weeks 0–1: filled late as in case 4. `late_lbs == allocated_lbs`,
        `late_fill_date > week.due_date`.
        - Week 2: fully filled on-time by the later job. `late_lbs == 0.0`,
        `late_fill_date <= week.due_date`.
        - Week 3: on-time job exhausts before week 3 is satisfied.
        `allocated_lbs < qty_lbs`, `late_lbs == 0.0`, `late_fill_date` is
        the last on-time chunk to contribute (`<= week.due_date`).
    7. Same as case 5 but week 3's demand is partially unmet
        - Week 0: on-hand + late job as in case 5. `late_lbs == qty_lbs -
        on_hand_lbs`, `late_fill_date` is the late job's last contributing
        chunk.
        - Week 1: fully filled by the late job. `late_lbs == allocated_lbs`,
        `late_fill_date > week.due_date`.
        - Week 2: fully filled on-time by the later job. `late_lbs == 0.0`,
        `late_fill_date <= week.due_date`.
        - Week 3: on-time job exhausts before week 3 is satisfied.
        `allocated_lbs < qty_lbs`, `late_lbs == 0.0`, `late_fill_date` is
        the last on-time chunk to contribute (`<= week.due_date`).

### SafetyAwareView

1. ~~Job allocation logic~~ (already covered)
2. Cost tracker calculations
    1. ~~Excess- and carry- only~~ (already covered)
    2. All zero case
        - on-hand = week 0 + safety
        - subsequent jobs fill orders within lead time
    3. Drainage only (no carrying cost or excess)
        1. Constant drainage
            1. Constant drainage at safety target
                - on-hand = week 0
                - all jobs fill orders completely on the due date
            2. Constant drainage between 0 and safety target
            3. Constant drainage capped at safety target
                - no on-hand and no jobs produces same drainage cost as test case 2.3.1.1
        2. Non-constant drainage
            1. No stacked drainage
                - test week 0 <= on-hand < week 0 + safety AND on-hand = week 0 + safety
                - physical pool always returns to safety target before the next drain event
            2. Stacked drainage between jobs
                - cases where after physical pool = safety target but before the next job,
                two drain events occur
                - test different splits between first and second drain events
            3. Stacked drainage interleaved with jobs
                - case where event sequence is drain, chunk, drain and chunk partially restores
                the physical pool
    4. Combined cost trackers
        1. No stacked drainage with carrying and no excess
            - on_hand < week 0 + safety
            - first job (in week 0) over produces to week 1 + safety but under produces to week 2
            - week 2 order brings pool below safety
            - second job (in week 2) produces exactly enough for safety and week 3
        2. No stacked drainage with carrying and excess
            - same as 2.4.1, but the second job over produces
        3. Stacked drainage with carrying and no excess
            - week 0 <= on_hand < week 0 + safety
            - week 0 + week 1 <= on_hand + first_job.lbs < week 0 + safety + week 1 (first job ends in week 0)
            - second job (in week 1, after week 1 due date) produces exactly enough to cover remaining demand and refill safety

## RlsItem tests

These should cover a lot of the same scenarios as the SafetyAwareView tests, but now checking that the
computation works for `register_jobs` and `cost_if`. Many sections will point to previously written tests
or earlier sections for more detail. Both methods take a list of jobs; the single-job variants used in
sections 1–3 below pass a one-element list (`[job]`). Section 4 covers multi-job batches.

1. Job allocation logic
    - All of these tests should be run on the non-empty job allocation logic tests from RawView and
    SafetyAwareView
    - For each test, confirm `cost_if` does not affect the status of the orders
    1. In chronological order
    2. Out of chronological order
2. Cost tracker calculations after `register_jobs`
    - These tests drive scenarios through `register_jobs` (one job at a time, in single-element
    lists) and assert on both views' cost trackers simultaneously: `raw_view.lateness` and
    `safety_view.{drainage, carrying, excess}`. Allocation correctness (`allocated_lbs`) is
    already covered by section 1 for the scenarios where the two overlap; the focus here is on
    the cost values.
    1. Scenarios replayed from the SafetyAwareView cost tests
        - Pick a representative subset of the cases written for SafetyAwareView sections 2.2–2.4 and
        re-run them through `register_jobs`. In each, `raw_view.lateness` should be 0 (those
        scenarios were designed so the raw view sees no actual late deliveries). Suggested coverage:
            - 2.2 (all zero)
            - 2.3.1.1 (constant drainage at safety target)
            - 2.3.2.2 (stacked drainage between jobs, even split)
            - 2.3.2.3 (stacked drainage interleaved with jobs)
            - 2.4.1 (no stacked drainage with carrying)
            - 2.4.3 (stacked drainage with carrying)
    2. Scenarios that exercise both views' cost trackers at once
        - At least one case where some demand is filled by a job ending strictly after its
        target order's due date, producing `raw_view.lateness > 0` alongside non-trivial
        safety-view drainage and/or carrying.
        - Confirms the two views' trackers update independently and consistently when fed the
        same job stream.
3. `cost_if` behavior (single-job hypothetical)
    - These tests verify that the `CostComponents` returned by `cost_if([job])` matches what
    would happen if the hypothetical job were instead passed to `register_jobs`. Each test
    registers some initial jobs (where applicable), calls `cost_if([hypothetical])` that lands
    at a specific position in the existing schedule, and compares the returned components to a
    register-and-snapshot baseline.
    - Each test should also confirm the `RlsItem` state is unchanged after `cost_if` returns
    (orders' `allocated_lbs`, both views' cost trackers, `safety_view.safety_pool`).
    1. No existing jobs
        - `cost_if` called on a freshly constructed `RlsItem` with no prior `register_jobs`.
    2. Hypothetical ends before all existing jobs
    3. Hypothetical ends between existing jobs
    4. Hypothetical ends after all existing jobs
    5. Hypothetical ends at the same time as an existing job
        - `bisect_right` places the hypothetical after the existing job; this is the boundary
        case where insertion position is ambiguous on time alone.
4. Multi-job batch behavior
    - These tests cover the case where `plan_production` emits multiple `Job`s from one
    decision (mid-stream beam exhaustion split, or `'next_runout'` mode's run-up). Both
    `register_jobs` and `cost_if` accept a list and treat the batch as a single update.
    1. `register_jobs([j1, j2])` yields the same end state as `register_jobs([j1])` followed
       by `register_jobs([j2])`. Compare both `CostComponents` and per-order `allocated_lbs`.
    2. `register_jobs([])` is a no-op — cost trackers and allocations unchanged.
    3. `cost_if([j1, j2])` returns the same `CostComponents` as registering the batch and
       reading the view trackers. State unchanged after the call.
    4. `cost_if([j1, j2])` equals `cost_if([j2, j1])` — order in the input list does not affect
       the result, because `register_jobs` sorts by `job.end` internally.
    5. `cost_if([])` returns the current state's cost; state unchanged.