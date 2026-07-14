#!/usr/bin/env python

import unittest
from datetime import datetime

from swmtplanner.core.materials import RawMat
from swmtplanner.core.materials.inventory import (
    ValGroup, SortedGroup, Exactly, Greater, Less, InRange,
)

GROUPS = (ValGroup, SortedGroup)

D1 = datetime(2026, 7, 1)
D2 = datetime(2026, 7, 2)
D3 = datetime(2026, 7, 3)
D4 = datetime(2026, 7, 4)
D5 = datetime(2026, 7, 5)


def _mat(id, avail):
    return RawMat(id=id, sku='S', avail_date=avail, qty=1.0, unit='lbs')


def _build(cls, mats):
    g = cls('avail_date')
    for m in mats:
        g.add(m)
    return g


class TestGroups(unittest.TestCase):

    def test_single_object(self):
        """2.1 — one object: get_group on its avail_date returns just it, empty
        otherwise."""
        for cls in GROUPS:
            with self.subTest(cls=cls.__name__):
                m = _mat('A', D1)
                g = _build(cls, [m])
                self.assertEqual(g.get_group(Exactly(D1)), {m})
                self.assertEqual(g.get_group(Exactly(D2)), set())

    def test_multiple_values(self):
        """2.2 — objects across multiple avail_dates: get_group per value."""
        for cls in GROUPS:
            with self.subTest(cls=cls.__name__):
                a, b, c = _mat('A', D1), _mat('B', D1), _mat('C', D2)
                d, e = _mat('D', D3), _mat('E', D3)
                g = _build(cls, [a, b, c, d, e])
                self.assertEqual(g.get_group(Exactly(D1)), {a, b})
                self.assertEqual(g.get_group(Exactly(D2)), {c})
                self.assertEqual(g.get_group(Exactly(D3)), {d, e})

    def test_remove_updates(self):
        """2.3 — remove updates the group."""
        for cls in GROUPS:
            with self.subTest(cls=cls.__name__):
                a, b = _mat('A', D1), _mat('B', D1)
                g = _build(cls, [a, b])
                g.remove('A', D1)
                self.assertEqual(g.get_group(Exactly(D1)), {b})

    def test_remove_unknown_id(self):
        """2.4 — remove with an unknown id raises KeyError."""
        for cls in GROUPS:
            with self.subTest(cls=cls.__name__):
                g = _build(cls, [_mat('A', D1)])
                with self.assertRaises(KeyError):
                    g.remove('NOPE', D1)

    def test_remove_wrong_value(self):
        """2.5 — remove with the wrong avail_date for the object raises
        KeyError."""
        for cls in GROUPS:
            with self.subTest(cls=cls.__name__):
                g = _build(cls, [_mat('A', D1)])
                with self.assertRaises(KeyError):
                    g.remove('A', D2)

    def test_greater_matches_exactly(self):
        """2.6 — a Greater covering exactly one date matches the Exactly set."""
        for cls in GROUPS:
            with self.subTest(cls=cls.__name__):
                g = _build(cls, [_mat('A', D1), _mat('B', D2), _mat('C', D3)])
                self.assertEqual(g.get_group(Greater(D2)),
                                 g.get_group(Exactly(D3)))

    def test_less_matches_exactly(self):
        """2.7 — a Less covering exactly one date matches the Exactly set."""
        for cls in GROUPS:
            with self.subTest(cls=cls.__name__):
                g = _build(cls, [_mat('A', D1), _mat('B', D2), _mat('C', D3)])
                self.assertEqual(g.get_group(Less(D2)),
                                 g.get_group(Exactly(D1)))

    def test_ranges_over_multiple_groups(self):
        """2.8 — Greater/Less/InRange over multiple dates return correct sets."""
        for cls in GROUPS:
            with self.subTest(cls=cls.__name__):
                a, b, c = _mat('A', D1), _mat('B', D2), _mat('C', D3)
                g = _build(cls, [a, b, c])
                self.assertEqual(g.get_group(Greater(D1)), {b, c})
                self.assertEqual(g.get_group(Less(D3)), {a, b})
                self.assertEqual(g.get_group(InRange(D1, D3)), {a, b})

    def test_empty_ranges(self):
        """2.9 — Greater/Less/InRange excluding all dates return empty sets."""
        for cls in GROUPS:
            with self.subTest(cls=cls.__name__):
                a, b, c = _mat('A', D1), _mat('B', D2), _mat('C', D3)
                g = _build(cls, [a, b, c])
                self.assertEqual(g.get_group(Greater(D3)), set())
                self.assertEqual(g.get_group(Less(D1)), set())
                self.assertEqual(g.get_group(InRange(D4, D5)), set())


if __name__ == '__main__':
    unittest.main()
