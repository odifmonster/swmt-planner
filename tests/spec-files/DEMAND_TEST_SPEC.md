# Specification of coverage of demand module tests

All test specification will be written here, starting with the drainage-focused tests
on FulfillmentViews.

## FulfillmentView tests

Desired test coverage for view objects. RawView tests are already covered.

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
computation works for `register_job` and `cost_if`. Many sections will point to previously written tests
or earlier sections for more detail.

1. Job allocation logic
    - All of these tests should be run on the non-empty job allocation logic tests from RawView and
    SafetyAwareView
    - For each test, confirm `cost_if` does not affect the status of the orders
    1. In chronological order
    2. Out of chronological order
2. Cost tracker calculations after `register_job`
    - These tests drive scenarios through `register_job` and assert on both views' cost trackers
    simultaneously: `raw_view.lateness` and `safety_view.{drainage, carrying, excess}`. Allocation
    correctness (`allocated_lbs`) is already covered by section 1 for the scenarios where the two
    overlap; the focus here is on the cost values.
    1. Scenarios replayed from the SafetyAwareView cost tests
        - Pick a representative subset of the cases written for SafetyAwareView sections 2.2–2.4 and
        re-run them through `register_job`. In each, `raw_view.lateness` should be 0 (those
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
3. `cost_if` behavior
    - These tests verify that the `CostComponents` returned by `cost_if` matches what would
    happen if the hypothetical job were instead passed to `register_job`. Each test registers
    some initial jobs (where applicable), calls `cost_if` with a hypothetical that lands at a
    specific position in the existing schedule, and compares the returned components to a
    register-and-snapshot baseline.
    - Each test should also confirm the `RlsItem` state is unchanged after `cost_if` returns
    (orders' `allocated_lbs`, both views' cost trackers, `safety_view.safety_pool`).
    1. No existing jobs
        - `cost_if` called on a freshly constructed `RlsItem` with no prior `register_job`.
    2. Hypothetical ends before all existing jobs
    3. Hypothetical ends between existing jobs
    4. Hypothetical ends after all existing jobs
    5. Hypothetical ends at the same time as an existing job
        - `bisect_right` places the hypothetical after the existing job; this is the boundary
        case where insertion position is ambiguous on time alone.