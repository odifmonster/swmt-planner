#!/usr/bin/env python

import unittest
from dataclasses import FrozenInstanceError

from swmtplanner.core.products import Shade, DyeFormula, Fabric, Greige

DF_1234 = DyeFormula(1234, 'Ebony', Shade.BLACK)
DF_2001 = DyeFormula(2001, 'Fog', Shade.LIGHT1)
G_5429D = Greige('AU5429D', 28, 168, 24.36, 300.0, (), rates={})
FAB = Fabric('FF AU5429D-1234-60', G_5429D, 'AU5429D', DF_1234, 60.0, 1.85,
             jets=('J1', 'J3'))


class TestShade(unittest.TestCase):

    def test_shade_members(self):
        self.assertEqual([m.name for m in Shade],
                         ['LIGHT0', 'LIGHT1', 'MEDIUM', 'SD_BLACK', 'BLACK'])

    def test_shade_values(self):
        self.assertEqual(Shade.BLACK.value, 'BLACK')
        self.assertIs(Shade('LIGHT0'), Shade.LIGHT0)

    def test_shade_identity(self):
        self.assertIsNot(Shade.LIGHT0, Shade.LIGHT1)
        self.assertIsNot(Shade.SD_BLACK, Shade.BLACK)


class TestDyeFormula(unittest.TestCase):

    def test_formula_init(self):
        self.assertEqual(DF_1234.id, 1234)
        self.assertEqual(DF_1234.name, 'Ebony')
        self.assertIs(DF_1234.shade, Shade.BLACK)

    def test_formula_equal_by_id(self):
        other = DyeFormula(1234, 'other', Shade.MEDIUM)
        self.assertEqual(DF_1234, other)
        self.assertEqual(hash(DF_1234), hash(other))
        self.assertEqual(hash(DF_1234), hash(1234))

    def test_formula_unequal_id(self):
        self.assertNotEqual(DF_1234, DyeFormula(1235, 'Ebony', Shade.BLACK))

    def test_formula_hashable(self):
        s = {DF_1234, DyeFormula(1234, 'x', Shade.LIGHT0), DF_2001}
        self.assertEqual(len(s), 2)

    def test_formula_frozen(self):
        with self.assertRaises(FrozenInstanceError):
            DF_1234.shade = Shade.MEDIUM


class TestFabric(unittest.TestCase):

    def test_fabric_init(self):
        self.assertEqual(FAB.id, 'FF AU5429D-1234-60')
        self.assertIs(FAB.greige_style, G_5429D)
        self.assertEqual(FAB.master_style, 'AU5429D')
        self.assertIs(FAB.color, DF_1234)
        self.assertEqual(FAB.width, 60.0)
        self.assertEqual(FAB.yld, 1.85)
        self.assertEqual(FAB.jets, ('J1', 'J3'))

    def test_fabric_jet_present(self):
        self.assertTrue(FAB.can_run_on_jet('J1'))
        self.assertTrue(FAB.can_run_on_jet('J3'))

    def test_fabric_jet_absent(self):
        self.assertFalse(FAB.can_run_on_jet('J2'))

    def test_fabric_jet_case(self):
        self.assertFalse(FAB.can_run_on_jet('j1'))

    def test_fabric_no_jets(self):
        f = Fabric('FF X-1-1', G_5429D, 'X', DF_1234, 1.0, 1.0, jets=())
        self.assertFalse(f.can_run_on_jet('J1'))

    def test_fabric_equal_by_id(self):
        other = Fabric('FF AU5429D-1234-60', G_5429D, 'other', DF_2001, 0.0, 0.0, jets=())
        self.assertEqual(FAB, other)
        self.assertEqual(hash(FAB), hash(other))

    def test_fabric_unequal_id(self):
        other = Fabric('FF AU5429D-2001-60', G_5429D, 'AU5429D', DF_2001, 60.0, 1.85,
                       jets=('J1', 'J3'))
        self.assertNotEqual(FAB, other)

    def test_fabric_unequal_other_class(self):
        self.assertNotEqual(FAB, DF_1234)
        self.assertNotEqual(FAB, G_5429D)

    def test_fabric_hashable(self):
        s = {FAB, Fabric('FF AU5429D-1234-60', G_5429D, 'AU5429D', DF_1234, 60.0, 1.85, jets=())}
        self.assertEqual(len(s), 1)

    def test_fabric_frozen(self):
        with self.assertRaises(FrozenInstanceError):
            FAB.width = 54.0


if __name__ == '__main__':
    unittest.main()
