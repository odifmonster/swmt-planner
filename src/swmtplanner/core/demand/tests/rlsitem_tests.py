#!/usr/bin/env python

import math
import unittest
from datetime import datetime, timedelta

from swmtplanner.core.product import Fabric
from swmtplanner.core.demand import RlsItem, Chunk
from swmtplanner.core.schedule import Job, Priority


LEAD = timedelta(days=3)

# netting fixture: 3 orders; today/lead put only the first in the near-term
# horizon (first_due <= today + lead < second_due)
N_DUES = [datetime.fromisocalendar(2026, 2 + i, 2) for i in range(3)]
N_TODAY = N_DUES[0] - timedelta(days=1)
N_REQS = [(10.0, N_DUES[i]) for i in range(3)]

# end-to-end fixture: six orders, matching Section 2
E_DUES = [datetime.fromisocalendar(2026, 2 + i, 2) for i in range(6)]
E_TODAY = datetime(2026, 1, 1)
E_REQS = [(10.0, E_DUES[i]) for i in range(6)]


def _ed(i: int, off: int) -> datetime:
    return E_DUES[i] + timedelta(days=off)


def _fabric(id: str = 'F1') -> Fabric:
    return Fabric(id=id, ply1_parts=(), greige='G', style='S', width=60.0,
                  oz_sq_yd=10.0, yld_pct=0.9, name='N', number=1,
                  shade_rating=0, jets={})


class FabRlsItem(RlsItem[Fabric]):
    """Concrete RlsItem over a Fabric. register_job converts a job into
    50-unit chunks at 10 units/hour — one chunk per 5 hours of runtime,
    available at its completion time — registered with the job as their
    source (3.3). 3.1/3.2 leave it unused."""

    def register_job(self, job: Job) -> None:
        hours = (job.end - job.start).total_seconds() / 3600
        self.register_chunks(
            [Chunk(self.item, job.start + timedelta(hours=5 * (k + 1)), 50.0)
             for k in range(int(hours * 10 / 50))],
            job)


class TestRlsItemNetting(unittest.TestCase):
    """3.1 — the initial netting of on-hand into each view's covered_on_hand."""

    def setUp(self):
        self.f = _fabric()

    def _build(self, on_hand: float, safety_tgt: float) -> FabRlsItem:
        return FabRlsItem(self.f, LEAD, on_hand, safety_tgt, (2026, 2),
                          N_TODAY, N_REQS)

    def test_no_safety_target(self):
        """3.1.1 — safety_tgt == 0: raw and safety net identically (Safety gets
        0). On-hand: part of the first order, exactly the first, spanning
        several."""
        for on_hand, raw_covered in [(4.0, [4, 0, 0]), (10.0, [10, 0, 0]),
                                     (25.0, [10, 10, 5])]:
            rls = self._build(on_hand, 0.0)
            raw = rls.raw_view.orders
            saf = rls.safety_view.orders
            for i in range(3):
                self.assertEqual(raw[i].due_date, saf[i].due_date)
                self.assertAlmostEqual(raw[i].covered_on_hand, raw_covered[i],
                                       msg=(on_hand, i))
                self.assertAlmostEqual(saf[i].covered_on_hand, raw_covered[i],
                                       msg=(on_hand, i))
            self.assertAlmostEqual(rls.safety_view.safety.covered_on_hand, 0.0)

    def test_on_hand_le_first_order(self):
        """3.1.2 — safety_tgt > 0, on_hand <= first order: the first RawOrder and
        first SafetyOrder get the same covered_on_hand (== on_hand); Safety 0."""
        for on_hand in (4.0, 10.0):
            rls = self._build(on_hand, 15.0)
            raw0 = rls.raw_view.orders[0]
            saf0 = rls.safety_view.orders[0]
            self.assertAlmostEqual(raw0.covered_on_hand, on_hand)
            self.assertAlmostEqual(saf0.covered_on_hand, on_hand)
            self.assertAlmostEqual(rls.safety_view.safety.covered_on_hand, 0.0)

    def test_on_hand_ge_first_order(self):
        """3.1.3 — safety_tgt > 0, on_hand >= first order: both first orders fully
        covered, but the leftover goes to the 2nd RawOrder vs the Safety. Leftover
        <, ==, and > safety_tgt."""
        # (on_hand, raw_covered, safety_order_covered, safety_covered)
        cases = [
            (15.0, [10, 5, 0], [10, 0, 0], 5.0),     # leftover 5 < tgt 15
            (25.0, [10, 10, 5], [10, 0, 0], 15.0),   # leftover 15 == tgt
            (30.0, [10, 10, 10], [10, 5, 0], 15.0),  # leftover 20 > tgt (spills)
        ]
        for on_hand, raw_c, saf_c, saf_cov in cases:
            rls = self._build(on_hand, 15.0)
            raw = rls.raw_view.orders
            saf = rls.safety_view.orders
            self.assertAlmostEqual(raw[0].covered_on_hand, 10.0, msg=on_hand)
            self.assertAlmostEqual(saf[0].covered_on_hand, 10.0, msg=on_hand)
            for i in range(3):
                self.assertAlmostEqual(raw[i].covered_on_hand, raw_c[i],
                                       msg=(on_hand, 'raw', i))
                self.assertAlmostEqual(saf[i].covered_on_hand, saf_c[i],
                                       msg=(on_hand, 'saf', i))
            self.assertAlmostEqual(rls.safety_view.safety.covered_on_hand, saf_cov)


