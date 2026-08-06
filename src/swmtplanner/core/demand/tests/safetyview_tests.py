#!/usr/bin/env python

import math
import unittest
from datetime import datetime, timedelta

from swmtplanner.core.product import Fabric
from swmtplanner.core.demand import SafetyView, SafetyOrder, Chunk


FW = (2026, 2)
DUES = [datetime.fromisocalendar(2026, 2 + i, 2) for i in range(6)]
TODAY = datetime(2026, 1, 1)      # before every due date; RawView-style Tuesdays
LEAD = timedelta(days=3)          # shorter than the 1-week order spacing
TGT = 20.0                        # safety target
INIT = 10.0                       # each order's demand
COVERED = [10.0, 0.0, 0.0, 0.0, 0.0, 0.0]   # P0 covered by on-hand; P1-P5 net


def _fabric(id: str = 'F1') -> Fabric:
    return Fabric(id=id, ply1_parts=(), greige='G', style='S', width=60.0,
                  oz_sq_yd=10.0, yld_pct=0.9, name='N', number=1,
                  shade_rating=0, jets={})


def _dd(i: int, off: int) -> datetime:
    return DUES[i] + timedelta(days=off)


class _SafetyViewCase(unittest.TestCase):
    """These tests recompute over the *full* chunk list and verify the final
    carrying / drainage / excess (drainage is a whole-schedule integral, so it is
    checked only at the complete state). They also confirm every order is filled
    and the safety allocation, which together pin down that the right chunks
    reached the right orders / safety."""

    def setUp(self):
        self.f = _fabric()

    def _run(self, safety_on_hand, on_hand, specs):
        orders = [SafetyOrder(self.f, INIT, COVERED[i], FW, DUES[i])
                  for i in range(6)]
        sv = SafetyView(self.f, orders, TGT, safety_on_hand, LEAD, on_hand, TODAY)
        sv.recompute([Chunk(self.f, a, q) for a, q in specs])
        return sv, orders

    def _check(self, sv, orders, carrying, drainage, excess, safety_alloc):
        for name, got, want in (('carrying', sv.carrying, carrying),
                                ('drainage', sv.drainage, drainage),
                                ('excess', sv.excess, excess)):
            self.assertTrue(math.isclose(got, want, rel_tol=1e-9, abs_tol=1e-9),
                            (name, got, want))
        self.assertAlmostEqual(sv.safety.allocated_qty, safety_alloc)
        self.assertAlmostEqual(sv.safety.remaining, 0.0)   # safety ends full
        for o in orders:
            self.assertAlmostEqual(o.remaining, 0.0, msg=o.id)


