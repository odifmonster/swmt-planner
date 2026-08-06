#!/usr/bin/env python

import math
import unittest
from datetime import datetime, timedelta

from swmtplanner.core.product import Fabric
from swmtplanner.core.demand import RlsItem, Chunk


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
    """Concrete RlsItem over a Fabric; register_job is empty (no planner
    job -> Chunk conversion is under test yet)."""

    def register_job(self, job) -> None:
        pass


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


if __name__ == '__main__':
    unittest.main()
