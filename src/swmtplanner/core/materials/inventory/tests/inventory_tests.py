#!/usr/bin/env python

import unittest
from datetime import datetime

from swmtplanner.core.materials import RawMat
from swmtplanner.core.materials.inventory import (
    Inventory, Exactly, NotExactly, Greater, Less, InRange,
)

D1 = datetime(2026, 7, 1)
D2 = datetime(2026, 7, 2)

GROUPED = ['sku', 'unit']
SORTED = ['qty', 'avail_date', 'consumed_date']


class _Consumable(RawMat):
    """A RawMat with a mutable consumed_date, for exercising the grouping guard."""

    def __init__(self, id, sku, avail_date, qty, unit, consumed_date):
        super().__init__(id, sku, avail_date, qty, unit)
        self.consumed_date = consumed_date


def _fresh():
    return Inventory(grouped=GROUPED, sorted=SORTED)


def _cons(id, sku='S1', qty=100.0, unit='lbs', avail=D1, consumed=D1):
    return _Consumable(id, sku, avail, qty, unit, consumed)


def _populated():
    inv = _fresh()
    mats = {
        'A': _cons('A', 'S1', 100.0, 'lbs'),
        'B': _cons('B', 'S1', 200.0, 'lbs'),
        'C': _cons('C', 'S2', 200.0, 'yd'),
        'D': _cons('D', 'S2', 300.0, 'yd'),
        'E': _cons('E', 'S3', 300.0, 'yd'),
    }
    for m in mats.values():
        inv.add(m)
    return inv, mats


class TestInventoryEmpty(unittest.TestCase):

    def test_empty(self):
        """3.1.1 — select_where returns empty for any conditions after
        construction."""
        inv = _fresh()
        self.assertEqual(inv.select_where(sku='X'), [])
        self.assertEqual(inv.select_where(qty=Greater(0.0)), [])
        self.assertEqual(inv.select_where(sku='X', unit='lbs', qty=Less(999.0)), [])


class TestInventoryAddRemove(unittest.TestCase):

    def test_add_remove(self):
        """3.2.1 — add/remove reflected by select_where() with no conditions."""
        inv = _fresh()
        a, b = _cons('A'), _cons('B')
        inv.add(a)
        inv.add(b)
        self.assertEqual(set(inv.select_where()), {a, b})
        inv.remove('A')
        self.assertEqual(set(inv.select_where()), {b})

    def test_add_duplicate(self):
        """3.2.2 — adding a duplicate id raises ValueError."""
        inv = _fresh()
        inv.add(_cons('A'))
        with self.assertRaises(ValueError):
            inv.add(_cons('A'))

    def test_remove_missing(self):
        """3.2.3 — removing a non-existent id raises KeyError."""
        inv = _fresh()
        with self.assertRaises(KeyError):
            inv.remove('NOPE')

    def test_remove_after_mutation(self):
        """3.2.4 — mutating consumed_date after adding, then removing, raises
        KeyError (broken-grouping guard)."""
        inv = _fresh()
        m = _cons('A', consumed=D1)
        inv.add(m)
        m.consumed_date = D2
        with self.assertRaises(KeyError):
            inv.remove('A')


class TestInventorySelectWhere(unittest.TestCase):

    def test_single_condition_per_type(self):
        """3.3.1 — each condition type on a sorted (qty) and a value-grouped
        (sku) attribute."""
        inv, m = _populated()
        # sorted attribute: qty
        self.assertEqual(set(inv.select_where(qty=Exactly(200.0))),
                         {m['B'], m['C']})
        self.assertEqual(set(inv.select_where(qty=NotExactly(200.0))),
                         {m['A'], m['D'], m['E']})
        self.assertEqual(set(inv.select_where(qty=Greater(200.0))),
                         {m['D'], m['E']})
        self.assertEqual(set(inv.select_where(qty=Less(200.0))), {m['A']})
        self.assertEqual(set(inv.select_where(qty=InRange(100.0, 300.0))),
                         {m['A'], m['B'], m['C']})
        # value-grouped attribute: sku
        self.assertEqual(set(inv.select_where(sku=Exactly('S1'))),
                         {m['A'], m['B']})
        self.assertEqual(set(inv.select_where(sku=NotExactly('S1'))),
                         {m['C'], m['D'], m['E']})
        self.assertEqual(set(inv.select_where(sku=Greater('S1'))),
                         {m['C'], m['D'], m['E']})
        self.assertEqual(set(inv.select_where(sku=Less('S3'))),
                         {m['A'], m['B'], m['C'], m['D']})
        self.assertEqual(set(inv.select_where(sku=InRange('S1', 'S3'))),
                         {m['A'], m['B'], m['C'], m['D']})
        # a plain value is inferred as Exactly
        self.assertEqual(set(inv.select_where(sku='S1')),
                         set(inv.select_where(sku=Exactly('S1'))))

    def test_no_overlap_empty(self):
        """3.3.2 — two conditions with no overlapping matches return empty."""
        inv, m = _populated()
        self.assertEqual(inv.select_where(sku='S1', qty=Exactly(300.0)), [])

    def test_intersection(self):
        """3.3.3 — multiple conditions return the correct intersection."""
        inv, m = _populated()
        # 1. each condition returns the same set {A, B}
        self.assertEqual(set(inv.select_where(sku='S1')), {m['A'], m['B']})
        self.assertEqual(set(inv.select_where(unit='lbs')), {m['A'], m['B']})
        self.assertEqual(set(inv.select_where(sku='S1', unit='lbs')),
                         {m['A'], m['B']})
        # 2. differing sets with a non-empty overlap -> {D}
        self.assertEqual(set(inv.select_where(sku='S2')), {m['C'], m['D']})
        self.assertEqual(set(inv.select_where(qty=Exactly(300.0))),
                         {m['D'], m['E']})
        self.assertEqual(set(inv.select_where(sku='S2', qty=Exactly(300.0))),
                         {m['D']})

    def test_remove_updates_result(self):
        """3.3.4 — removing an object from a multi-condition result excludes it
        (and it is gone from all groups)."""
        inv, m = _populated()
        self.assertEqual(set(inv.select_where(sku='S1', unit='lbs')),
                         {m['A'], m['B']})
        inv.remove('A')
        self.assertEqual(set(inv.select_where(sku='S1', unit='lbs')), {m['B']})
        self.assertEqual(set(inv.select_where(sku='S1')), {m['B']})
        self.assertEqual(set(inv.select_where(unit='lbs')), {m['B']})
        self.assertEqual(inv.select_where(qty=Exactly(100.0)), [])

    def test_add_updates_result(self):
        """3.3.5 — adding an object meeting multiple conditions includes it."""
        inv, m = _populated()
        f = _cons('F', 'S1', 200.0, 'lbs')
        inv.add(f)
        self.assertEqual(set(inv.select_where(sku='S1', unit='lbs')),
                         {m['A'], m['B'], f})


if __name__ == '__main__':
    unittest.main()