class TestRlsItemEndToEnd(unittest.TestCase):
    """3.2 — reproduce five Section-2 scenarios through RlsItem netting +
    register_chunks + recompute, and confirm the view values match."""

    def setUp(self):
        self.f = _fabric()

    def _build(self, on_hand: float, safety_tgt: float) -> FabRlsItem:
        return FabRlsItem(self.f, LEAD, on_hand, safety_tgt, (2026, 2),
                          E_TODAY, E_REQS)

    def _metrics(self, sv, carrying, drainage, excess):
        for name, got, want in (('carrying', sv.carrying, carrying),
                                ('drainage', sv.drainage, drainage),
                                ('excess', sv.excess, excess)):
            self.assertTrue(math.isclose(got, want, rel_tol=1e-9, abs_tol=1e-9),
                            (name, got, want))
        for o in sv.orders:
            self.assertAlmostEqual(o.remaining, 0.0)

    def test_raw_one_late_chunk(self):
        """3.2 — RawView 2.1.1.2 (one late chunk fills all) via RlsItem."""
        rls = self._build(0.0, 0.0)          # on_hand 0 -> every order net-uncovered
        avail = _ed(5, 1)
        rls.register_chunks([Chunk(self.f, avail, 60.0)])
        rls.recompute()
        rv = rls.raw_view
        for o in rv.orders:
            self.assertAlmostEqual(o.remaining, 0.0)
        exp = sum(10.0 * 2.0 ** ((avail - E_DUES[i]).days) for i in range(6))
        self.assertTrue(math.isclose(rv.lateness, exp, rel_tol=1e-9))

    def test_raw_late_first_then_forward(self):
        """3.2 — RawView 2.1.2.1 (late first, then forward on time) via RlsItem."""
        rls = self._build(0.0, 0.0)
        rls.register_chunks([Chunk(self.f, _ed(0, 2), 15.0),
                             Chunk(self.f, _ed(1, 3), 5.0),
                             Chunk(self.f, _ed(2, -1), 40.0)])
        rls.recompute()
        rv = rls.raw_view
        for o in rv.orders:
            self.assertAlmostEqual(o.remaining, 0.0)
        exp = 10.0 * 2.0 ** 2 + 5.0 * 2.0 ** 3   # P0 late 2d (10), P1 late 3d (5)
        self.assertTrue(math.isclose(rv.lateness, exp, rel_tol=1e-9))

    def test_safety_carrying(self):
        """3.2 — SafetyView 2.2.1.3 (carrying only) via RlsItem."""
        rls = self._build(30.0, 20.0)        # nets P0 order + Safety covered
        rls.register_chunks([Chunk(self.f, _ed(1, -2), 20.0),
                             Chunk(self.f, _ed(3, -2), 10.0),
                             Chunk(self.f, _ed(4, -2), 10.0),
                             Chunk(self.f, _ed(5, -2), 10.0)])
        rls.recompute()
        self._metrics(rls.safety_view, 60.0, 0.0, 0.0)

    def test_safety_drainage(self):
        """3.2 — SafetyView 2.2.1.8 (drainage only) via RlsItem."""
        rls = self._build(30.0, 20.0)
        rls.register_chunks([Chunk(self.f, _ed(2, -2), 10.0),
                             Chunk(self.f, _ed(3, -2), 10.0),
                             Chunk(self.f, _ed(4, -2), 10.0),
                             Chunk(self.f, _ed(5, -2), 10.0),
                             Chunk(self.f, _ed(5, 5), 10.0)])
        rls.recompute()
        self._metrics(rls.safety_view, 0.0, 200.0, 0.0)

    def test_safety_all_three(self):
        """3.2 — SafetyView 2.2.2.10 (carrying + drainage + excess) via RlsItem."""
        rls = self._build(30.0, 20.0)
        rls.register_chunks([Chunk(self.f, _ed(2, 4), 20.0),
                             Chunk(self.f, _ed(3, -3), 35.0)])
        rls.recompute()
        self._metrics(rls.safety_view, 210.0, 150.0, 5.0)


