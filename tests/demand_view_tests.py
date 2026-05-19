#!/usr/bin/env python

import json
import unittest
from collections import namedtuple
from datetime import datetime, timedelta
from pathlib import Path

from swmtplanner.demand.order import WeeklyDemand
from swmtplanner.demand.view import RawView, SafetyAwareView
from swmtplanner.products import Greige


# RawView / SafetyAwareView touch `.item` on the rls_item (and through it
# `.id` and `.safety`), `.lead_time` on the rls_item (for carrying-cost math),
# and `.end` / `.lbs` on each job. We stand in for RlsItem and Job with
# namedtuples, and use real Greige objects loaded from the canonical fixture
# file so the safety-stock target matches real inputs.
_DEFAULT_LEAD_TIME = timedelta(days=7)
_FakeRlsItem = namedtuple('_FakeRlsItem', ['item', 'lead_time'], defaults=[_DEFAULT_LEAD_TIME])
_FakeJob = namedtuple('_FakeJob', ['end', 'lbs', 'rolls'], defaults=[()])


_GREIGE_FIXTURE = Path(__file__).parent / 'data-files' / 'greige-styles.json'


def _load_greiges() -> dict[str, Greige]:
    with _GREIGE_FIXTURE.open() as f:
        data = json.load(f)
    return {
        g['id']: Greige(
            id=g['id'],
            family=g['family'],
            tgt_wt=g['tgt_wt'],
            top_beam=g['top_beam'],
            top_pct=g['top_pct'],
            btm_beam=g['btm_beam'],
            btm_pct=g['btm_pct'],
            safety=g['safety'],
            machines={m['id']: m['rate'] for m in g['machines']},
        )
        for g in data
    }


_GREIGES = _load_greiges()


_START = datetime(2026, 1, 1)


def _make_weekly_demand(qtys: list[float]) -> list[WeeklyDemand]:
    return [
        WeeklyDemand(
            week_idx=i,
            due_date=_START + timedelta(days=7 * (i + 1)),
            qty_lbs=qty,
        )
        for i, qty in enumerate(qtys)
    ]


def _make_view(qtys: list[float], greige_id: str = 'AU4782K') -> RawView:
    rls_item = _FakeRlsItem(item=_GREIGES[greige_id])
    return RawView(rls_item, _make_weekly_demand(qtys))


def _make_safety_view(
    qtys: list[float],
    greige_id: str = 'AU2958G',
    lead_time: timedelta = _DEFAULT_LEAD_TIME,
) -> SafetyAwareView:
    # AU2958G has safety=1400, a convenient size for hand-computed allocations.
    rls_item = _FakeRlsItem(item=_GREIGES[greige_id], lead_time=lead_time)
    return SafetyAwareView(rls_item, _make_weekly_demand(qtys))


def _job(week_offset: int, lbs: float) -> _FakeJob:
    # job.end timestamps are not used by recompute beyond preserving FIFO
    # order; we set them to a reasonable per-week offset so the assumed
    # invariant (jobs sorted by job.end) is naturally satisfied.
    return _FakeJob(end=_START + timedelta(days=7 * week_offset), lbs=lbs)


def _job_at(end_dt: datetime, lbs: float) -> _FakeJob:
    return _FakeJob(end=end_dt, lbs=lbs)


# Convenience: due_date for week i in our standard 4-week setup starting _START.
def _due(week_idx: int) -> datetime:
    return _START + timedelta(days=7 * (week_idx + 1))


