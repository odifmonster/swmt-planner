#!/usr/bin/env python

import unittest
from datetime import datetime

from swmtplanner.core.materials import GreigeRoll
from swmtplanner.core.materials.rawmat import SMALL, STANDARD, LARGE
from swmtplanner.core.product.greige import Greige, BeamConfig

_BC = BeamConfig(beamset='B', pct=1.0)


def _greige(tgt_wt: float) -> Greige:
    return Greige(id='G', tgt_wt=tgt_wt, safety=0.0, pattern='A',
                  top=_BC, bottom=_BC, alt_names=[])


def _roll(qty, greige, id='R1', sku='SKU1', plant='Fairystone',
          variant='V1', yarn_merge=5, avail=None):
    return GreigeRoll(id=id, sku=sku, avail_date=avail or datetime(2026, 7, 1),
                      qty=qty, plant=plant, variant=variant,
                      yarn_merge=yarn_merge, greige=greige)


class TestGreigeRollConstruction(unittest.TestCase):

    def test_construction(self):
        """2.1.1 — non-computed properties are correct."""
        d = datetime(2026, 7, 1, 8, 0)
        g = _greige(700.0)
        r = _roll(qty=350.0, greige=g, id='R1', sku='SKU1', plant='Fairystone',
                  variant='V1', yarn_merge=5, avail=d)
        self.assertEqual(r.id, 'R1')
        self.assertEqual(r.sku, 'SKU1')
        self.assertEqual(r.avail_date, d)
        self.assertEqual(r.qty, 350.0)
        self.assertEqual(r.unit, 'lbs')
        self.assertEqual(r.plant, 'Fairystone')
        self.assertEqual(r.variant, 'V1')
        self.assertEqual(r.yarn_merge, 5)
        self.assertIs(r.greige, g)

    def test_single_target(self):
        """2.1.2 — single_target for double-port (>400), single-port (<=400), and
        no greige (defaults to DEFAULT_ROLL_WT = 700)."""
        self.assertAlmostEqual(_roll(350.0, _greige(700.0)).single_target, 350.0)
        self.assertAlmostEqual(_roll(300.0, _greige(300.0)).single_target, 300.0)
        self.assertAlmostEqual(_roll(350.0, None).single_target, 350.0)

    def test_computed_matrix(self):
        """2.1.3 — n_ports, avg_port_wt, and size across 1-4 ports for all three
        sizes (single_target = 350)."""
        g = _greige(700.0)   # single_target = 350
        # (qty, expected n_ports, expected avg_port_wt, expected size)
        cases = [
            (300.0, 1, 300.0, SMALL),
            (600.0, 2, 300.0, SMALL),
            (900.0, 3, 300.0, SMALL),
            (1250.0, 4, 312.5, SMALL),
            (350.0, 1, 350.0, STANDARD),
            (700.0, 2, 350.0, STANDARD),
            (1050.0, 3, 350.0, STANDARD),
            (1400.0, 4, 350.0, STANDARD),
            (400.0, 1, 400.0, LARGE),
            (800.0, 2, 400.0, LARGE),
            (1200.0, 3, 400.0, LARGE),
            (1550.0, 4, 387.5, LARGE),
        ]
        for qty, n_ports, avg, size in cases:
            r = _roll(qty, g)
            self.assertEqual(r.n_ports, n_ports, f'n_ports for qty={qty}')
            self.assertAlmostEqual(r.avg_port_wt, avg, msg=f'avg for qty={qty}')
            self.assertEqual(r.size, size, f'size for qty={qty}')


