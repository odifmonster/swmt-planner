#!/usr/bin/env python

from datetime import date, datetime, timedelta

from swmtplanner.demand import RlsItem
from swmtplanner.demand.order.order import DemandQty
from swmtplanner.products import Greige
from swmtplanner.schedule import Job

START_DAY = date(2025, 6, 2).toordinal()  # Monday, 2025-06-02

def make_greige(safety=0.0):
    return Greige(
        id='G1',
        family='FAM',
        tgt_wt=100.0,
        top_beam='TB',
        top_pct=0.5,
        btm_beam='BB',
        btm_pct=0.5,
        safety=safety,
        machines={},
    )

def make_job(item, end_offset, lbs):
    """Job ending `end_offset` days after start_day."""
    end = datetime.fromordinal(START_DAY + end_offset)
    return Job(item, end - timedelta(hours=1), end, lbs)

# ---- cascading fulfillment (no safety, no on_hand) ------------------------
# weekly_use=[10, 20, 30] — cumulative demand is 10, 30, 60 across O0..O2.
# A single job ending mid-week-0 produces `lbs` lbs of inventory; it should
# fulfill orders consecutively, with each order's `cumulative` reflecting
# what's left of the cumulative-demand-through-that-order. Per-order `excess`
# = max(0, production - cumulative_demand_through_order).
CASCADE_CASES = [
    ('partial wk0 (5 lbs)',
     5,
     [DemandQty(cumulative=5,  regular=5,  safety=0, excess=0),
      DemandQty(cumulative=25, regular=20, safety=0, excess=0),
      DemandQty(cumulative=55, regular=30, safety=0, excess=0)]),

    ('exact wk0 (10 lbs)',
     10,
     [DemandQty(cumulative=0,  regular=0,  safety=0, excess=0),
      DemandQty(cumulative=20, regular=20, safety=0, excess=0),
      DemandQty(cumulative=50, regular=30, safety=0, excess=0)]),

    ('wk0 + spillover into wk1 (15 lbs)',
     15,
     [DemandQty(cumulative=0,  regular=0,  safety=0, excess=5),
      DemandQty(cumulative=15, regular=15, safety=0, excess=0),
      DemandQty(cumulative=45, regular=30, safety=0, excess=0)]),

    ('wk0 + wk1 exact (30 lbs)',
     30,
     [DemandQty(cumulative=0,  regular=0,  safety=0, excess=20),
      DemandQty(cumulative=0,  regular=0,  safety=0, excess=0),
      DemandQty(cumulative=30, regular=30, safety=0, excess=0)]),

    ('wk0 + wk1 + partial wk2 (45 lbs)',
     45,
     [DemandQty(cumulative=0,  regular=0,  safety=0, excess=35),
      DemandQty(cumulative=0,  regular=0,  safety=0, excess=15),
      DemandQty(cumulative=15, regular=15, safety=0, excess=0)]),

    ('total demand met exactly (60 lbs)',
     60,
     [DemandQty(cumulative=0,  regular=0,  safety=0, excess=50),
      DemandQty(cumulative=0,  regular=0,  safety=0, excess=30),
      DemandQty(cumulative=0,  regular=0,  safety=0, excess=0)]),

    ('production exceeds total demand (70 lbs)',
     70,
     [DemandQty(cumulative=0,  regular=0,  safety=0, excess=60),
      DemandQty(cumulative=0,  regular=0,  safety=0, excess=40),
      DemandQty(cumulative=0,  regular=0,  safety=0, excess=10)]),
]

def test_cascade_single_job():
    for label, lbs, expected_qtys in CASCADE_CASES:
        g = make_greige(safety=0.0)
        r = RlsItem(g, on_hand=0, weekly_use=[10, 20, 30], start_day=START_DAY)
        r.assign(make_job(g, end_offset=1, lbs=lbs))
        for i, (o, exp) in enumerate(zip(r.orders, expected_qtys)):
            actual = o.remaining()
            assert actual == exp, \
                f'[{label}] orders[{i}].remaining()={actual!r}, expected {exp!r}'

def test_cascade_split_across_two_jobs():
    """Splitting one large job into two consecutive jobs must yield the same
    remaining state — assignment is additive, not order-dependent within the
    same week."""
    for label, lbs, expected_qtys in CASCADE_CASES:
        g = make_greige(safety=0.0)
        r = RlsItem(g, on_hand=0, weekly_use=[10, 20, 30], start_day=START_DAY)
        first = lbs // 2
        second = lbs - first
        r.assign(make_job(g, end_offset=1, lbs=first))
        r.assign(make_job(g, end_offset=5, lbs=second))
        for i, (o, exp) in enumerate(zip(r.orders, expected_qtys)):
            actual = o.remaining()
            assert actual == exp, \
                f'[{label} split] orders[{i}].remaining()={actual!r}, expected {exp!r}'