class RawViewRecomputeTests(unittest.TestCase):

    def test_empty_jobs_zero_on_hand_does_not_fill(self):
        view = _make_view([100, 200, 150, 300])
        view.recompute(jobs=[], on_hand=0)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [0.0, 0.0, 0.0, 0.0],
        )
        self.assertEqual(view.lateness, 0.0)

    def test_empty_jobs_with_on_hand_fills_earliest_first(self):
        view = _make_view([100, 200, 150, 300])
        # 250 lbs covers order 0 (100) and partially fills order 1 (150).
        view.recompute(jobs=[], on_hand=250)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 150.0, 0.0, 0.0],
        )
        # on_hand is stamped at order 0's due_date, so on-time for every order.
        self.assertEqual(view.lateness, 0.0)

    def test_jobs_only_fills_orders_and_consumes_jobs_sequentially(self):
        # Stream lbs: 300, 200 → 500 total against demand [100, 200, 150, 300].
        # Order 0 takes 100 from job1 (200 left in job1).
        # Order 1 takes 200 from job1 (depleted).
        # Order 2 takes 150 from job2 (50 left).
        # Order 3 takes the remaining 50 from job2; short by 250.
        view = _make_view([100, 200, 150, 300])
        jobs = [_job(week_offset=1, lbs=300), _job(week_offset=2, lbs=200)]
        view.recompute(jobs=jobs, on_hand=0)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 200.0, 150.0, 50.0],
        )
        # Job1.end == week_0.due, job2.end == week_1.due; all chunks land
        # at-or-before the orders they fill, so nothing is strictly late.
        self.assertEqual(view.lateness, 0.0)

    def test_on_hand_drains_before_jobs(self):
        # on_hand 50 then jobs of 300 and 200 against demand [100, 200, 150, 300].
        # Order 0: 50 from on_hand (depleted), 50 from job1 (250 left).
        # Order 1: 200 from job1 (50 left).
        # Order 2: 50 from job1 (depleted), 100 from job2 (100 left).
        # Order 3: 100 from job2; short by 200.
        view = _make_view([100, 200, 150, 300])
        jobs = [_job(week_offset=1, lbs=300), _job(week_offset=2, lbs=200)]
        view.recompute(jobs=jobs, on_hand=50)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 200.0, 150.0, 100.0],
        )
        self.assertEqual(view.lateness, 0.0)

    def test_zero_demand_weeks_in_middle_are_skipped(self):
        # Demand [100, 0, 50, 0] with 150 on hand fills order 0 then order 2;
        # the zero-demand weeks should not consume any lbs.
        view = _make_view([100, 0, 50, 0])
        view.recompute(jobs=[], on_hand=150)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 0.0, 50.0, 0.0],
        )
        self.assertEqual(view.lateness, 0.0)

    def test_lateness_one_day_late(self):
        # Single job, 100 lbs, ends 1 day after week 0's due_date.
        # Expected: 100 * 2^1 = 200.
        view = _make_view([100, 0, 0, 0])
        jobs = [_job_at(_due(0) + timedelta(days=1), lbs=100)]
        view.recompute(jobs=jobs, on_hand=0)
        self.assertEqual(view.orders[0].allocated_lbs, 100.0)
        self.assertAlmostEqual(view.lateness, 200.0)

    def test_lateness_two_days_late_doubles(self):
        # Single job, 100 lbs, ends 2 days after week 0's due_date.
        # Expected: 100 * 2^2 = 400 (i.e., doubled from the 1-day-late case).
        view = _make_view([100, 0, 0, 0])
        jobs = [_job_at(_due(0) + timedelta(days=2), lbs=100)]
        view.recompute(jobs=jobs, on_hand=0)
        self.assertAlmostEqual(view.lateness, 400.0)

    def test_lateness_fractional_days(self):
        # Half a day late: 100 * 2^0.5 = 100 * sqrt(2) ≈ 141.421...
        view = _make_view([100, 0, 0, 0])
        jobs = [_job_at(_due(0) + timedelta(hours=12), lbs=100)]
        view.recompute(jobs=jobs, on_hand=0)
        self.assertAlmostEqual(view.lateness, 100.0 * (2.0 ** 0.5))

    def test_lateness_chunks_to_different_orders_accumulate(self):
        # Single job, 200 lbs, ends 1 day after week 1's due_date.
        # That is 8 days late for week 0 and 1 day late for week 1.
        # Order 0 takes 100 lbs (8 days late) → 100 * 2^8 = 25600.
        # Order 1 takes 100 lbs (1 day late)  → 100 * 2^1 = 200.
        # Total = 25800.
        view = _make_view([100, 100, 0, 0])
        jobs = [_job_at(_due(1) + timedelta(days=1), lbs=200)]
        view.recompute(jobs=jobs, on_hand=0)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 100.0, 0.0, 0.0],
        )
        self.assertAlmostEqual(view.lateness, 100.0 * 2.0**8 + 100.0 * 2.0**1)

    def test_lateness_on_time_chunks_do_not_contribute(self):
        # One job ends 1 day late for week 0 but on time for week 1.
        # Demand [50, 50, 0, 0], job ends at week_0.due + 1 day, 100 lbs.
        # Order 0 takes 50 (1 day late) → 50 * 2 = 100.
        # Order 1 takes 50 — job.end = week_0.due + 1 day, week_1.due is 7 days
        # past week_0.due, so the chunk is well within on-time for week 1.
        # Total lateness = 100.
        view = _make_view([50, 50, 0, 0])
        jobs = [_job_at(_due(0) + timedelta(days=1), lbs=100)]
        view.recompute(jobs=jobs, on_hand=0)
        self.assertAlmostEqual(view.lateness, 100.0)

    def test_lateness_resets_between_recomputes(self):
        # First recompute introduces lateness; second with no jobs clears it.
        view = _make_view([100, 0, 0, 0])
        view.recompute(jobs=[_job_at(_due(0) + timedelta(days=1), lbs=100)], on_hand=0)
        self.assertGreater(view.lateness, 0)
        view.recompute(jobs=[], on_hand=100)
        self.assertEqual(view.lateness, 0.0)

    def test_on_hand_covers_partial_order_only_remainder_is_late(self):
        # Demand [100, 0, 0, 0]. 30 lbs on hand cover part of order 0 on time;
        # the remaining 70 come from a job that ends 1 day past week 0's due.
        # Only the 70 lbs from the job should be counted late.
        # Expected lateness = 70 * 2^1 = 140.
        view = _make_view([100, 0, 0, 0])
        jobs = [_job_at(_due(0) + timedelta(days=1), lbs=70)]
        view.recompute(jobs=jobs, on_hand=30)
        self.assertEqual(view.orders[0].allocated_lbs, 100.0)
        self.assertAlmostEqual(view.lateness, 140.0)

    def test_on_hand_covers_full_order_lateness_only_on_subsequent(self):
        # Demand [100, 100, 0, 0]. 100 lbs on hand fully cover order 0 on time.
        # A late job (100 lbs, ending 1 day past week 1's due) then fills
        # order 1. Order 0 contributes no lateness; order 1 contributes
        # 100 * 2^1 = 200.
        view = _make_view([100, 100, 0, 0])
        jobs = [_job_at(_due(1) + timedelta(days=1), lbs=100)]
        view.recompute(jobs=jobs, on_hand=100)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 100.0, 0.0, 0.0],
        )
        self.assertAlmostEqual(view.lateness, 200.0)

    # --- Per-order late reporting (RawOrder.late_lbs / late_fill_date) ---

    def test_late_reporting_empty_case(self):
        # Section 1: no jobs, zero on_hand. Every order untouched, so
        # allocated_lbs == 0, late_lbs == 0, and late_fill_date is None.
        view = _make_view([100, 200, 150, 300])
        view.recompute(jobs=[], on_hand=0)
        for o in view.orders:
            self.assertEqual(o.allocated_lbs, 0.0)
            self.assertEqual(o.late_lbs, 0.0)
            self.assertIsNone(o.late_fill_date)

    def test_late_reporting_on_hand_only_fully_covers_horizon(self):
        # Section 2.1: on_hand = 750 exactly covers all four weeks' demand
        # (100 + 200 + 150 + 300). On-hand is stamped at first_due, so every
        # order is filled on-time by a single contributing chunk.
        # late_lbs == 0 for all orders; late_fill_date == first_due for all.
        view = _make_view([100, 200, 150, 300])
        view.recompute(jobs=[], on_hand=750)
        first_due = _due(0)
        expected_alloc = [100.0, 200.0, 150.0, 300.0]
        for o, alloc in zip(view.orders, expected_alloc):
            self.assertEqual(o.allocated_lbs, alloc)
            self.assertEqual(o.late_lbs, 0.0)
            self.assertEqual(o.late_fill_date, first_due)

    def test_late_reporting_on_hand_only_partially_covers_horizon(self):
        # Section 2.2: on_hand = 250 fully covers week 0 (100) and partially
        # fills week 1 (150 of 200). Weeks 2 and 3 see no chunk at all.
        # Orders 0–1: late_fill_date == first_due, late_lbs == 0.
        # Orders 2–3: allocated_lbs == 0, late_lbs == 0, late_fill_date is None.
        view = _make_view([100, 200, 150, 300])
        view.recompute(jobs=[], on_hand=250)
        first_due = _due(0)
        # Order 0 fully filled, order 1 partial — both on-time via on-hand.
        self.assertEqual(view.orders[0].allocated_lbs, 100.0)
        self.assertEqual(view.orders[0].late_lbs, 0.0)
        self.assertEqual(view.orders[0].late_fill_date, first_due)
        self.assertEqual(view.orders[1].allocated_lbs, 150.0)
        self.assertEqual(view.orders[1].late_lbs, 0.0)
        self.assertEqual(view.orders[1].late_fill_date, first_due)
        # Orders 2 and 3 untouched.
        for o in view.orders[2:]:
            self.assertEqual(o.allocated_lbs, 0.0)
            self.assertEqual(o.late_lbs, 0.0)
            self.assertIsNone(o.late_fill_date)

    def test_late_reporting_on_hand_plus_jobs_all_on_time(self):
        # Section 3.1: every order fully filled; every chunk strictly before
        # its target order's due_date. on_hand fully fills order 0 (last
        # contributor is on_hand → late_fill_date == first_due). Jobs fill
        # orders 1–3, each ending 1 day before the target due_date (last
        # contributor is the job → late_fill_date == job.end).
        view = _make_view([100, 200, 150, 300])
        job1 = _job_at(_due(1) - timedelta(days=1), lbs=200)
        job2 = _job_at(_due(2) - timedelta(days=1), lbs=150)
        job3 = _job_at(_due(3) - timedelta(days=1), lbs=300)
        view.recompute(jobs=[job1, job2, job3], on_hand=100)
        expected_alloc = [100.0, 200.0, 150.0, 300.0]
        expected_fill_date = [_due(0), job1.end, job2.end, job3.end]
        for o, alloc, fill in zip(view.orders, expected_alloc, expected_fill_date):
            self.assertEqual(o.allocated_lbs, alloc)
            self.assertEqual(o.late_lbs, 0.0)
            self.assertEqual(o.late_fill_date, fill)
        self.assertEqual(view.lateness, 0.0)

    def test_late_reporting_chunk_at_due_date_is_on_time(self):
        # Section 3.2: boundary case — a job ending exactly at the order's
        # due_date is on-time (avail_time > due_date is the late check, so
        # equality is not late). Demand [100, 0, 0, 0]; one job at _due(0)
        # with 100 lbs. Order 0: late_lbs == 0, late_fill_date == _due(0).
        view = _make_view([100, 0, 0, 0])
        jobs = [_job_at(_due(0), lbs=100)]
        view.recompute(jobs=jobs, on_hand=0)
        self.assertEqual(view.orders[0].allocated_lbs, 100.0)
        self.assertEqual(view.orders[0].late_lbs, 0.0)
        self.assertEqual(view.orders[0].late_fill_date, _due(0))
        self.assertEqual(view.lateness, 0.0)

    def test_late_reporting_supply_short_last_order_partial(self):
        # Section 4.1: total supply (650) < total demand (750), but every
        # contributing chunk is on-time. job3 is undersized → order 3
        # partially filled. late_lbs == 0 everywhere; partial order's
        # late_fill_date is still the last contributing chunk's time.
        view = _make_view([100, 200, 150, 300])
        job1 = _job_at(_due(1) - timedelta(days=1), lbs=200)
        job2 = _job_at(_due(2) - timedelta(days=1), lbs=150)
        job3 = _job_at(_due(3) - timedelta(days=1), lbs=200)  # 100 short of order 3
        view.recompute(jobs=[job1, job2, job3], on_hand=100)
        expected_alloc = [100.0, 200.0, 150.0, 200.0]
        expected_fill_date = [_due(0), job1.end, job2.end, job3.end]
        for o, alloc, fill in zip(view.orders, expected_alloc, expected_fill_date):
            self.assertEqual(o.allocated_lbs, alloc)
            self.assertEqual(o.late_lbs, 0.0)
            self.assertEqual(o.late_fill_date, fill)
        self.assertEqual(view.lateness, 0.0)

    def test_late_reporting_supply_short_last_order_untouched(self):
        # Section 4.2: supply (450) runs out before reaching order 3.
        # Orders 0–2 fully filled on-time; order 3 sees no chunk at all
        # (allocated_lbs == 0, late_lbs == 0, late_fill_date is None).
        view = _make_view([100, 200, 150, 300])
        job1 = _job_at(_due(1) - timedelta(days=1), lbs=200)
        job2 = _job_at(_due(2) - timedelta(days=1), lbs=150)
        view.recompute(jobs=[job1, job2], on_hand=100)
        # Orders 0–2 fully filled.
        self.assertEqual(view.orders[0].allocated_lbs, 100.0)
        self.assertEqual(view.orders[0].late_lbs, 0.0)
        self.assertEqual(view.orders[0].late_fill_date, _due(0))
        self.assertEqual(view.orders[1].allocated_lbs, 200.0)
        self.assertEqual(view.orders[1].late_lbs, 0.0)
        self.assertEqual(view.orders[1].late_fill_date, job1.end)
        self.assertEqual(view.orders[2].allocated_lbs, 150.0)
        self.assertEqual(view.orders[2].late_lbs, 0.0)
        self.assertEqual(view.orders[2].late_fill_date, job2.end)
        # Order 3 untouched.
        self.assertEqual(view.orders[3].allocated_lbs, 0.0)
        self.assertEqual(view.orders[3].late_lbs, 0.0)
        self.assertIsNone(view.orders[3].late_fill_date)
        self.assertEqual(view.lateness, 0.0)

    def test_late_reporting_all_orders_late_no_on_hand(self):
        # Section 5.1: every order filled by a single late job. Each job
        # ends 1 day past its target order's due_date with exactly that
        # order's demand, so each order is fully late.
        # Lateness = sum(qty * 2^1) = 2 * 750 = 1500.
        view = _make_view([100, 200, 150, 300])
        job0 = _job_at(_due(0) + timedelta(days=1), lbs=100)
        job1 = _job_at(_due(1) + timedelta(days=1), lbs=200)
        job2 = _job_at(_due(2) + timedelta(days=1), lbs=150)
        job3 = _job_at(_due(3) + timedelta(days=1), lbs=300)
        view.recompute(jobs=[job0, job1, job2, job3], on_hand=0)
        expected_alloc = [100.0, 200.0, 150.0, 300.0]
        expected_fill = [job0.end, job1.end, job2.end, job3.end]
        for o, alloc, fill in zip(view.orders, expected_alloc, expected_fill):
            self.assertEqual(o.allocated_lbs, alloc)
            self.assertEqual(o.late_lbs, alloc)  # fully late
            self.assertEqual(o.late_fill_date, fill)
        self.assertAlmostEqual(view.lateness, 2.0 * sum(expected_alloc))

    def test_late_reporting_all_orders_late_on_hand_partial_week_0(self):
        # Section 5.2: on_hand = 50 fills half of order 0 on-time
        # (stamped at first_due == _due(0)). A small late job tops up
        # order 0; further late jobs fill orders 1–3.
        # Order 0: late_lbs = qty - on_hand = 50; late_fill_date is the
        # late job's end (latest chunk). Orders 1–3: fully late.
        # Lateness = 50*2 + 200*2 + 150*2 + 300*2 = 1400.
        view = _make_view([100, 200, 150, 300])
        job0a = _job_at(_due(0) + timedelta(days=1), lbs=50)
        job1 = _job_at(_due(1) + timedelta(days=1), lbs=200)
        job2 = _job_at(_due(2) + timedelta(days=1), lbs=150)
        job3 = _job_at(_due(3) + timedelta(days=1), lbs=300)
        view.recompute(jobs=[job0a, job1, job2, job3], on_hand=50)
        self.assertEqual(view.orders[0].allocated_lbs, 100.0)
        self.assertEqual(view.orders[0].late_lbs, 50.0)
        self.assertEqual(view.orders[0].late_fill_date, job0a.end)
        self.assertEqual(view.orders[1].allocated_lbs, 200.0)
        self.assertEqual(view.orders[1].late_lbs, 200.0)
        self.assertEqual(view.orders[1].late_fill_date, job1.end)
        self.assertEqual(view.orders[2].allocated_lbs, 150.0)
        self.assertEqual(view.orders[2].late_lbs, 150.0)
        self.assertEqual(view.orders[2].late_fill_date, job2.end)
        self.assertEqual(view.orders[3].allocated_lbs, 300.0)
        self.assertEqual(view.orders[3].late_lbs, 300.0)
        self.assertEqual(view.orders[3].late_fill_date, job3.end)
        self.assertAlmostEqual(view.lateness, 1400.0)

    def test_late_reporting_week_0_full_week_1_partial_on_hand(self):
        # Section 5.3: on_hand = 200 fully covers order 0 (100) and half
        # of order 1 (100 on-time at first_due). Late jobs fill the rest:
        # job1 tops up order 1; job2 fills order 2; job3 fills order 3.
        # Order 0: fully on-time → late_lbs = 0, late_fill_date = _due(0).
        # Order 1: late_lbs = qty - (on_hand - week_0.qty) = 100;
        # late_fill_date = job1.end (the latest contributing chunk).
        # Orders 2–3: fully late.
        # Lateness = 100*2 + 150*2 + 300*2 = 1100.
        view = _make_view([100, 200, 150, 300])
        job1 = _job_at(_due(1) + timedelta(days=1), lbs=100)
        job2 = _job_at(_due(2) + timedelta(days=1), lbs=150)
        job3 = _job_at(_due(3) + timedelta(days=1), lbs=300)
        view.recompute(jobs=[job1, job2, job3], on_hand=200)
        self.assertEqual(view.orders[0].allocated_lbs, 100.0)
        self.assertEqual(view.orders[0].late_lbs, 0.0)
        self.assertEqual(view.orders[0].late_fill_date, _due(0))
        self.assertEqual(view.orders[1].allocated_lbs, 200.0)
        self.assertEqual(view.orders[1].late_lbs, 100.0)
        self.assertEqual(view.orders[1].late_fill_date, job1.end)
        self.assertEqual(view.orders[2].allocated_lbs, 150.0)
        self.assertEqual(view.orders[2].late_lbs, 150.0)
        self.assertEqual(view.orders[2].late_fill_date, job2.end)
        self.assertEqual(view.orders[3].allocated_lbs, 300.0)
        self.assertEqual(view.orders[3].late_lbs, 300.0)
        self.assertEqual(view.orders[3].late_fill_date, job3.end)
        self.assertAlmostEqual(view.lateness, 1100.0)

    def test_late_reporting_mixed_late_early_on_time_later_no_on_hand(self):
        # Section 5.4: no on-hand. One late job at _due(1)+1d with 300 lbs
        # covers orders 0+1 (both late). One on-time job at _due(2)-1d
        # with 450 lbs covers orders 2+3 on-time.
        # Order 0: 100 lbs late by 8 days. Order 1: 200 lbs late by 1 day.
        # Orders 2–3: fully on-time (avail = _due(2)-1d < each due_date).
        # Lateness = 100*2^8 + 200*2^1 = 25600 + 400 = 26000.
        view = _make_view([100, 200, 150, 300])
        late_job = _job_at(_due(1) + timedelta(days=1), lbs=300)
        on_time_job = _job_at(_due(2) - timedelta(days=1), lbs=450)
        view.recompute(jobs=[late_job, on_time_job], on_hand=0)
        self.assertEqual(view.orders[0].allocated_lbs, 100.0)
        self.assertEqual(view.orders[0].late_lbs, 100.0)
        self.assertEqual(view.orders[0].late_fill_date, late_job.end)
        self.assertEqual(view.orders[1].allocated_lbs, 200.0)
        self.assertEqual(view.orders[1].late_lbs, 200.0)
        self.assertEqual(view.orders[1].late_fill_date, late_job.end)
        self.assertEqual(view.orders[2].allocated_lbs, 150.0)
        self.assertEqual(view.orders[2].late_lbs, 0.0)
        self.assertEqual(view.orders[2].late_fill_date, on_time_job.end)
        self.assertEqual(view.orders[3].allocated_lbs, 300.0)
        self.assertEqual(view.orders[3].late_lbs, 0.0)
        self.assertEqual(view.orders[3].late_fill_date, on_time_job.end)
        self.assertAlmostEqual(view.lateness, 26000.0)

    def test_late_reporting_mixed_late_early_on_time_later_with_on_hand(self):
        # Section 5.5: same as 5.4 but on_hand = 50 covers half of order 0
        # on-time. late_job sized down to 250 lbs (50 to finish order 0 +
        # 200 to fill order 1).
        # Order 0: mixed — 50 on-time from on_hand + 50 late from late_job.
        # late_lbs = 50; late_fill_date = late_job.end.
        # Orders 1–3 unchanged from 5.4.
        # Lateness = 50*2^8 + 200*2^1 = 12800 + 400 = 13200.
        view = _make_view([100, 200, 150, 300])
        late_job = _job_at(_due(1) + timedelta(days=1), lbs=250)
        on_time_job = _job_at(_due(2) - timedelta(days=1), lbs=450)
        view.recompute(jobs=[late_job, on_time_job], on_hand=50)
        self.assertEqual(view.orders[0].allocated_lbs, 100.0)
        self.assertEqual(view.orders[0].late_lbs, 50.0)
        self.assertEqual(view.orders[0].late_fill_date, late_job.end)
        self.assertEqual(view.orders[1].allocated_lbs, 200.0)
        self.assertEqual(view.orders[1].late_lbs, 200.0)
        self.assertEqual(view.orders[1].late_fill_date, late_job.end)
        self.assertEqual(view.orders[2].allocated_lbs, 150.0)
        self.assertEqual(view.orders[2].late_lbs, 0.0)
        self.assertEqual(view.orders[2].late_fill_date, on_time_job.end)
        self.assertEqual(view.orders[3].allocated_lbs, 300.0)
        self.assertEqual(view.orders[3].late_lbs, 0.0)
        self.assertEqual(view.orders[3].late_fill_date, on_time_job.end)
        self.assertAlmostEqual(view.lateness, 13200.0)

    def test_late_reporting_mixed_late_on_time_partial_last_week(self):
        # Section 5.6: same as 5.4 but on_time_job sized 350 lbs (100
        # short of orders 2+3 combined) → order 3 partially filled.
        # Order 2: fully on-time. Order 3: allocated = 200,
        # late_lbs = 0, late_fill_date = on_time_job.end.
        # Lateness identical to 5.4 (only orders 0–1 are late).
        view = _make_view([100, 200, 150, 300])
        late_job = _job_at(_due(1) + timedelta(days=1), lbs=300)
        on_time_job = _job_at(_due(2) - timedelta(days=1), lbs=350)
        view.recompute(jobs=[late_job, on_time_job], on_hand=0)
        self.assertEqual(view.orders[0].allocated_lbs, 100.0)
        self.assertEqual(view.orders[0].late_lbs, 100.0)
        self.assertEqual(view.orders[0].late_fill_date, late_job.end)
        self.assertEqual(view.orders[1].allocated_lbs, 200.0)
        self.assertEqual(view.orders[1].late_lbs, 200.0)
        self.assertEqual(view.orders[1].late_fill_date, late_job.end)
        self.assertEqual(view.orders[2].allocated_lbs, 150.0)
        self.assertEqual(view.orders[2].late_lbs, 0.0)
        self.assertEqual(view.orders[2].late_fill_date, on_time_job.end)
        self.assertEqual(view.orders[3].allocated_lbs, 200.0)
        self.assertEqual(view.orders[3].late_lbs, 0.0)
        self.assertEqual(view.orders[3].late_fill_date, on_time_job.end)
        self.assertAlmostEqual(view.lateness, 26000.0)

    def test_late_reporting_mixed_late_on_time_partial_last_week_with_on_hand(self):
        # Section 5.7: same as 5.5 but on_time_job sized 350 lbs → order 3
        # partially filled. Combines every per-order state in one run:
        # mixed (order 0), fully late (order 1), fully on-time (order 2),
        # partially on-time (order 3).
        # Lateness identical to 5.5.
        view = _make_view([100, 200, 150, 300])
        late_job = _job_at(_due(1) + timedelta(days=1), lbs=250)
        on_time_job = _job_at(_due(2) - timedelta(days=1), lbs=350)
        view.recompute(jobs=[late_job, on_time_job], on_hand=50)
        self.assertEqual(view.orders[0].allocated_lbs, 100.0)
        self.assertEqual(view.orders[0].late_lbs, 50.0)
        self.assertEqual(view.orders[0].late_fill_date, late_job.end)
        self.assertEqual(view.orders[1].allocated_lbs, 200.0)
        self.assertEqual(view.orders[1].late_lbs, 200.0)
        self.assertEqual(view.orders[1].late_fill_date, late_job.end)
        self.assertEqual(view.orders[2].allocated_lbs, 150.0)
        self.assertEqual(view.orders[2].late_lbs, 0.0)
        self.assertEqual(view.orders[2].late_fill_date, on_time_job.end)
        self.assertEqual(view.orders[3].allocated_lbs, 200.0)
        self.assertEqual(view.orders[3].late_lbs, 0.0)
        self.assertEqual(view.orders[3].late_fill_date, on_time_job.end)
        self.assertAlmostEqual(view.lateness, 13200.0)


