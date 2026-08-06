#!/usr/bin/env python

import unittest
from datetime import datetime, timedelta

from swmtplanner.core.product import Fabric
from swmtplanner.core.demand import Order, RawOrder, Chunk


def _fabric(id: str = 'F1') -> Fabric:
    return Fabric(id=id, ply1_parts=(), greige='G', style='S', width=60.0,
                  oz_sq_yd=10.0, yld_pct=0.9, name='N', number=1,
                  shade_rating=0, jets={})


def _order(first_week: tuple[int, int], offset: int, weekday: int,
           item: Fabric) -> Order:
    """Build an Order whose due date is `offset` ISO weeks and `weekday - 1`
    days past the Monday of `first_week` (so it lands on ISO weekday `weekday`
    of week first_week + offset)."""
    monday = datetime.fromisocalendar(first_week[0], first_week[1], 1)
    due = monday + timedelta(weeks=offset, days=weekday - 1)
    return Order(item, 10.0, 0.0, first_week, due)


class TestOrderId(unittest.TestCase):
    """1.2.1 — Order.id and Order.week_offset. Each scenario walks the matrix
    offset in {0, 2, -1} x iso_weekday in {1, 3, 6}, checking both the id string
    ('P{offset}-{weekday}@{fabric id}') and the week_offset value."""

    OFFSETS = (0, 2, -1)
    WEEKDAYS = (1, 3, 6)

    def _check_matrix(self, first_week: tuple[int, int]):
        f = _fabric()
        for offset in self.OFFSETS:
            for wd in self.WEEKDAYS:
                o = _order(first_week, offset, wd, f)
                self.assertEqual(o.week_offset, offset, (first_week, offset, wd))
                self.assertEqual(o.id, f'P{offset}-{wd}@{f.id}',
                                 (first_week, offset, wd))

    def test_mid_year(self):
        """1.2.1 — mid-year first_week (week 26): baseline, no year-boundary
        effects."""
        self._check_matrix((2026, 26))

    def test_year_crossing(self):
        """1.2.1 — year-crossing first_week (2020-W53, whose Monday is in 2020
        and later days fall in 2021): P0 due dates whose calendar year differs
        from their ISO year still key off the ISO week."""
        # sanity: this week really does straddle the year boundary
        mon = datetime.fromisocalendar(2020, 53, 1)
        self.assertEqual(mon.year, 2020)
        self.assertEqual((mon + timedelta(days=4)).year, 2021)
        self._check_matrix((2020, 53))

    def test_near_year_end(self):
        """1.2.1 — near-year-end first_week (2025-W51): the P2 outcomes land in
        the following ISO year, so week_offset is counted across the boundary."""
        # sanity: P2 (two weeks on) is in ISO year 2026
        p2_mon = datetime.fromisocalendar(2025, 51, 1) + timedelta(weeks=2)
        self.assertEqual(p2_mon.isocalendar()[0], 2026)
        self._check_matrix((2025, 51))


class TestRawOrderLate(unittest.TestCase):
    """1.2.2 — RawOrder late calculations. These only add/clear chunks; they do
    not touch allocated_qty (remaining is covered by 1.1)."""

    DUE = datetime(2026, 6, 15)

    def _ro(self, f: Fabric) -> RawOrder:
        return RawOrder(f, 100.0, 0.0, (2026, 1), self.DUE)

    def test_empty_after_construction(self):
        """1.2.2.1 — fresh RawOrder: empty late table, late_qty 0, fill date
        None."""
        ro = self._ro(_fabric())
        self.assertEqual(ro.late_table(), [])
        self.assertEqual(ro.late_qty, 0.0)
        self.assertIsNone(ro.late_fill_date)

    def test_all_on_time(self):
        """1.2.2.2 — only on-time chunks (avail_date <= due_date), added out of
        chronological order: the late values stay empty."""
        f = _fabric()
        ro = self._ro(f)
        ro.add_chunk(Chunk(f, self.DUE - timedelta(days=3), 5.0))
        ro.add_chunk(Chunk(f, self.DUE - timedelta(days=10), 2.0))
        ro.add_chunk(Chunk(f, self.DUE, 1.0))   # exactly on the due date -> on time
        self.assertEqual(ro.late_table(), [])
        self.assertEqual(ro.late_qty, 0.0)
        self.assertIsNone(ro.late_fill_date)

    def test_one_late_chunk(self):
        """1.2.2.3 — one late chunk populates late_qty, late_fill_date and the
        late table."""
        f = _fabric()
        ro = self._ro(f)
        avail = self.DUE + timedelta(days=3)
        ro.add_chunk(Chunk(f, avail, 5.0))
        self.assertEqual(ro.late_qty, 5.0)
        self.assertEqual(ro.late_fill_date, avail)
        self.assertEqual(ro.late_table(), [(timedelta(days=3), 5.0)])

    def test_multiple_late_out_of_order(self):
        """1.2.2.4 — several late chunks added out of chronological order: total
        late_qty, latest avail_date as late_fill_date, and a late table sorted by
        avail_date."""
        f = _fabric()
        ro = self._ro(f)
        ro.add_chunk(Chunk(f, self.DUE + timedelta(days=5), 4.0))
        ro.add_chunk(Chunk(f, self.DUE + timedelta(days=1), 2.0))
        ro.add_chunk(Chunk(f, self.DUE + timedelta(days=10), 6.0))
        self.assertEqual(ro.late_qty, 12.0)
        self.assertEqual(ro.late_fill_date, self.DUE + timedelta(days=10))
        self.assertEqual(ro.late_table(),
                         [(timedelta(days=1), 2.0),
                          (timedelta(days=5), 4.0),
                          (timedelta(days=10), 6.0)])

    def test_mixed_late_and_on_time(self):
        """1.2.2.5 — a mix of on-time and late chunks out of order: only the late
        chunks contribute, and the late table holds just those, sorted by
        avail_date."""
        f = _fabric()
        ro = self._ro(f)
        ro.add_chunk(Chunk(f, self.DUE + timedelta(days=7), 5.0))   # late
        ro.add_chunk(Chunk(f, self.DUE - timedelta(days=2), 3.0))   # on time
        ro.add_chunk(Chunk(f, self.DUE + timedelta(days=2), 4.0))   # late
        ro.add_chunk(Chunk(f, self.DUE, 1.0))                       # on time
        self.assertEqual(ro.late_qty, 9.0)
        self.assertEqual(ro.late_fill_date, self.DUE + timedelta(days=7))
        self.assertEqual(ro.late_table(),
                         [(timedelta(days=2), 4.0),
                          (timedelta(days=7), 5.0)])

    def test_clear_resets(self):
        """1.2.2.6 — clear_chunks() returns everything to the construction
        state."""
        f = _fabric()
        ro = self._ro(f)
        ro.add_chunk(Chunk(f, self.DUE + timedelta(days=2), 4.0))   # late
        ro.add_chunk(Chunk(f, self.DUE - timedelta(days=1), 3.0))   # on time
        self.assertNotEqual(ro.late_table(), [])
        ro.clear_chunks()
        self.assertEqual(ro.late_table(), [])
        self.assertEqual(ro.late_qty, 0.0)
        self.assertIsNone(ro.late_fill_date)


if __name__ == '__main__':
    unittest.main()
