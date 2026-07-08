#!/usr/bin/env python

import unittest
from datetime import datetime

from swmtplanner.core.materials import GreigeRoll, DyeLot
from swmtplanner.core.product.greige import Greige, BeamConfig

_BC = BeamConfig(beamset='B', pct=1.0)
_G700 = Greige(id='G', tgt_wt=700.0, safety=0.0, pattern='A',
               top=_BC, bottom=_BC, alt_names=[])   # single_target = 350

_D1 = datetime(2026, 7, 1)
_D2 = datetime(2026, 7, 2)
_D3 = datetime(2026, 7, 3)


def _roll(id, qty, sku='S1', plant='P1', avail=_D1):
    return GreigeRoll(id=id, sku=sku, avail_date=avail, qty=qty, plant=plant,
                      variant='V', yarn_merge=1, greige=_G700)


def _ids(lot):
    return sorted(r.id for r in lot)


class TestDyeLotConstruction(unittest.TestCase):

    def test_empty(self):
        """3.1.1 — empty list gives a DyeLot with default values."""
        lot = DyeLot([])
        self.assertIsNone(lot.sku)
        self.assertIsNone(lot.plant)
        self.assertIsNone(lot.avail_date)
        self.assertEqual(lot.total_lbs, 0)
        self.assertEqual(lot.n_ports, 0)
        self.assertEqual(lot.avg_port_wt, 0)

    def test_single(self):
        """3.1.2 — a single-roll lot shares all attributes with that roll."""
        r = _roll('A', 350.0)
        lot = DyeLot([r])
        self.assertEqual(lot.sku, r.sku)
        self.assertEqual(lot.plant, r.plant)
        self.assertEqual(lot.avail_date, r.avail_date)
        self.assertEqual(lot.total_lbs, r.qty)
        self.assertEqual(lot.n_ports, r.n_ports)
        self.assertAlmostEqual(lot.avg_port_wt, r.avg_port_wt)

    def test_mismatched(self):
        """3.1.3 — mismatched plants or skus raise."""
        with self.assertRaises(ValueError):
            DyeLot([_roll('A', 350.0, sku='S1'), _roll('B', 350.0, sku='S2')])
        with self.assertRaises(ValueError):
            DyeLot([_roll('A', 350.0, plant='P1'), _roll('B', 350.0, plant='P2')])

    def test_identical(self):
        """3.1.4 — identical rolls: properties match except summed total_lbs and
        n_ports; avg_port_wt stays the rolls' value."""
        r = _roll('A', 350.0)
        lot = DyeLot([_roll('A', 350.0), _roll('B', 350.0)])
        self.assertEqual(lot.sku, r.sku)
        self.assertEqual(lot.plant, r.plant)
        self.assertEqual(lot.avail_date, r.avail_date)
        self.assertEqual(lot.total_lbs, 2 * r.qty)
        self.assertEqual(lot.n_ports, 2 * r.n_ports)
        self.assertAlmostEqual(lot.avg_port_wt, r.avg_port_wt)

    def test_differing(self):
        """3.1.5 — differing (but compatible) rolls compute correct aggregates."""
        lot = DyeLot([_roll('A', 300.0, avail=_D1),   # 1 port
                      _roll('B', 800.0, avail=_D2)])   # 2 ports
        self.assertEqual(lot.avail_date, _D2)          # max
        self.assertEqual(lot.total_lbs, 1100.0)        # sum
        self.assertEqual(lot.n_ports, 3)               # 1 + 2
        self.assertAlmostEqual(lot.avg_port_wt, 1100.0 / 3)


class TestDyeLotAddRemove(unittest.TestCase):

    def test_add_to_empty(self):
        """3.2.1 — adding to an empty lot sets its properties to the roll's."""
        lot = DyeLot([])
        r = _roll('A', 350.0)
        lot.add(r)
        self.assertEqual(lot.sku, r.sku)
        self.assertEqual(lot.plant, r.plant)
        self.assertEqual(lot.avail_date, r.avail_date)
        self.assertEqual(lot.total_lbs, r.qty)
        self.assertEqual(lot.n_ports, r.n_ports)

    def test_add_mismatched(self):
        """3.2.2 — adding a mismatched roll to a non-empty lot raises."""
        lot = DyeLot([_roll('A', 350.0, sku='S1', plant='P1')])
        with self.assertRaises(ValueError):
            lot.add(_roll('B', 350.0, sku='S2', plant='P1'))
        with self.assertRaises(ValueError):
            lot.add(_roll('C', 350.0, sku='S1', plant='P2'))

    def test_add_valid(self):
        """3.2.3 — adding a valid roll updates the aggregate properties."""
        lot = DyeLot([_roll('A', 300.0, avail=_D1)])   # 1 port
        lot.add(_roll('B', 800.0, avail=_D2))          # 2 ports
        self.assertEqual(lot.avail_date, _D2)
        self.assertEqual(lot.total_lbs, 1100.0)
        self.assertEqual(lot.n_ports, 3)
        self.assertAlmostEqual(lot.avg_port_wt, 1100.0 / 3)

    def test_remove_last(self):
        """3.2.4 — removing the last roll returns properties to defaults."""
        lot = DyeLot([_roll('A', 350.0)])
        lot.remove('A')
        self.assertIsNone(lot.sku)
        self.assertIsNone(lot.plant)
        self.assertIsNone(lot.avail_date)
        self.assertEqual(lot.total_lbs, 0)
        self.assertEqual(lot.n_ports, 0)
        self.assertEqual(lot.avg_port_wt, 0)

    def test_remove_last_then_add_different(self):
        """3.2.5 — removing the last roll then adding one with a different
        plant/sku changes the lot's plant/sku."""
        lot = DyeLot([_roll('A', 350.0, sku='S1', plant='P1')])
        lot.remove('A')
        lot.add(_roll('B', 350.0, sku='S2', plant='P2'))
        self.assertEqual(lot.sku, 'S2')
        self.assertEqual(lot.plant, 'P2')

    def test_remove_from_many(self):
        """3.2.6 — removing a roll from a lot of >= 2 updates the aggregates."""
        lot = DyeLot([_roll('A', 300.0, avail=_D1),    # 1 port
                      _roll('B', 800.0, avail=_D3),    # 2 ports (latest date)
                      _roll('C', 350.0, avail=_D2)])   # 1 port
        lot.remove('B')
        self.assertEqual(lot.avail_date, _D2)          # max of remaining
        self.assertEqual(lot.total_lbs, 650.0)         # 300 + 350
        self.assertEqual(lot.n_ports, 2)               # 1 + 1
        self.assertAlmostEqual(lot.avg_port_wt, 325.0)

    def test_removed_roll_returned(self):
        """3.2.7 — the correct roll is returned on removal."""
        b = _roll('B', 800.0)
        lot = DyeLot([_roll('A', 300.0), b])
        self.assertIs(lot.remove('B'), b)

    def test_iteration(self):
        """3.2.8 — add / remove are reflected in __iter__."""
        lot = DyeLot([_roll('A', 300.0), _roll('B', 350.0)])
        self.assertEqual(_ids(lot), ['A', 'B'])
        lot.add(_roll('C', 300.0))
        self.assertEqual(_ids(lot), ['A', 'B', 'C'])
        lot.remove('A')
        self.assertEqual(_ids(lot), ['B', 'C'])


if __name__ == '__main__':
    unittest.main()