class SafetyAwareViewRecomputeTests(unittest.TestCase):
    # All tests below default to greige AU2958G, so safety_target == 1400.

    def test_no_jobs_no_on_hand_leaves_everything_zero(self):
        view = _make_safety_view([100, 200, 150, 300])
        view.recompute(jobs=[], on_hand=0)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [0.0, 0.0, 0.0, 0.0],
        )
        self.assertEqual(view.safety_pool, 0.0)

    def test_on_hand_partially_fills_week_0(self):
        # 50 lbs < week 0's demand of 100. Order 0 gets 50, others untouched,
        # safety pool stays at 0 (nothing left over).
        view = _make_safety_view([100, 200, 150, 300])
        view.recompute(jobs=[], on_hand=50)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [50.0, 0.0, 0.0, 0.0],
        )
        self.assertEqual(view.safety_pool, 0.0)

    def test_on_hand_fills_week_0_then_partial_safety(self):
        # 600 lbs: 100 → week 0, 500 → safety (target 1400, not full).
        view = _make_safety_view([100, 200, 150, 300])
        view.recompute(jobs=[], on_hand=600)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 0.0, 0.0, 0.0],
        )
        self.assertEqual(view.safety_pool, 500.0)

    def test_on_hand_fills_week_0_full_safety_then_partial_week_1(self):
        # 1600 lbs: 100 → week 0, 1400 → safety (full), 100 → week 1 (partial).
        view = _make_safety_view([100, 200, 150, 300])
        view.recompute(jobs=[], on_hand=1600)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 100.0, 0.0, 0.0],
        )
        self.assertEqual(view.safety_pool, 1400.0)

    def test_on_hand_fills_all_demand_and_safety(self):
        # 2150 lbs = 100 + 1400 + 200 + 150 + 300, exactly enough to cover
        # every order plus a full safety pool.
        view = _make_safety_view([100, 200, 150, 300])
        view.recompute(jobs=[], on_hand=2150)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 200.0, 150.0, 300.0],
        )
        self.assertEqual(view.safety_pool, 1400.0)

    def test_jobs_fill_weeks_0_and_1_before_safety(self):
        # Job ends between week 0's and week 1's due dates → nearest on-time
        # order is week 1. Bucket 1 spans weeks 0..1, then safety, then later.
        # 800 lbs: 100 → week 0 (late), 200 → week 1 (on time), 500 → safety.
        view = _make_safety_view([100, 200, 150, 300])
        jobs = [_job_at(_due(0) + timedelta(days=4), lbs=800)]
        view.recompute(jobs=jobs, on_hand=0)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 200.0, 0.0, 0.0],
        )
        self.assertEqual(view.safety_pool, 500.0)

    def test_job_late_to_all_orders_fills_every_order_before_safety(self):
        # Job ends a week after week 3's due_date → late to all orders.
        # Bucket 1 spans all four orders earliest-first, then safety.
        # 1250 lbs: 100+200+150+300 = 750 → orders, remaining 500 → safety.
        view = _make_safety_view([100, 200, 150, 300])
        jobs = [_job_at(_due(3) + timedelta(days=7), lbs=1250)]
        view.recompute(jobs=jobs, on_hand=0)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 200.0, 150.0, 300.0],
        )
        self.assertEqual(view.safety_pool, 500.0)

    # --- Carrying / excess tests ---
    # All four below have on_hand >= week 0 demand + safety_target and avoid
    # any drains (so drainage == 0). They exercise the carrying and excess
    # trackers in isolation, with lead_time = 7 days.

    def test_on_hand_above_demand_plus_safety_yields_excess_and_carrying(self):
        # on_hand = 2650 = 100 (week 0) + 1400 (safety) + 200 + 150 + 300 + 500 (excess).
        # Bucket 3 from on_hand:
        #   order 1: 200 lbs, hold 7d, beyond_lead 0 → 0
        #   order 2: 150 lbs, hold 14d, beyond_lead 7d → 1050
        #   order 3: 300 lbs, hold 21d, beyond_lead 14d → 4200
        # Carrying = 5250, excess = 500, drainage = 0.
        view = _make_safety_view([100, 200, 150, 300])
        view.recompute(jobs=[], on_hand=2650)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 200.0, 150.0, 300.0],
        )
        self.assertEqual(view.safety_pool, 1400.0)
        self.assertAlmostEqual(view.carrying, 5250.0)
        self.assertEqual(view.excess, 500.0)
        self.assertEqual(view.drainage, 0.0)

    def test_on_hand_exactly_covers_demand_plus_safety_has_carrying_no_excess(self):
        # on_hand = 2150 (no excess). Same bucket 3 fills as above:
        # carrying = 5250, excess = 0, drainage = 0.
        view = _make_safety_view([100, 200, 150, 300])
        view.recompute(jobs=[], on_hand=2150)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 200.0, 150.0, 300.0],
        )
        self.assertEqual(view.safety_pool, 1400.0)
        self.assertAlmostEqual(view.carrying, 5250.0)
        self.assertEqual(view.excess, 0.0)
        self.assertEqual(view.drainage, 0.0)

    def test_job_creates_carrying_but_no_excess(self):
        # on_hand = 1500 covers exactly week 0 (100) + safety (1400).
        # Job ends at week 0's due + 1 day with 650 lbs. on_time_idx = 1, so
        # bucket 1 fills orders 0 (already full) and 1 (200 lbs, no carry);
        # bucket 3 fills orders 2 and 3:
        #   order 2: 150 lbs, hold 13d, beyond_lead 6d → 900
        #   order 3: 300 lbs, hold 20d, beyond_lead 13d → 3900
        # Carrying = 4800, excess = 0, drainage = 0.
        view = _make_safety_view([100, 200, 150, 300])
        jobs = [_job_at(_due(0) + timedelta(days=1), lbs=650)]
        view.recompute(jobs=jobs, on_hand=1500)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 200.0, 150.0, 300.0],
        )
        self.assertEqual(view.safety_pool, 1400.0)
        self.assertAlmostEqual(view.carrying, 4800.0)
        self.assertEqual(view.excess, 0.0)
        self.assertEqual(view.drainage, 0.0)

    def test_job_creates_both_carrying_and_excess(self):
        # Same setup as previous but the job has 1000 lbs (350 more than
        # needed). Allocations and carrying match; the 350 extra falls into
        # bucket 4. drainage stays 0.
        view = _make_safety_view([100, 200, 150, 300])
        jobs = [_job_at(_due(0) + timedelta(days=1), lbs=1000)]
        view.recompute(jobs=jobs, on_hand=1500)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 200.0, 150.0, 300.0],
        )
        self.assertEqual(view.safety_pool, 1400.0)
        self.assertAlmostEqual(view.carrying, 4800.0)
        self.assertEqual(view.excess, 350.0)
        self.assertEqual(view.drainage, 0.0)

    # --- All-zero test (spec section 2.2) ---

    def test_all_costs_zero_with_in_lead_time_job_fills(self):
        # on_hand = week 0 + safety = 1500 → physical pool reaches target
        # immediately. Subsequent jobs each fill their order via bucket 1
        # within lead_time (so no carrying), and gap == 0 at every drain
        # (so no drainage past target). Excess = 0 because each job is
        # sized exactly.
        view = _make_safety_view([100, 200, 150, 300])
        jobs = [
            _job_at(_due(0) + timedelta(days=4),  lbs=200),  # fills order 1
            _job_at(_due(0) + timedelta(days=11), lbs=150),  # fills order 2
            _job_at(_due(0) + timedelta(days=18), lbs=300),  # fills order 3
        ]
        view.recompute(jobs=jobs, on_hand=1500)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 200.0, 150.0, 300.0],
        )
        self.assertEqual(view.safety_pool, 1400.0)
        self.assertEqual(view.excess, 0.0)
        self.assertEqual(view.carrying, 0.0)
        self.assertEqual(view.drainage, 0.0)

    # --- Constant drainage tests (spec section 2.3.1) ---

    def test_constant_drainage_at_safety_target(self):
        # 2.3.1.1: on_hand = week 0 demand only (no safety fill); each
        # subsequent order is filled exactly on its due date by a perfectly
        # sized job (chunk fires before drain, so gap = 0 at every drain).
        # Pool stays at 0 throughout → integrand = safety_target = 1400.
        # Drainage = 1400 lbs * 21 days = 29400 lb-days.
        view = _make_safety_view([100, 200, 150, 300])
        jobs = [
            _job_at(_due(1), lbs=200),
            _job_at(_due(2), lbs=150),
            _job_at(_due(3), lbs=300),
        ]
        view.recompute(jobs=jobs, on_hand=100)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 200.0, 150.0, 300.0],
        )
        self.assertEqual(view.safety_pool, 0.0)
        self.assertEqual(view.excess, 0.0)
        self.assertEqual(view.carrying, 0.0)
        self.assertAlmostEqual(view.drainage, 1400.0 * 21)

    def test_constant_drainage_between_zero_and_safety_target(self):
        # 2.3.1.2: on_hand = week 0 + partial safety (500 lbs into safety
        # bucket). Jobs fill subsequent orders within lead_time, so no
        # drains happen. Pool sits at 500 from t=week_0.due onward.
        # Integrand = 1400 - 500 = 900 lbs over 21 days = 18900 lb-days.
        view = _make_safety_view([100, 200, 150, 300])
        jobs = [
            _job_at(_due(0) + timedelta(days=4),  lbs=200),
            _job_at(_due(0) + timedelta(days=11), lbs=150),
            _job_at(_due(0) + timedelta(days=18), lbs=300),
        ]
        view.recompute(jobs=jobs, on_hand=600)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 200.0, 150.0, 300.0],
        )
        self.assertEqual(view.safety_pool, 500.0)
        self.assertEqual(view.excess, 0.0)
        self.assertEqual(view.carrying, 0.0)
        self.assertAlmostEqual(view.drainage, 900.0 * 21)

    def test_constant_drainage_capped_at_safety_target(self):
        # 2.3.1.3: no on_hand and no jobs. Pool starts at 0 and goes
        # progressively negative as each order drains by its full demand,
        # but the drainage integrand is capped at safety_target (deeper
        # deficit is "real" shipment lateness handled by the raw view).
        # → same total drainage as 2.3.1.1 (29400 lb-days), even though
        # the physical pool ends at -750.
        view = _make_safety_view([100, 200, 150, 300])
        view.recompute(jobs=[], on_hand=0)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [0.0, 0.0, 0.0, 0.0],
        )
        self.assertEqual(view.safety_pool, 0.0)
        self.assertEqual(view.excess, 0.0)
        self.assertEqual(view.carrying, 0.0)
        self.assertAlmostEqual(view.drainage, 1400.0 * 21)

    # --- Non-constant drainage tests (spec section 2.3.2) ---

    def test_no_stacked_drainage_with_partial_initial_safety(self):
        # 2.3.2.1, sub-case (a): on_hand = 800 (100 to order 0, 700 to
        # safety). Pool sits at 700 from week_0.due → constant baseline
        # drainage for the first week. Order 1 drains (pool 500); the next
        # job both refunds the drained order and tops up safety to target,
        # so the pool returns to safety_target before any subsequent drain.
        # Drainage = 7d × 700 + 1d × 900 = 4900 + 900 = 5800.
        view = _make_safety_view([100, 200, 150, 300])
        jobs = [
            # 1050 lbs = 200 (order 1 refund) + 150 (order 2 fill) + 700 (safety).
            _job_at(_due(1) + timedelta(days=1), lbs=1050),
            # Fills order 3 in bucket 1 within lead_time → no carrying.
            _job_at(_due(2) + timedelta(days=5), lbs=300),
        ]
        view.recompute(jobs=jobs, on_hand=800)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 200.0, 150.0, 300.0],
        )
        self.assertEqual(view.safety_pool, 1400.0)
        self.assertEqual(view.excess, 0.0)
        self.assertEqual(view.carrying, 0.0)
        self.assertAlmostEqual(view.drainage, 5800.0)

    def test_no_stacked_drainage_with_full_initial_safety(self):
        # 2.3.2.1, sub-case (b): on_hand = 1500 → pool starts at target.
        # Each subsequent order drains with a sized-just-right refund job
        # following one day later, returning the pool to safety_target
        # before the next drain.
        # Drainage = 1d × 200 + 1d × 150 = 350.
        view = _make_safety_view([100, 200, 150, 300])
        jobs = [
            _job_at(_due(1) + timedelta(days=1), lbs=200),  # refunds order 1
            _job_at(_due(2) + timedelta(days=1), lbs=150),  # refunds order 2
            _job_at(_due(2) + timedelta(days=5), lbs=300),  # fills order 3 on time
        ]
        view.recompute(jobs=jobs, on_hand=1500)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 200.0, 150.0, 300.0],
        )
        self.assertEqual(view.safety_pool, 1400.0)
        self.assertEqual(view.excess, 0.0)
        self.assertEqual(view.carrying, 0.0)
        self.assertAlmostEqual(view.drainage, 350.0)

    def test_stacked_drainage_between_jobs_even_split(self):
        # 2.3.2.2, first split: demand [100, 200, 150, 300], on_hand = 1500.
        # Orders 1 and 2 drain consecutively (week_1.due then week_2.due)
        # with no chunk between them, so deficit stacks: 200, then 350.
        # A single job at week_2.due+1d refunds both. Drainage =
        # 7d × 200 + 1d × 350 = 1400 + 350 = 1750.
        view = _make_safety_view([100, 200, 150, 300])
        jobs = [
            # 350 lbs = 200 (order 1 refund) + 150 (order 2 refund).
            _job_at(_due(2) + timedelta(days=1), lbs=350),
            _job_at(_due(2) + timedelta(days=5), lbs=300),  # fills order 3
        ]
        view.recompute(jobs=jobs, on_hand=1500)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 200.0, 150.0, 300.0],
        )
        self.assertEqual(view.safety_pool, 1400.0)
        self.assertEqual(view.excess, 0.0)
        self.assertEqual(view.carrying, 0.0)
        self.assertAlmostEqual(view.drainage, 1750.0)

    def test_stacked_drainage_between_jobs_uneven_split(self):
        # 2.3.2.2, second split: same structure as above but the demand
        # split is shifted so gap_1=50, gap_2=300. Total stacked deficit
        # (350) is the same as the even-split case, but the time spent
        # at the smaller intermediate deficit is shorter.
        # Drainage = 7d × 50 + 1d × 350 = 350 + 350 = 700.
        view = _make_safety_view([100, 50, 300, 200])
        jobs = [
            _job_at(_due(2) + timedelta(days=1), lbs=350),  # refunds order 1 + 2
            _job_at(_due(2) + timedelta(days=5), lbs=200),  # fills order 3
        ]
        view.recompute(jobs=jobs, on_hand=1500)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 50.0, 300.0, 200.0],
        )
        self.assertEqual(view.safety_pool, 1400.0)
        self.assertEqual(view.excess, 0.0)
        self.assertEqual(view.carrying, 0.0)
        self.assertAlmostEqual(view.drainage, 700.0)

    def test_stacked_drainage_interleaved_with_jobs(self):
        # 2.3.2.3: event sequence drain → chunk (partial refund) → drain.
        # Order 1 drains (pool 1400 → 1200); Job 1 (100 lbs) refunds half
        # → pool 1300; order 2 then drains on top of the remaining deficit
        # → pool 1150 (stacked = 250). Job 2 then fully restores pool to
        # target. Drainage = 1d × 200 + 6d × 100 + 1d × 250 = 200 + 600
        # + 250 = 1050.
        view = _make_safety_view([100, 200, 150, 300])
        jobs = [
            _job_at(_due(1) + timedelta(days=1), lbs=100),  # partial refund of order 1
            _job_at(_due(2) + timedelta(days=1), lbs=250),  # full refund of orders 1+2
            _job_at(_due(2) + timedelta(days=5), lbs=300),  # fills order 3
        ]
        view.recompute(jobs=jobs, on_hand=1500)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 200.0, 150.0, 300.0],
        )
        self.assertEqual(view.safety_pool, 1400.0)
        self.assertEqual(view.excess, 0.0)
        self.assertEqual(view.carrying, 0.0)
        self.assertAlmostEqual(view.drainage, 1050.0)

    # --- Combined cost tracker tests (spec section 2.4) ---

    def test_no_stacked_drainage_with_carrying_and_no_excess(self):
        # 2.4.1: on_hand = 600 (covers order 0 + 500 toward safety, leaving
        # safety 900 short). First job at week_0.due+1d, 1200 lbs:
        #   bucket 1 (order 1):    200
        #   bucket 2 (safety):     900  → pool now 1400
        #   bucket 3 (order 2):    100  → partial fill (50 short of demand)
        # The bucket 3 lbs are held 13 days vs lead_time 7, so carrying
        # accrues = 100 lbs × 6 days = 600.
        #
        # Order 2 drains at week_2.due by its 50-lb gap → pool 1350.
        # Second job at week_2.due+1d, 350 lbs:
        #   bucket 1 (order 2):     50  → refund pool back to 1400
        #   bucket 1 (order 3):    300  → fills order 3 before its due date
        # No bucket-3 fill on the second job, so no further carrying.
        #
        # Drainage integral picks up two segments:
        #   week_0.due → week_0.due+1d  (1d × deficit 900) = 900
        #   week_2.due → week_2.due+1d  (1d × deficit 50)  =  50
        # All other intervals are at pool=1400 (deficit 0). Total = 950.
        #
        # No lbs spill into bucket 4, so excess = 0. Only one drain event
        # actually occurs (order 2), so drainage is "non-stacked."
        view = _make_safety_view([100, 200, 150, 300])
        jobs = [
            _job_at(_due(0) + timedelta(days=1), lbs=1200),
            _job_at(_due(2) + timedelta(days=1), lbs=350),
        ]
        view.recompute(jobs=jobs, on_hand=600)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 200.0, 150.0, 300.0],
        )
        self.assertEqual(view.safety_pool, 1400.0)
        self.assertAlmostEqual(view.carrying, 600.0)
        self.assertEqual(view.excess, 0.0)
        self.assertAlmostEqual(view.drainage, 950.0)

    def test_no_stacked_drainage_with_carrying_and_excess(self):
        # 2.4.2: Identical setup to 2.4.1 except the second job is sized
        # 100 lbs over what's needed. Allocations, carrying, and drainage
        # match 2.4.1 exactly; the 100-lb surplus falls through buckets
        # 1–3 untouched (safety is full, no later orders to fill) and
        # lands in bucket 4 → excess = 100.
        view = _make_safety_view([100, 200, 150, 300])
        jobs = [
            _job_at(_due(0) + timedelta(days=1), lbs=1200),
            _job_at(_due(2) + timedelta(days=1), lbs=450),  # was 350 in 2.4.1
        ]
        view.recompute(jobs=jobs, on_hand=600)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 200.0, 150.0, 300.0],
        )
        self.assertEqual(view.safety_pool, 1400.0)
        self.assertAlmostEqual(view.carrying, 600.0)
        self.assertEqual(view.excess, 100.0)
        self.assertAlmostEqual(view.drainage, 950.0)

    def test_stacked_drainage_with_carrying_and_no_excess(self):
        # 2.4.3: on_hand = 100 (exactly week 0 demand). First job at
        # week_0.due, 200 lbs. Together these put 100 into safety_pool
        # (from on_hand) and another 100 (from first_job's bucket 2),
        # leaving safety at 200 — well below target. Order 0 drains with
        # gap 0 (it was fully filled by on_hand), so pool stays at 200.
        #
        # week_0.due → week_1.due (7d at deficit 1200): drainage += 8400.
        # Order 1 drains at week_1.due (gap 200) → pool 0 (the order-1
        # deficit stacks onto the existing safety shortfall, and the
        # combined deficit clamps at safety_target = 1400).
        # week_1.due → week_1.due+1d (1d at deficit 1400): drainage += 1400.
        #
        # Second job at week_1.due+1d, 1850 lbs:
        #   bucket 1 (order 1):    200  → refund pool +200 = 200
        #   bucket 1 (order 2):    150
        #   bucket 2 (safety):    1200  → pool +1200 = 1400
        #   bucket 3 (order 3):    300  → held 13d (6d past lead_time)
        #     → carrying += 300 × 6 = 1800.
        #
        # Drainage = 8400 + 1400 = 9800. Carrying = 1800. Excess = 0.
        view = _make_safety_view([100, 200, 150, 300])
        jobs = [
            _job_at(_due(0), lbs=200),                       # ends in week 0
            _job_at(_due(1) + timedelta(days=1), lbs=1850),  # late to week 1
        ]
        view.recompute(jobs=jobs, on_hand=100)
        self.assertEqual(
            [o.allocated_lbs for o in view.orders],
            [100.0, 200.0, 150.0, 300.0],
        )
        self.assertEqual(view.safety_pool, 1400.0)
        self.assertAlmostEqual(view.carrying, 1800.0)
        self.assertEqual(view.excess, 0.0)
        self.assertAlmostEqual(view.drainage, 9800.0)


if __name__ == '__main__':
    unittest.main()
