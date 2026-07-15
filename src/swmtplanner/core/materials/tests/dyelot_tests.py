#!/usr/bin/env python

import unittest
from datetime import datetime

from swmtplanner.core.materials import GreigeRoll, DyeLot
from swmtplanner.core.product.greige import Greige, BeamConfig
from swmtplanner.core.product.fabric import Fabric

_BC = BeamConfig(beamset='B', pct=1.0)
_G700 = Greige(id='G', tgt_wt=700.0, safety=0.0, pattern='A',
               top=_BC, bottom=_BC, alt_names=[])   # single_target = 350

_D1 = datetime(2026, 7, 1)
_D2 = datetime(2026, 7, 2)
_D3 = datetime(2026, 7, 3)


def _roll(id, qty, sku='S1', plant='P1', avail=_D1):
    return GreigeRoll(id=id, sku=sku, avail_date=avail, qty=qty, plant=plant,
                      variant='V', yarn_merge=1, greige=_G700)


def _fabric(fid, greige, yld_pct=0.9):
    # yds_per_lb = 36 * 16 / (oz_sq_yd * width) * yld_pct = 0.96 * yld_pct
    return Fabric(id=fid, ply1_parts=(), greige=greige, style='STY', width=60.0,
                  oz_sq_yd=10.0, yld_pct=yld_pct, name='N', number=1,
                  shade_rating=1, jets=[])


def _ids(lot):
    return sorted(r.id for r in lot)


class TestDyeLotConstruction(unittest.TestCase):

    def test_empty(self):
        """3.1.1 — empty list gives a DyeLot with default values."""
        lot = DyeLot([])
        self.assertIsNone(lot.greige)
        self.assertIsNone(lot.plant)
        self.assertIsNone(lot.avail_date)
        self.assertEqual(lot.total_lbs, 0)
        self.assertEqual(lot.n_ports, 0)
        self.assertEqual(lot.avg_port_wt, 0)

    def test_single(self):
        """3.1.2 — a single-roll lot shares all attributes with that roll."""
        r = _roll('A', 350.0)
        lot = DyeLot([r])
        self.assertEqual(lot.greige, r.sku)
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
        self.assertEqual(lot.greige, r.sku)
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
        self.assertEqual(lot.greige, r.sku)
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
        self.assertIsNone(lot.greige)
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
        self.assertEqual(lot.greige, 'S2')
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

    def test_add_fabric_set_wrong_greige(self):
        """3.2.9 — fabric set, empty lot: adding a roll whose sku != fabric.greige
        raises."""
        lot = DyeLot([])
        lot.fabric = _fabric('F1', greige='S1')
        with self.assertRaises(ValueError):
            lot.add(_roll('A', 350.0, sku='S2'))

    def test_add_fabric_set_matching_greige(self):
        """3.2.10 — fabric set, empty lot: adding a roll whose sku matches
        fabric.greige is accepted."""
        lot = DyeLot([])
        lot.fabric = _fabric('F1', greige='S1')
        lot.add(_roll('A', 350.0, sku='S1'))
        self.assertEqual(lot.greige, 'S1')


class TestDyeLotFabric(unittest.TestCase):

    def test_set_on_empty(self):
        """3.3.1 — fabric can be set to any style on an empty lot."""
        lot = DyeLot([])
        f = _fabric('F1', greige='ANY')
        lot.fabric = f
        self.assertIs(lot.fabric, f)

    def test_set_incompatible_with_rolls(self):
        """3.3.2 — setting a fabric whose greige mismatches the lot's rolls
        raises."""
        lot = DyeLot([_roll('A', 350.0, sku='S1')])
        with self.assertRaises(ValueError):
            lot.fabric = _fabric('F1', greige='S2')

    def test_change_fabric_updates_total_yds(self):
        """3.3.3 — changing to a different same-greige fabric updates
        total_yds."""
        lot = DyeLot([_roll('A', 350.0, sku='S1')])
        f1 = _fabric('F1', greige='S1', yld_pct=0.9)
        lot.fabric = f1
        self.assertAlmostEqual(lot.total_yds, lot.total_lbs * f1.yds_per_lb)
        f2 = _fabric('F2', greige='S1', yld_pct=0.95)
        lot.fabric = f2
        self.assertIs(lot.fabric, f2)
        self.assertNotAlmostEqual(f1.yds_per_lb, f2.yds_per_lb)
        self.assertAlmostEqual(lot.total_yds, lot.total_lbs * f2.yds_per_lb)


if __name__ == '__main__':
    unittest.main()
