#!/usr/bin/env python

import unittest
from datetime import date

from swmtplanner.support.workcal.holiday import FixedDate, FlexDate


class FixedDateTests(unittest.TestCase):
    """Covers section 1.1 of COVERAGE.md."""

    def test_construction(self):
        """1.1.1: construction works as expected"""
        christmas = FixedDate(name='Christmas', month=12, day=25)
        self.assertEqual(christmas.name, 'Christmas')
        self.assertEqual(christmas.month, 12)
        self.assertEqual(christmas.day, 25)

    def test_date_in_year(self):
        """1.1.2: date_in_year works as expected for multiple years"""
        christmas = FixedDate(name='Christmas', month=12, day=25)
        self.assertEqual(christmas.date_in_year(2025), date(2025, 12, 25))
        self.assertEqual(christmas.date_in_year(2026), date(2026, 12, 25))


class FlexDateTests(unittest.TestCase):
    """Covers section 1.2 of COVERAGE.md."""

    def setUp(self):
        self.thanksgiving = FlexDate(name='Thanksgiving', month=11, weekday=3, n=4)
        self.mem_day = FlexDate(name='Memorial Day', month=5, weekday=0, n=-1)

    def test_construction(self):
        """1.2.1: construction works as expected"""
        self.assertEqual(self.thanksgiving.name, 'Thanksgiving')
        self.assertEqual(self.thanksgiving.month, 11)
        self.assertEqual(self.thanksgiving.weekday, 3)
        self.assertEqual(self.thanksgiving.n, 4)

        self.assertEqual(self.mem_day.name, 'Memorial Day')
        self.assertEqual(self.mem_day.month, 5)
        self.assertEqual(self.mem_day.weekday, 0)
        self.assertEqual(self.mem_day.n, -1)

    def test_date_in_year_2026(self):
        """1.2.2: 2026 yields Nov 26 (Thanksgiving) and May 25 (Memorial Day)"""
        self.assertEqual(self.thanksgiving.date_in_year(2026), date(2026, 11, 26))
        self.assertEqual(self.mem_day.date_in_year(2026), date(2026, 5, 25))

    def test_date_in_year_2025(self):
        """1.2.2: 2025 yields Nov 27 (Thanksgiving) and May 26 (Memorial Day)"""
        self.assertEqual(self.thanksgiving.date_in_year(2025), date(2025, 11, 27))
        self.assertEqual(self.mem_day.date_in_year(2025), date(2025, 5, 26))


if __name__ == '__main__':
    unittest.main()
