#!/usr/bin/env python

import unittest
from datetime import datetime

from swmtplanner.core.materials import GreigeRoll
from swmtplanner.core.materials.rawmat import STANDARD
from swmtplanner.core.materials.inventory import GreigeInv
from swmtplanner.core.product.greige import Greige, BeamConfig

D1 = datetime(2026, 7, 1)
_BC = BeamConfig(beamset='B', pct=1.0)
G700 = Greige(id='G', tgt_wt=700.0, safety=0.0, pattern='A',
              top=_BC, bottom=_BC, alt_names=[])   # single_target 350


def _roll(id, qty, sku, plant='FS'):
    # greige=None -> default 700 -> single_target 350
    return GreigeRoll(id=id, sku=sku, avail_date=D1, qty=qty, plant=plant,
                      variant='V', yarn_merge=1, greige=None)


class TestTransformRolls(unittest.TestCase):

    def test_direct_combinations(self):
        """4.2.1.1 — small+large rolls combine (no trim) into standard 2/3/4-port
        rolls."""
        inv = GreigeInv()
        inv.add(_roll('a', 300.0, 'S2'))   # SMALL 1-port
        inv.add(_roll('b', 400.0, 'S2'))   # LARGE 1-port  -> 700, standard 2-port
        inv.add(_roll('c', 500.0, 'S3'))   # LARGE 1-port
        inv.add(_roll('d', 500.0, 'S3'))   # LARGE 1-port  -> 1000, standard 3-port
        inv.add(_roll('e', 600.0, 'S4'))   # SMALL 2-port
        inv.add(_roll('f', 800.0, 'S4'))   # LARGE 2-port  -> 1400, standard 4-port
        inv.transform_rolls()
        for sku, ports in (('S2', 2), ('S3', 3), ('S4', 4)):
            rolls = inv.select_where(sku=sku)
            self.assertEqual(len(rolls), 1)
            self.assertEqual(rolls[0].size, STANDARD)
            self.assertEqual(rolls[0].n_ports, ports)

    def test_exact_target_trim(self):
        """4.2.1.2 — a combination trimmed (<= MAX_TRIM_LBS) to the exact target
        (378 -> trim 28 -> 350)."""
        inv = GreigeInv()
        inv.add(_roll('a', 200.0, 'S5'))
        inv.add(_roll('b', 178.0, 'S5'))
        inv.transform_rolls()
        rolls = inv.select_where(sku='S5')
        self.assertEqual(len(rolls), 1)
        self.assertEqual(rolls[0].size, STANDARD)
        self.assertAlmostEqual(rolls[0].qty, 350.0)

    def test_full_trim(self):
        """4.2.1.3 — a combination trimmed a full 30 lbs into range but short of
        the exact target (400 -> trim 30 -> 370)."""
        inv = GreigeInv()
        inv.add(_roll('a', 250.0, 'S6'))
        inv.add(_roll('b', 150.0, 'S6'))
        inv.transform_rolls()
        rolls = inv.select_where(sku='S6')
        self.assertEqual(len(rolls), 1)
        self.assertEqual(rolls[0].size, STANDARD)
        self.assertAlmostEqual(rolls[0].qty, 370.0)

    def test_all_results_standard(self):
        """4.2.1.4 — every combination result is standard after transform_rolls."""
        inv = GreigeInv()
        inv.add(_roll('a', 300.0, 'S2'))
        inv.add(_roll('b', 400.0, 'S2'))
        inv.add(_roll('c', 250.0, 'S6'))
        inv.add(_roll('d', 150.0, 'S6'))
        inv.transform_rolls()
        combined = [r for r in inv.select_where() if '/' in r.id]
        self.assertTrue(combined)
        for r in combined:
            self.assertEqual(r.size, STANDARD)


class TestCreateRoll(unittest.TestCase):

    def test_properties(self):
        """4.2.2.1 — created roll carries the passed properties (+ variant=sku,
        yarn_merge=-1, unit='lbs')."""
        inv = GreigeInv()
        r = inv.create_roll(sku='SKU1', avail_date=D1, qty=350.0,
                            plant='Fairystone', greige=G700)
        self.assertEqual(r.sku, 'SKU1')
        self.assertEqual(r.avail_date, D1)
        self.assertEqual(r.qty, 350.0)
        self.assertEqual(r.plant, 'Fairystone')
        self.assertIs(r.greige, G700)
        self.assertEqual(r.variant, 'SKU1')
        self.assertEqual(r.yarn_merge, -1)
        self.assertEqual(r.unit, 'lbs')

    def test_id_built(self):
        """4.2.2.2 — id is <plant prefix>NEW-<counter>."""
        inv = GreigeInv()
        fs = inv.create_roll('SKU1', D1, 350.0, 'Fairystone', G700)
        wv = inv.create_roll('SKU1', D1, 350.0, 'Whiteville', G700)
        self.assertEqual(fs.id, 'FSNEW-0')
        self.assertEqual(wv.id, 'WVNEW-1')

    def test_counter_increments(self):
        """4.2.2.3 — successive calls produce distinct, incrementing ids."""
        inv = GreigeInv()
        ids = [inv.create_roll('S', D1, 350.0, 'Fairystone', G700).id
               for _ in range(3)]
        self.assertEqual(ids, ['FSNEW-0', 'FSNEW-1', 'FSNEW-2'])


if __name__ == '__main__':
    unittest.main()