class TestGreigeRollSplit(unittest.TestCase):

    def test_invalid_weights(self):
        """2.2.1 — split raises when lbs1 + lbs2 != qty."""
        r = _roll(700.0, _greige(700.0))
        with self.assertRaises(ValueError):
            r.split(300.0, 300.0)

    def test_new_rolls(self):
        """2.2.2 — split produces correct ids/qtys; other properties inherited."""
        d = datetime(2026, 7, 1, 8, 0)
        g = _greige(700.0)
        r = _roll(700.0, g, id='R1', sku='SKU1', plant='Fairystone',
                  variant='V1', yarn_merge=5, avail=d)
        first, second = r.split(300.0, 400.0)
        self.assertEqual((first.id, first.qty), ('R1A', 300.0))
        self.assertEqual((second.id, second.qty), ('R1B', 400.0))
        for child in (first, second):
            self.assertEqual(child.sku, 'SKU1')
            self.assertEqual(child.plant, 'Fairystone')
            self.assertEqual(child.variant, 'V1')
            self.assertEqual(child.yarn_merge, 5)
            self.assertEqual(child.avail_date, d)
            self.assertEqual(child.unit, 'lbs')
            self.assertIs(child.greige, g)

    def test_recompute_scenarios(self):
        """2.2.3 — split recompute scenarios (single_target = 350)."""
        g = _greige(700.0)

        # 1. unbalanced: big keeps parent's n_ports (2) but changes size;
        #    partial is less than one port's worth (< 350 lbs).
        parent = _roll(700.0, g)   # 2 ports, STANDARD
        big, partial = parent.split(600.0, 100.0)
        self.assertEqual(big.n_ports, parent.n_ports)   # both 2
        self.assertNotEqual(big.size, parent.size)
        self.assertEqual(big.size, SMALL)
        self.assertEqual(partial.n_ports, 1)
        self.assertLess(partial.qty, 350.0)

        # 2. balanced split of a 2-port roll -> two new rolls of the same size
        a, b = _roll(700.0, g).split(350.0, 350.0)
        self.assertEqual(a.size, b.size)
        self.assertEqual((a.n_ports, b.n_ports), (1, 1))
        self.assertEqual(a.size, STANDARD)

        # 3. unbalanced split of a LARGE 2-port roll -> LARGE 1-port + STANDARD 1-port
        large2 = _roll(800.0, g)
        self.assertEqual((large2.n_ports, large2.size), (2, LARGE))
        lg, std = large2.split(450.0, 350.0)
        self.assertEqual((lg.n_ports, lg.size), (1, LARGE))
        self.assertEqual((std.n_ports, std.size), (1, STANDARD))


class TestGreigeRollCombine(unittest.TestCase):

    def test_mismatched_rolls(self):
        """2.3.1 — combine raises on differing sku or plant."""
        g = _greige(700.0)
        a = _roll(350.0, g, id='A', sku='S1', plant='P1')
        with self.assertRaises(ValueError):
            a.combine(_roll(350.0, g, id='B', sku='S2', plant='P1'))
        with self.assertRaises(ValueError):
            a.combine(_roll(350.0, g, id='C', sku='S1', plant='P2'))

    def test_variant(self):
        """2.3.2 — combined variant kept when same, joined with '/' when
        different."""
        g = _greige(700.0)
        same = _roll(350.0, g, id='A', variant='V1').combine(
            _roll(350.0, g, id='B', variant='V1'))
        self.assertEqual(same.variant, 'V1')
        mixed = _roll(350.0, g, id='A', variant='V1').combine(
            _roll(350.0, g, id='B', variant='V2'))
        self.assertEqual(mixed.variant, 'V1/V2')

    def test_yarn_merge(self):
        """2.3.3 — yarn_merge kept when same, -1 when different."""
        g = _greige(700.0)
        same = _roll(350.0, g, id='A', yarn_merge=5).combine(
            _roll(350.0, g, id='B', yarn_merge=5))
        self.assertEqual(same.yarn_merge, 5)
        diff = _roll(350.0, g, id='A', yarn_merge=5).combine(
            _roll(350.0, g, id='B', yarn_merge=7))
        self.assertEqual(diff.yarn_merge, -1)

    def test_result_scenarios(self):
        """2.3.4 — combine result scenarios (single_target = 350)."""
        g = _greige(700.0)

        # 1. two partials -> STANDARD 1-port
        a = _roll(200.0, g, id='A')
        b = _roll(150.0, g, id='B')
        self.assertEqual((a.n_ports, b.n_ports), (1, 1))
        r1 = a.combine(b)
        self.assertEqual(r1.id, 'A/B')
        self.assertEqual(r1.qty, 350.0)
        self.assertEqual((r1.n_ports, r1.size), (1, STANDARD))
        self.assertAlmostEqual(r1.avg_port_wt, 350.0)

        # 2. one SMALL + one LARGE -> STANDARD 4-port
        small = _roll(600.0, g, id='A')   # 2 ports, SMALL
        large = _roll(800.0, g, id='B')   # 2 ports, LARGE
        self.assertEqual((small.size, large.size), (SMALL, LARGE))
        r2 = small.combine(large)
        self.assertEqual(r2.qty, 1400.0)
        self.assertEqual((r2.n_ports, r2.size), (4, STANDARD))
        self.assertAlmostEqual(r2.avg_port_wt, 350.0)

        # 3. two LARGE 1-port -> STANDARD 3-port
        l1 = _roll(500.0, g, id='A')
        l2 = _roll(500.0, g, id='B')
        self.assertEqual((l1.size, l1.n_ports), (LARGE, 1))
        r3 = l1.combine(l2)
        self.assertEqual(r3.qty, 1000.0)
        self.assertEqual((r3.n_ports, r3.size), (3, STANDARD))
        self.assertAlmostEqual(r3.avg_port_wt, 1000.0 / 3)


if __name__ == '__main__':
    unittest.main()
