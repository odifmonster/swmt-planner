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