#!/usr/bin/env python

import unittest

from swmtplanner.core.materials.inventory import (
    Exactly, NotExactly, Greater, Less, InRange,
)


class TestConditions(unittest.TestCase):

    def test_exactly(self):
        """1.1 — Exactly construction + predicate."""
        c = Exactly(5)
        self.assertEqual(c.val, 5)
        f = c.to_func()
        self.assertTrue(f(5))
        self.assertFalse(f(4))

    def test_not_exactly(self):
        """1.2 — NotExactly construction + predicate."""
        c = NotExactly(5)
        self.assertEqual(c.val, 5)
        f = c.to_func()
        self.assertFalse(f(5))
        self.assertTrue(f(4))

    def test_greater(self):
        """1.3 — Greater, exclusive and inclusive."""
        excl = Greater(10)
        self.assertEqual((excl.lo, excl.incl), (10, False))
        fe = excl.to_func()
        self.assertFalse(fe(9))
        self.assertFalse(fe(10))
        self.assertTrue(fe(11))
        fi = Greater(10, incl=True).to_func()
        self.assertFalse(fi(9))
        self.assertTrue(fi(10))
        self.assertTrue(fi(11))

    def test_less(self):
        """1.4 — Less, exclusive and inclusive."""
        fe = Less(10).to_func()
        self.assertTrue(fe(9))
        self.assertFalse(fe(10))
        self.assertFalse(fe(11))
        fi = Less(10, incl=True).to_func()
        self.assertTrue(fi(9))
        self.assertTrue(fi(10))
        self.assertFalse(fi(11))

    def test_in_range(self):
        """1.5 — InRange, default bounds and flipped inclusivity."""
        # default: incl_lo=True, incl_hi=False -> [10, 20)
        d = InRange(10, 20).to_func()
        self.assertFalse(d(9))
        self.assertTrue(d(10))
        self.assertTrue(d(15))
        self.assertFalse(d(20))
        self.assertFalse(d(21))
        # flipped -> (10, 20]
        f = InRange(10, 20, incl_lo=False, incl_hi=True).to_func()
        self.assertFalse(f(10))
        self.assertTrue(f(11))
        self.assertTrue(f(20))
        self.assertFalse(f(21))


if __name__ == '__main__':
    unittest.main()