class Test221Targeted(_SafetyViewCase):

    def test_no_penalties(self):
        """2.2.1.1 — P0 + safety covered; each chunk within lead before its
        order's due. No penalties."""
        sv, o = self._run(20.0, 30.0,
                          [(_dd(1, -2), 10), (_dd(2, -2), 10), (_dd(3, -2), 10),
                           (_dd(4, -2), 10), (_dd(5, -2), 10)])
        self._check(sv, o, 0.0, 0.0, 0.0, 0.0)

    def test_excess_only(self):
        """2.2.1.2 — as no-penalties but the P5 chunk overshoots by 5."""
        sv, o = self._run(20.0, 30.0,
                          [(_dd(1, -2), 10), (_dd(2, -2), 10), (_dd(3, -2), 10),
                           (_dd(4, -2), 10), (_dd(5, -2), 15)])
        self._check(sv, o, 0.0, 0.0, 5.0, 0.0)

    def test_carrying_one_chunk_p1_p2(self):
        """2.2.1.3 — first chunk fills P1 on time and P2 early."""
        sv, o = self._run(20.0, 30.0,
                          [(_dd(1, -2), 20), (_dd(3, -2), 10), (_dd(4, -2), 10),
                           (_dd(5, -2), 10)])
        self._check(sv, o, 60.0, 0.0, 0.0, 0.0)

    def test_carrying_one_chunk_p1_p2_p3(self):
        """2.2.1.4 — first chunk fills P1 on time and P2 + P3 early."""
        sv, o = self._run(20.0, 30.0,
                          [(_dd(1, -2), 30), (_dd(4, -2), 10), (_dd(5, -2), 10)])
        self._check(sv, o, 190.0, 0.0, 0.0, 0.0)

    def test_carrying_one_chunk_p1_part_p2(self):
        """2.2.1.5 — first chunk fills P1 on time and part of P2 early; a later
        chunk fills the rest on time."""
        sv, o = self._run(20.0, 30.0,
                          [(_dd(1, -2), 14), (_dd(2, -2), 6), (_dd(3, -2), 10),
                           (_dd(4, -2), 10), (_dd(5, -2), 10)])
        self._check(sv, o, 24.0, 0.0, 0.0, 0.0)

    def test_carrying_across_two_chunks(self):
        """2.2.1.6 — carrying from an early part of P2 (chunk 1) and an early part
        of P3 (chunk 2)."""
        sv, o = self._run(20.0, 30.0,
                          [(_dd(1, -2), 14), (_dd(2, -2), 10), (_dd(3, -2), 6),
                           (_dd(4, -2), 10), (_dd(5, -2), 10)])
        self._check(sv, o, 48.0, 0.0, 0.0, 0.0)

    def test_carrying_all_up_front(self):
        """2.2.1.7 — one chunk before P1's due fills everything (P2-P5 early)."""
        sv, o = self._run(20.0, 30.0, [(_dd(1, -2), 50)])
        self._check(sv, o, 660.0, 0.0, 0.0, 0.0)

    def test_drainage_p1_from_safety(self):
        """2.2.1.8 — nothing before P1's due; P1 is met from safety and the pool
        stays short until a chunk after P5 restores it."""
        sv, o = self._run(20.0, 30.0,
                          [(_dd(2, -2), 10), (_dd(3, -2), 10), (_dd(4, -2), 10),
                           (_dd(5, -2), 10), (_dd(5, 5), 10)])
        self._check(sv, o, 0.0, 200.0, 0.0, 0.0)

    def test_drainage_rebuild_safety(self):
        """2.2.1.9 — safety uncovered at start; rebuilt over the first chunks."""
        sv, o = self._run(0.0, 10.0,
                          [(_dd(1, -2), 10), (_dd(2, -2), 20), (_dd(3, -2), 20),
                           (_dd(4, -2), 10), (_dd(5, -2), 10)])
        self._check(sv, o, 0.0, 320.0, 0.0, 20.0)

    def test_drainage_dip_then_restore(self):
        """2.2.1.10 — safety drained across the first two orders, then a catch-up
        chunk restores it before P3."""
        sv, o = self._run(20.0, 30.0,
                          [(_dd(1, 3), 8), (_dd(2, 1), 8), (_dd(2, 4), 14),
                           (_dd(4, -2), 10), (_dd(5, -2), 10)])
        self._check(sv, o, 0.0, 62.0, 0.0, 0.0)


