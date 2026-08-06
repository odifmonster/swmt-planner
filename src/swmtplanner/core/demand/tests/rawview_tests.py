#!/usr/bin/env python

import math
import unittest
from datetime import datetime, timedelta

from swmtplanner.core.product import Fabric
from swmtplanner.core.demand import RawView, RawOrder, Chunk


FW = (2026, 2)
# six orders due on the Tuesday (iso_weekday 2) of six consecutive weeks
DUES = [datetime.fromisocalendar(2026, 2 + i, 2) for i in range(6)]
INIT = 10.0


def _fabric(id: str = 'F1') -> Fabric:
    return Fabric(id=id, ply1_parts=(), greige='G', style='S', width=60.0,
                  oz_sq_yd=10.0, yld_pct=0.9, name='N', number=1,
                  shade_rating=0, jets={})


class _RawViewCase(unittest.TestCase):
    """Shared driver: six RawOrders P0-2 … P5-2 (covered_on_hand 0). Append
    chunks in chronological order, recompute(chunks) after each, and verify every
    order's remaining / late table / late_fill_date / late_qty and the view's
    lateness. `expected` maps order index -> (remaining, [(avail_date, qty), ...])
    for its *late* portions; unlisted orders default to (INIT, [])."""

    def setUp(self):
        self.f = _fabric()
        self.orders = [RawOrder(self.f, INIT, 0.0, FW, DUES[i]) for i in range(6)]
        self.view = RawView(self.f, self.orders)
        self.chunks = []

    def _step(self, chunk, expected):
        self.chunks.append(chunk)
        self.view.recompute(self.chunks)
        lateness = 0.0
        for i, order in enumerate(self.orders):
            remaining, portions = expected.get(i, (INIT, []))
            self.assertAlmostEqual(order.remaining, remaining, msg=order.id)
            self.assertEqual(order.late_table(),
                             [(a - order.due_date, q) for a, q in portions],
                             order.id)
            self.assertAlmostEqual(order.late_qty, sum(q for _, q in portions),
                                   msg=order.id)
            self.assertEqual(order.late_fill_date,
                             portions[-1][0] if portions else None, order.id)
            for a, q in portions:
                lateness += q * 2.0 ** ((a - order.due_date).total_seconds()
                                        / 86400)
        self.assertTrue(math.isclose(self.view.lateness, lateness,
                                     rel_tol=1e-9, abs_tol=1e-9),
                        (self.view.lateness, lateness))


class Test211WholeOrder(_RawViewCase):

    def test_one_early_chunk_fills_all(self):
        """2.1.1.1 — one chunk before the first due date fills every order on
        time; nothing late, lateness 0."""
        c = Chunk(self.f, DUES[0] - timedelta(days=5), 60.0)
        self._step(c, {i: (0.0, []) for i in range(6)})

    def test_one_late_chunk_fills_all(self):
        """2.1.1.2 — one chunk one day after the last due date fills every order
        late (each at its own lag)."""
        avail = DUES[5] + timedelta(days=1)
        c = Chunk(self.f, avail, 60.0)
        self._step(c, {i: (0.0, [(avail, 10.0)]) for i in range(6)})

    def test_one_on_time_chunk_per_order(self):
        """2.1.1.3 — six chunks, the i-th just before order i's due and sized to
        it: each fills its order on time; lateness stays 0."""
        for i in range(6):
            c = Chunk(self.f, DUES[i] - timedelta(days=1), 10.0)
            self._step(c, {j: (0.0, []) for j in range(i + 1)})

    def test_one_late_chunk_per_order(self):
        """2.1.1.4 — six chunks, the i-th one day after order i's due: each fills
        its order one day late; lateness grows each step."""
        for i in range(6):
            avail = DUES[i] + timedelta(days=1)
            c = Chunk(self.f, avail, 10.0)
            self._step(c, {j: (0.0, [(DUES[j] + timedelta(days=1), 10.0)])
                           for j in range(i + 1)})


