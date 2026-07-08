#!/usr/bin/env python

import unittest
from datetime import datetime

from swmtplanner.core.materials import RawMat


class TestRawMat(unittest.TestCase):

    def test_construction(self):
        """1.1.1 — attributes are stored and exposed as read-only properties."""
        d = datetime(2026, 7, 1, 8, 0)
        m = RawMat(id='M1', sku='SKU1', avail_date=d, qty=500.0, unit='lbs')
        self.assertEqual(m.id, 'M1')
        self.assertEqual(m.sku, 'SKU1')
        self.assertEqual(m.avail_date, d)
        self.assertEqual(m.qty, 500.0)
        self.assertEqual(m.unit, 'lbs')


if __name__ == '__main__':
    unittest.main()
