#!/usr/bin/env python

import unittest

from swmtplanner.core.product.fabric import (
    BLACK, Color, Fabric,
    load_ply1_translation, ply1_to_fabric,
)


def _fabric(id: str, ply1_parts: tuple[str, ...],
            jets: list[str] = ['J1']) -> Fabric:
    return Fabric(id=id, ply1_parts=ply1_parts, greige='G1', style='STY',
                  width=60.0, oz_sq_yd=10.0, yld_pct=0.9,
                  name='Navy', number=540, shade_rating=BLACK, jets=jets)


class TestFabricConstruction(unittest.TestCase):

    def test_construction(self):
        """2.1.1 — the whole Fabric is constructed properly: every read-only
        property is exposed correctly, including the color built from
        name/number/shade_rating."""
        f = Fabric(id='F1', ply1_parts=('P1', 'P2'), greige='G1', style='STY',
                   width=60.0, oz_sq_yd=10.0, yld_pct=0.9,
                   name='Navy', number=540, shade_rating=BLACK, jets=['J1'])
        self.assertEqual(f.id, 'F1')
        self.assertEqual(f.ply1_parts, ('P1', 'P2'))
        self.assertEqual(f.greige, 'G1')
        self.assertEqual(f.style, 'STY')
        self.assertEqual(f.width, 60.0)
        self.assertEqual(f.color, Color(name='Navy', number=540,
                                        shade_rating=BLACK))

    def test_yds_per_lb(self):
        """2.1.2 — yds_per_lb = 36 * 16 / (oz_sq_yd * width) * yld_pct, across a
        couple of cases."""
        f1 = Fabric(id='F1', ply1_parts=(), greige='G', style='S',
                    width=60.0, oz_sq_yd=10.0, yld_pct=0.9,
                    name='C', number=1, shade_rating=BLACK, jets=[])
        self.assertAlmostEqual(f1.yds_per_lb, 36 * 16 / (10.0 * 60.0) * 0.9)

        f2 = Fabric(id='F2', ply1_parts=(), greige='G', style='S',
                    width=54.0, oz_sq_yd=8.0, yld_pct=1.0,
                    name='C', number=1, shade_rating=BLACK, jets=[])
        self.assertAlmostEqual(f2.yds_per_lb, 36 * 16 / (8.0 * 54.0) * 1.0)

    def test_can_run_on_jet(self):
        """2.1.3 — can_run_on_jet returns True for jets provided and False for
        jets not provided."""
        f = _fabric('F1', (), jets=['J1', 'J2'])
        self.assertTrue(f.can_run_on_jet('J1'))
        self.assertTrue(f.can_run_on_jet('J2'))
        self.assertFalse(f.can_run_on_jet('J9'))


class TestPly1Translation(unittest.TestCase):

    def test_load_one_to_one(self):
        """2.2.1 — load_ply1_translation works on a one-to-one table."""
        f1 = _fabric('F1', ('P1',))
        f2 = _fabric('F2', ('P2',))
        load_ply1_translation([f1, f2])
        self.assertEqual(ply1_to_fabric('P1'), f1)
        self.assertEqual(ply1_to_fabric('P2'), f2)

    def test_load_many_to_one(self):
        """2.2.2 — load_ply1_translation works on a many-to-one table."""
        f = _fabric('F1', ('P1', 'P2', 'P3'))
        load_ply1_translation([f])
        self.assertEqual(ply1_to_fabric('P1'), f)
        self.assertEqual(ply1_to_fabric('P2'), f)
        self.assertEqual(ply1_to_fabric('P3'), f)

    def test_to_fabric(self):
        """2.2.3 — ply1_to_fabric returns the expected Fabric object."""
        f = _fabric('F1', ('P1',))
        load_ply1_translation([f])
        self.assertIs(ply1_to_fabric('P1'), f)

    def test_to_fabric_unknown(self):
        """2.2.4 — ply1_to_fabric returns None on an unknown ply1 part."""
        f = _fabric('F1', ('P1',))
        load_ply1_translation([f])
        self.assertIsNone(ply1_to_fabric('NOPE'))


if __name__ == '__main__':
    unittest.main()
