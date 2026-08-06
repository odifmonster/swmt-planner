#!/usr/bin/env python

import unittest

from swmtplanner.core.product import Fabric
from swmtplanner.core.demand.requirement import Requirement


class FabReq(Requirement[Fabric]):
    """Concrete Requirement over a Fabric, keyed simply by the fabric's id."""

    @property
    def id(self) -> str:
        return self.item.id


def _fabric(id: str = 'F1') -> Fabric:
    return Fabric(id=id, ply1_parts=(), greige='G', style='S', width=60.0,
                  oz_sq_yd=10.0, yld_pct=0.9, name='N', number=1,
                  shade_rating=0, jets={})


class TestRequirement(unittest.TestCase):

    def test_all_zeros(self):
        """1.1.1 — empty requirement (init_qty 0, covered_on_hand 0): remaining
        starts at 0 and stays 0 as allocated_qty increases. Also sanity-checks
        that FabReq exposes item / init_qty / covered_on_hand / id and that
        allocated_qty starts at 0."""
        f = _fabric('F1')
        r = FabReq(f, 0.0, 0.0)
        self.assertIs(r.item, f)
        self.assertEqual(r.init_qty, 0.0)
        self.assertEqual(r.covered_on_hand, 0.0)
        self.assertEqual(r.allocated_qty, 0.0)
        self.assertEqual(r.id, 'F1')
        self.assertEqual(r.remaining, 0.0)
        r.allocated_qty = 50.0
        self.assertEqual(r.remaining, 0.0)
        r.allocated_qty = 100.0
        self.assertEqual(r.remaining, 0.0)

    def test_zero_init_positive_on_hand(self):
        """1.1.2 — init_qty 0, covered_on_hand > 0: remaining starts at 0 and
        stays 0 as allocated_qty increases."""
        r = FabReq(_fabric(), 0.0, 30.0)
        self.assertEqual(r.remaining, 0.0)
        r.allocated_qty = 10.0
        self.assertEqual(r.remaining, 0.0)
        r.allocated_qty = 100.0
        self.assertEqual(r.remaining, 0.0)

    def test_positive_init_zero_on_hand(self):
        """1.1.3 — init_qty > 0, covered_on_hand 0: remaining starts at the full
        init_qty and goes down by the allocated amount, with a floor of 0."""
        r = FabReq(_fabric(), 100.0, 0.0)
        self.assertEqual(r.remaining, 100.0)
        r.allocated_qty = 30.0
        self.assertEqual(r.remaining, 70.0)
        r.allocated_qty = 100.0
        self.assertEqual(r.remaining, 0.0)
        r.allocated_qty = 150.0
        self.assertEqual(r.remaining, 0.0)

    def test_positive_init_on_hand_below_init(self):
        """1.1.4 — init_qty > 0, 0 < covered_on_hand < init_qty: remaining starts
        at init_qty - covered_on_hand and goes down by the allocated amount
        (floor of 0)."""
        r = FabReq(_fabric(), 100.0, 40.0)
        self.assertEqual(r.remaining, 60.0)
        r.allocated_qty = 20.0
        self.assertEqual(r.remaining, 40.0)
        r.allocated_qty = 60.0
        self.assertEqual(r.remaining, 0.0)
        r.allocated_qty = 100.0
        self.assertEqual(r.remaining, 0.0)

    def test_positive_init_on_hand_above_init(self):
        """1.1.5 — init_qty > 0, covered_on_hand > init_qty: remaining starts at 0
        and stays 0 as allocated_qty increases."""
        r = FabReq(_fabric(), 100.0, 150.0)
        self.assertEqual(r.remaining, 0.0)
        r.allocated_qty = 10.0
        self.assertEqual(r.remaining, 0.0)
        r.allocated_qty = 100.0
        self.assertEqual(r.remaining, 0.0)


if __name__ == '__main__':
    unittest.main()