class Test222Mixed(_SafetyViewCase):

    # carrying + excess
    def test_ce_one_over_large_early_chunk(self):
        """2.2.2.1 — one chunk before P1's due larger than total demand."""
        sv, o = self._run(20.0, 30.0, [(_dd(1, -2), 65)])
        self._check(sv, o, 660.0, 0.0, 15.0, 0.0)

    def test_ce_split_order_plus_overshoot(self):
        """2.2.2.2 — P2 split across two chunks (one early) plus a P5 overshoot."""
        sv, o = self._run(20.0, 30.0,
                          [(_dd(1, -2), 14), (_dd(2, -2), 6), (_dd(3, -2), 10),
                           (_dd(4, -2), 10), (_dd(5, -2), 15)])
        self._check(sv, o, 24.0, 0.0, 5.0, 0.0)

    def test_ce_two_early_multi_order_plus_overshoot(self):
        """2.2.2.3 — two early multi-order chunks (P2 and P4 early) plus a P5
        overshoot."""
        sv, o = self._run(20.0, 30.0,
                          [(_dd(1, -2), 20), (_dd(3, -2), 20), (_dd(5, -2), 15)])
        self._check(sv, o, 120.0, 0.0, 5.0, 0.0)

    # drainage + excess
    def test_de_p1_from_safety_plus_overshoot(self):
        """2.2.2.4 — P1 from safety (drainage) plus a tail overshoot."""
        sv, o = self._run(20.0, 30.0,
                          [(_dd(2, -2), 10), (_dd(3, -2), 10), (_dd(4, -2), 10),
                           (_dd(5, -2), 10), (_dd(5, 5), 15)])
        self._check(sv, o, 0.0, 200.0, 5.0, 0.0)

    def test_de_dip_plus_overshoot(self):
        """2.2.2.5 — a one-day P1 dip (drainage) plus a tail overshoot."""
        sv, o = self._run(20.0, 30.0,
                          [(_dd(1, 1), 10), (_dd(2, -2), 10), (_dd(3, -2), 10),
                           (_dd(4, -2), 10), (_dd(5, -2), 15)])
        self._check(sv, o, 0.0, 10.0, 5.0, 0.0)

    def test_de_uncovered_safety_plus_overshoot(self):
        """2.2.2.6 — safety uncovered (drainage while rebuilding) plus an
        overshoot."""
        sv, o = self._run(0.0, 10.0,
                          [(_dd(1, -2), 10), (_dd(2, -2), 20), (_dd(3, -2), 20),
                           (_dd(4, -2), 10), (_dd(5, -2), 15)])
        self._check(sv, o, 0.0, 320.0, 5.0, 20.0)

    # drainage + carrying
    def test_dc_safety_then_early_catch_up(self):
        """2.2.2.7 — P1/P2 from safety (drainage); catch-up chunk fills P3 on time
        and P4 early (carrying)."""
        sv, o = self._run(20.0, 30.0, [(_dd(2, 4), 40), (_dd(5, -2), 10)])
        self._check(sv, o, 70.0, 150.0, 0.0, 0.0)

    def test_dc_partial_draw_plus_early_chunk(self):
        """2.2.2.8 — partial early draw (drainage) plus a multi-order chunk that
        reaches P4 early (carrying)."""
        sv, o = self._run(20.0, 30.0,
                          [(_dd(1, 1), 6), (_dd(2, 4), 34), (_dd(5, -2), 10)])
        self._check(sv, o, 70.0, 90.0, 0.0, 0.0)

    def test_dc_uncovered_plus_early_fill(self):
        """2.2.2.9 — safety uncovered (drainage) plus an early fill of P4
        (carrying); sizes exact."""
        sv, o = self._run(0.0, 10.0,
                          [(_dd(1, -2), 10), (_dd(2, -2), 30), (_dd(3, -2), 20),
                           (_dd(5, -2), 10)])
        self._check(sv, o, 60.0, 270.0, 0.0, 20.0)

    # all three
    def test_all_catch_up_that_overshoots(self):
        """2.2.2.10 — P1/P2 from safety (drainage); a catch-up chunk fills P3 on
        time, P4/P5 early (carrying), and overshoots (excess)."""
        sv, o = self._run(20.0, 30.0, [(_dd(2, 4), 20), (_dd(3, -3), 35)])
        self._check(sv, o, 210.0, 150.0, 5.0, 0.0)

    def test_all_partial_draw_early_fill_overshoot(self):
        """2.2.2.11 — partial early draw (drainage), an early fill (carrying), and
        a P5 overshoot (excess)."""
        sv, o = self._run(20.0, 30.0,
                          [(_dd(1, 1), 6), (_dd(2, 4), 24), (_dd(3, -3), 10),
                           (_dd(5, -2), 20)])
        self._check(sv, o, 70.0, 90.0, 10.0, 0.0)

    def test_all_uncovered_early_multi_order_overshoot(self):
        """2.2.2.12 — safety uncovered (drainage), an early multi-order chunk
        (carrying), and an overshoot (excess)."""
        sv, o = self._run(0.0, 10.0,
                          [(_dd(1, -2), 10), (_dd(2, -2), 30), (_dd(3, -3), 35)])
        self._check(sv, o, 210.0, 270.0, 5.0, 20.0)


if __name__ == '__main__':
    unittest.main()