def _job(start: datetime, hours: float) -> Job:
    return Job(start, start + timedelta(hours=hours), Priority(None))


class TestRlsItemPriorityPush(unittest.TestCase):
    """3.3 — register_job and the priority push. Jobs are built with
    Priority(None); after each recompute every job's priority.value is
    asserted. Uses the netting fixture's dues (weeks 2-4 -> offsets 0-2) with
    50-unit orders matched to the 50-unit job chunks."""

    def setUp(self):
        self.f = _fabric()

    def _build(self, reqs, on_hand=0.0, safety_tgt=0.0) -> FabRlsItem:
        return FabRlsItem(self.f, LEAD, on_hand, safety_tgt, (2026, 2),
                          N_TODAY, reqs)

    def test_conversion(self):
        """3.3.1 — a 10-hour job yields two 50-unit chunks at start+5h and
        start+10h, verified through the view allocations: both orders filled,
        zero lateness, and a carrying value that pins the second chunk's
        avail_date."""
        rls = self._build([(50.0, N_DUES[0]), (50.0, N_DUES[1])])
        start = N_DUES[0] - timedelta(days=1)
        job = _job(start, 10)
        rls.register_job(job)
        rls.recompute()
        sv = rls.safety_view
        for o in sv.orders:
            self.assertAlmostEqual(o.remaining, 0.0)
        avail2 = start + timedelta(hours=10)
        exp = 50.0 * ((N_DUES[1] - avail2 - LEAD).total_seconds() / 86400)
        self.assertTrue(math.isclose(sv.carrying, exp, rel_tol=1e-9))
        self.assertAlmostEqual(rls.raw_view.lateness, 0.0)
        self.assertEqual(job.priority.value, 0)

    def test_late_job(self):
        """3.3.2 — a job running past the earliest unfilled order's due date
        fills that order and takes its week_offset."""
        rls = self._build([(50.0, N_DUES[0]), (50.0, N_DUES[1])])
        job = _job(N_DUES[0] + timedelta(days=1), 5)
        rls.register_job(job)
        rls.recompute()
        self.assertEqual(job.priority.value, 0)
        self.assertAlmostEqual(rls.safety_view.orders[0].remaining, 0.0)

    def test_on_time_job(self):
        """3.3.3 — an on-time job fills its order before safety (which is
        short) and takes the order's week_offset."""
        rls = self._build([(50.0, N_DUES[0])], safety_tgt=50.0)
        job = _job(N_DUES[0] - timedelta(days=1), 5)
        rls.register_job(job)
        rls.recompute()
        self.assertEqual(job.priority.value, 0)
        sv = rls.safety_view
        self.assertAlmostEqual(sv.orders[0].remaining, 0.0)
        self.assertAlmostEqual(sv.safety.allocated_qty, 0.0)

    def test_early_job(self):
        """3.3.4 — an early job (completing more than lead_time before every
        open order's due) fills safety first and takes 'S'."""
        rls = self._build([(50.0, N_DUES[2])], safety_tgt=50.0)
        job = _job(N_TODAY, 5)
        rls.register_job(job)
        rls.recompute()
        self.assertEqual(job.priority.value, 'S')
        sv = rls.safety_view
        self.assertAlmostEqual(sv.safety.remaining, 0.0)
        self.assertAlmostEqual(sv.orders[0].remaining, 50.0)

    def test_pure_excess_job(self):
        """3.3.5 — with all orders and safety covered on hand, the job's
        priority stays None after recompute."""
        rls = self._build([(50.0, N_DUES[0])], on_hand=100.0, safety_tgt=50.0)
        job = _job(N_DUES[0] - timedelta(days=1), 5)
        rls.register_job(job)
        rls.recompute()
        self.assertIsNone(job.priority.value)
        self.assertAlmostEqual(rls.safety_view.excess, 50.0)

    def test_multiple_jobs_same_priority(self):
        """3.3.6 — two jobs whose chunks land in one large order both take
        that order's week_offset."""
        rls = self._build([(100.0, N_DUES[0])])
        j1 = _job(N_DUES[0] - timedelta(days=1), 5)
        j2 = _job(N_DUES[0] - timedelta(hours=19), 5)
        rls.register_job(j1)
        rls.register_job(j2)
        rls.recompute()
        self.assertEqual(j1.priority.value, 0)
        self.assertEqual(j2.priority.value, 0)

    def test_job_spanning_requirements(self):
        """3.3.7 — a job whose first chunk fills an order and whose second
        tops up safety takes the order's week_offset (first write wins), not
        'S'."""
        rls = self._build([(50.0, N_DUES[0])], safety_tgt=50.0)
        job = _job(N_DUES[0] - timedelta(days=1), 10)
        rls.register_job(job)
        rls.recompute()
        self.assertEqual(job.priority.value, 0)
        self.assertAlmostEqual(rls.safety_view.safety.remaining, 0.0)

    def test_insert_no_change(self):
        """3.3.8 — inserting a job covering a different (later) requirement
        leaves the existing job's priority unchanged."""
        rls = self._build([(50.0, N_DUES[0]), (50.0, N_DUES[1])])
        j1 = _job(N_DUES[0] - timedelta(days=1), 5)
        rls.register_job(j1)
        rls.recompute()
        self.assertEqual(j1.priority.value, 0)
        j2 = _job(N_DUES[1] - timedelta(days=1), 5)
        rls.register_job(j2)
        rls.recompute()
        self.assertEqual(j1.priority.value, 0)
        self.assertEqual(j2.priority.value, 1)

    def test_insert_moving_down(self):
        """3.3.9 — a new earlier job takes over the order; the existing job
        moves down to the later order's week_offset."""
        rls = self._build([(50.0, N_DUES[0]), (50.0, N_DUES[1])])
        j1 = _job(N_DUES[0] - timedelta(days=1), 5)
        rls.register_job(j1)
        rls.recompute()
        self.assertEqual(j1.priority.value, 0)
        j2 = _job(N_DUES[0] - timedelta(days=2), 5)
        rls.register_job(j2)
        rls.recompute()
        self.assertEqual(j2.priority.value, 0)
        self.assertEqual(j1.priority.value, 1)

    def test_insert_to_safety(self):
        """3.3.10 — the new earlier job takes the near-term order; the
        existing job's first fill becomes the safety top-up ('S')."""
        rls = self._build([(50.0, N_DUES[0])], safety_tgt=50.0)
        j1 = _job(N_DUES[0] - timedelta(days=1), 5)
        rls.register_job(j1)
        rls.recompute()
        self.assertEqual(j1.priority.value, 0)
        j2 = _job(N_DUES[0] - timedelta(days=2), 5)
        rls.register_job(j2)
        rls.recompute()
        self.assertEqual(j2.priority.value, 0)
        self.assertEqual(j1.priority.value, 'S')

    def test_insert_from_safety(self):
        """3.3.11 — the existing early job was 'S'; a new earlier job
        replenishes safety instead, and the existing job moves to the future
        order's week_offset."""
        rls = self._build([(50.0, N_DUES[2])], safety_tgt=50.0)
        j1 = _job(N_TODAY + timedelta(hours=6), 5)
        rls.register_job(j1)
        rls.recompute()
        self.assertEqual(j1.priority.value, 'S')
        j2 = _job(N_TODAY, 5)
        rls.register_job(j2)
        rls.recompute()
        self.assertEqual(j2.priority.value, 'S')
        self.assertEqual(j1.priority.value, 2)


if __name__ == '__main__':
    unittest.main()