# ---- safety: timing of production matters ---------------------------------
# Per the spec, excess production refills safety stock before flowing to
# subsequent orders. In the implementation, this manifests when production
# happens "ahead of schedule" relative to a given order — i.e. the job ends
# at or before that order's prev_due (the previous order's due_date).
#
# Job ending mid-wk-0 (after start_day): no order's prev_due is on or after
# the job's end *except* O0's, but O0's prev_due is a week before start_day,
# so the job is *after* O0's prev_due too. Safety field stays at the initial
# target for every order; the 5-lb wk0 spillover flows directly into O1.
def test_late_job_does_not_replenish_safety():
    g = make_greige(safety=5.0)
    r = RlsItem(g, on_hand=0, weekly_use=[10, 20, 30], start_day=START_DAY)
    r.assign(make_job(g, end_offset=1, lbs=15))
    expected = [
        DemandQty(cumulative=0,  regular=0,  safety=5, excess=5),
        DemandQty(cumulative=15, regular=15, safety=5, excess=0),
        DemandQty(cumulative=45, regular=30, safety=5, excess=0),
    ]
    for i, (o, exp) in enumerate(zip(r.orders, expected)):
        actual = o.remaining()
        assert actual == exp, \
            f'orders[{i}].remaining()={actual!r}, expected {exp!r}'

# Job ending BEFORE start_day represents production ahead of schedule. For
# orders whose prev_due is on or after the job's end, the early production
# above their prev_lbs goes to safety first. Concretely:
#   - O0.prev_due = start_day - 1 wk: still after the job's end, so no credit.
#   - O1.prev_due = start_day:        cap=job_end, prod_above_prev_lbs(=10) is
#                                     5 lbs, all 5 go to safety -> O1.safety=0.
#   - O2.prev_due = start_day + 1 wk: cap=job_end, but prev_lbs=30 exceeds the
#                                     15 lbs produced, so no safety credit.
# Note: each order's safety field can diverge — the field is independently
# computed per order, so O0/O2 still report the original 5.
def test_early_job_replenishes_safety_for_later_order():
    g = make_greige(safety=5.0)
    r = RlsItem(g, on_hand=0, weekly_use=[10, 20, 30], start_day=START_DAY)
    r.assign(make_job(g, end_offset=-2, lbs=15))
    expected = [
        DemandQty(cumulative=0,  regular=0,  safety=5, excess=5),
        DemandQty(cumulative=20, regular=20, safety=0, excess=0),
        DemandQty(cumulative=45, regular=30, safety=5, excess=0),
    ]
    for i, (o, exp) in enumerate(zip(r.orders, expected)):
        actual = o.remaining()
        assert actual == exp, \
            f'orders[{i}].remaining()={actual!r}, expected {exp!r}'

# ---- on_hand and jobs are interchangeable for the same total inventory ----
# Starting with on_hand=15 and no jobs should yield the same remaining state
# as starting with on_hand=5 and producing a 10-lb job during wk0.
def test_on_hand_and_jobs_compose():
    g1 = make_greige(safety=0.0)
    r1 = RlsItem(g1, on_hand=15, weekly_use=[10, 20, 30], start_day=START_DAY)
    state1 = [o.remaining() for o in r1.orders]

    g2 = make_greige(safety=0.0)
    r2 = RlsItem(g2, on_hand=5, weekly_use=[10, 20, 30], start_day=START_DAY)
    r2.assign(make_job(g2, end_offset=1, lbs=10))
    state2 = [o.remaining() for o in r2.orders]

    assert state1 == state2, \
        f'on_hand=15 vs on_hand=5 + 10-lb job differ:\n  {state1}\n  vs\n  {state2}'

# ---- assignment order is irrelevant for the final state -------------------
# Same set of jobs assigned in any order should yield the same state (since
# update() inserts into a sorted list keyed on end-time).
def test_assign_order_does_not_affect_final_state():
    g1 = make_greige(safety=0.0)
    r1 = RlsItem(g1, on_hand=0, weekly_use=[10, 20, 30], start_day=START_DAY)
    r1.assign(make_job(g1, end_offset=1, lbs=10))
    r1.assign(make_job(g1, end_offset=5, lbs=5))
    r1.assign(make_job(g1, end_offset=8, lbs=20))
    state1 = [o.remaining() for o in r1.orders]

    g2 = make_greige(safety=0.0)
    r2 = RlsItem(g2, on_hand=0, weekly_use=[10, 20, 30], start_day=START_DAY)
    r2.assign(make_job(g2, end_offset=8, lbs=20))
    r2.assign(make_job(g2, end_offset=1, lbs=10))
    r2.assign(make_job(g2, end_offset=5, lbs=5))
    state2 = [o.remaining() for o in r2.orders]

    assert state1 == state2, \
        f'assign-order dependent:\n  {state1}\n  vs\n  {state2}'

def main():
    test_cascade_single_job()
    print(f'All {len(CASCADE_CASES)} cascade single-job cases passed.')
    test_cascade_split_across_two_jobs()
    print(f'All {len(CASCADE_CASES)} cascade split-job cases passed.')
    test_late_job_does_not_replenish_safety()
    print('Late-job (no safety credit) case passed.')
    test_early_job_replenishes_safety_for_later_order()
    print('Early-job (safety credit) case passed.')
    test_on_hand_and_jobs_compose()
    print('on_hand + job composition case passed.')
    test_assign_order_does_not_affect_final_state()
    print('Assign-order independence case passed.')

if __name__ == '__main__':
    main()