class Test212Split(_RawViewCase):

    def test_late_first_then_forward(self):
        """2.1.2.1 — chunk 1 fills P0 late + part of P1 on time; chunk 2 fills the
        rest of P1 late; chunk 3 fills P2–P5 on time."""
        a1 = DUES[0] + timedelta(days=2)
        self._step(Chunk(self.f, a1, 15.0),
                   {0: (0.0, [(a1, 10.0)]), 1: (5.0, [])})
        a2 = DUES[1] + timedelta(days=3)
        self._step(Chunk(self.f, a2, 5.0),
                   {0: (0.0, [(a1, 10.0)]), 1: (0.0, [(a2, 5.0)])})
        a3 = DUES[2] - timedelta(days=1)
        self._step(Chunk(self.f, a3, 40.0),
                   {0: (0.0, [(a1, 10.0)]), 1: (0.0, [(a2, 5.0)]),
                    2: (0.0, []), 3: (0.0, []), 4: (0.0, []), 5: (0.0, [])})

    def test_first_order_split_across_two_late_chunks(self):
        """2.1.2.2 — P0 filled by two late chunks (two late-table entries); the
        second also fills P1 on time; a third fills the rest on time."""
        a1 = DUES[0] + timedelta(days=2)
        self._step(Chunk(self.f, a1, 4.0), {0: (6.0, [(a1, 4.0)])})
        a2 = DUES[0] + timedelta(days=4)
        self._step(Chunk(self.f, a2, 16.0),
                   {0: (0.0, [(a1, 4.0), (a2, 6.0)]), 1: (0.0, [])})
        a3 = DUES[2] - timedelta(days=1)
        self._step(Chunk(self.f, a3, 40.0),
                   {0: (0.0, [(a1, 4.0), (a2, 6.0)]), 1: (0.0, []),
                    2: (0.0, []), 3: (0.0, []), 4: (0.0, []), 5: (0.0, [])})

    def test_several_mid_sequence_split_both_ways(self):
        """2.1.2.3 — two chunks after P1's due fill P0/P1 late and part of P2 on
        time; then on-time chunks fill the rest, splitting both ways."""
        a1 = DUES[1] + timedelta(days=1)
        self._step(Chunk(self.f, a1, 10.0), {0: (0.0, [(a1, 10.0)])})
        a2 = DUES[1] + timedelta(days=3)
        self._step(Chunk(self.f, a2, 15.0),
                   {0: (0.0, [(a1, 10.0)]), 1: (0.0, [(a2, 10.0)]), 2: (5.0, [])})
        b = DUES[2] - timedelta(days=1)
        self._step(Chunk(self.f, b, 9.0),
                   {0: (0.0, [(a1, 10.0)]), 1: (0.0, [(a2, 10.0)]),
                    2: (0.0, []), 3: (6.0, [])})
        c = DUES[3] - timedelta(days=1)
        self._step(Chunk(self.f, c, 26.0),
                   {0: (0.0, [(a1, 10.0)]), 1: (0.0, [(a2, 10.0)]),
                    2: (0.0, []), 3: (0.0, []), 4: (0.0, []), 5: (0.0, [])})

    def test_back_fill_after_last_due(self):
        """2.1.2.4 — chunks all after the last due date back-fill the orders from
        the first; every filled portion is late."""
        a1 = DUES[5] + timedelta(days=1)
        self._step(Chunk(self.f, a1, 25.0),
                   {0: (0.0, [(a1, 10.0)]), 1: (0.0, [(a1, 10.0)]),
                    2: (5.0, [(a1, 5.0)])})
        a2 = DUES[5] + timedelta(days=3)
        self._step(Chunk(self.f, a2, 25.0),
                   {0: (0.0, [(a1, 10.0)]), 1: (0.0, [(a1, 10.0)]),
                    2: (0.0, [(a1, 5.0), (a2, 5.0)]), 3: (0.0, [(a2, 10.0)]),
                    4: (0.0, [(a2, 10.0)])})
        a3 = DUES[5] + timedelta(days=5)
        self._step(Chunk(self.f, a3, 10.0),
                   {0: (0.0, [(a1, 10.0)]), 1: (0.0, [(a1, 10.0)]),
                    2: (0.0, [(a1, 5.0), (a2, 5.0)]), 3: (0.0, [(a2, 10.0)]),
                    4: (0.0, [(a2, 10.0)]), 5: (0.0, [(a3, 10.0)])})


if __name__ == '__main__':
    unittest.main()
