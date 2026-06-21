#!/usr/bin/env python

import unittest
from datetime import date

from swmtplanner.support.workcal.holiday import (
    FixedDate, FlexDate, load_holidays
)


class TestFixedDate(unittest.TestCase):

    def test_construction(self):
        """1.1.1 — fields are stored correctly."""
        h = FixedDate(name='Christmas', month=12, day=25)
        self.assertEqual(h.name, 'Christmas')
        self.assertEqual(h.month, 12)
        self.assertEqual(h.day, 25)

    def test_get_date_in_year(self):
        """1.1.2 — returns the expected date."""
        h = FixedDate(name='Christmas', month=12, day=25)
        self.assertEqual(h.get_date_in_year(2026), date(2026, 12, 25))


class TestFlexDate(unittest.TestCase):

    def test_construction(self):
        """1.2.1 — fields are stored correctly."""
        h = FlexDate(name='Memorial Day', month=5, weekday=0, n=-1)
        self.assertEqual(h.name, 'Memorial Day')
        self.assertEqual(h.month, 5)
        self.assertEqual(h.weekday, 0)
        self.assertEqual(h.n, -1)

    def test_get_date_in_year_positive_n(self):
        """1.2.2 — nth-weekday calculation for positive n (4th Thursday of
        November, 2026 = 2026-11-26)."""
        h = FlexDate(name='Thanksgiving', month=11, weekday=3, n=4)
        self.assertEqual(h.get_date_in_year(2026), date(2026, 11, 26))

    def test_get_date_in_year_negative_n(self):
        """1.2.3 — calculation for negative n (last Monday of May, 2026 =
        2026-05-25)."""
        h = FlexDate(name='Memorial Day', month=5, weekday=0, n=-1)
        self.assertEqual(h.get_date_in_year(2026), date(2026, 5, 25))

    def test_get_date_in_year_known_dates(self):
        """1.2.4 — a couple of known dates across two weekdays (Thursday and
        Monday) and a couple of years."""
        thanksgiving = FlexDate(name='Thanksgiving', month=11, weekday=3, n=4)
        self.assertEqual(thanksgiving.get_date_in_year(2025), date(2025, 11, 27))
        self.assertEqual(thanksgiving.get_date_in_year(2026), date(2026, 11, 26))

        memorial = FlexDate(name='Memorial Day', month=5, weekday=0, n=-1)
        self.assertEqual(memorial.get_date_in_year(2025), date(2025, 5, 26))
        self.assertEqual(memorial.get_date_in_year(2026), date(2026, 5, 25))


class TestLoadHolidays(unittest.TestCase):

    def test_error_not_a_list(self):
        """1.3.1 — a JSON string that is not a list raises ValueError."""
        with self.assertRaises(ValueError):
            load_holidays('{"name": "Christmas", "month": 12, "day": 25}')

    def test_error_element_not_object(self):
        """1.3.2 — a list element that is not a JSON object raises
        ValueError."""
        with self.assertRaises(ValueError):
            load_holidays('[1]')

    def test_error_element_wrong_fields(self):
        """1.3.3 — a list element whose fields match no holiday type raises
        ValueError."""
        with self.assertRaises(ValueError):
            load_holidays('[{"name": "Mystery", "month": 1}]')

    def test_valid_input(self):
        """1.3.4 — a valid string (mixing FixedDate and FlexDate) returns the
        correct list of Holiday objects."""
        json_str = (
            '[{"name": "Christmas", "month": 12, "day": 25}, '
            '{"name": "Memorial Day", "month": 5, "weekday": 0, "n": -1}]'
        )
        result = load_holidays(json_str)
        self.assertEqual(result, [
            FixedDate(name='Christmas', month=12, day=25),
            FlexDate(name='Memorial Day', month=5, weekday=0, n=-1),
        ])


if __name__ == '__main__':
    unittest.main()
