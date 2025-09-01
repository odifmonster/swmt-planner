#!/usr/bin/env python

import unittest

import datetime as dt

from swmtplanner.support import Quantity
from swmtplanner.support.grouped import Grouped
from swmtplanner.items import greige, GreigeStyle
from swmtplanner.materials import Snapshot, RawMat, RawMatView, ARRIVED

greige.translate.init()
greige.init()

class GreigeRoll(RawMat[str]):

    def __init__(self, id: str, item: GreigeStyle, lbs: float):
        super().__init__('GreigeRoll', id, GRollView(self), item,
                         ARRIVED, dt.datetime.fromtimestamp(0), Quantity(lbs=lbs))
        
    @property
    def size(self):
        lbs = self.qty.lbs
        if self.item.load_rng.is_above(lbs):
            return 'PARTIAL'
        if self.item.load_rng.contains(lbs):
            return 'HALF'
        if self.item.roll_rng.is_above(lbs):
            return 'SMALL'
        if self.item.roll_rng.contains(lbs):
            return 'NORMAL'
        return 'LARGE'

class GRollView(RawMatView[str], attrs=('size',)):

    def __init__(self, link: GreigeRoll):
        super().__init__(link)

class PAInv(Grouped[str, GreigeStyle]):

    def __init__(self):
        super().__init__('item', 'size', 'id')

    def get(self, id: str) -> GRollView:
        return super().get(id)

    def add(self, data: GreigeRoll) -> None:
        return super().add(data)
    
    def remove(self, dview: GRollView, remkey = False) -> GreigeRoll:
        return super().remove(dview, remkey=remkey)

class TestRawMat(unittest.TestCase):

    def setUp(self):
        self.roll1 = GreigeRoll('ROLL01', greige.get_style('AU7529'), 935)
        self.roll2 = GreigeRoll('ROLL02', greige.get_style('AU7529'), 800)
        self.inv = PAInv()

    def test_immut_in_group(self):
        self.inv.add(self.roll1)

        with self.assertRaises(RuntimeError) as cm1:
            self.roll1.allocate(Quantity(lbs=350))

        self.assertEqual(str(cm1.exception), '\'GreigeRoll\' objects cannot be mutated ' + \
                         'while in a group')
        
        with self.assertRaises(RuntimeError) as cm2:
            self.roll1.allocate(Quantity(lbs=350), snapshot=Snapshot())

        self.assertEqual(str(cm2.exception), '\'GreigeRoll\' objects cannot be mutated ' + \
                         'while in a group')
        
    def test_alloc(self):
        piece1 = self.roll1.allocate(Quantity(lbs=350))
        piece2 = self.roll2.allocate(Quantity(lbs=350))

        self.assertAlmostEqual(self.roll1.qty.lbs, 585, places=4)
        self.assertAlmostEqual(self.roll2.qty.lbs, 450, places=4)

        with self.assertRaises(KeyError):
            self.roll1.deallocate(piece2)

        self.roll1.deallocate(piece1)
        self.roll2.deallocate(piece2)

        self.assertAlmostEqual(self.roll1.qty.lbs, 935, places=4)
        self.assertAlmostEqual(self.roll2.qty.lbs, 800, places=4)

    def test_temp_alloc(self):
        snap1 = Snapshot()
        snap2 = Snapshot()
        piece1 = self.roll1.allocate(Quantity(lbs=350), snapshot=snap1)
        piece2 = self.roll1.allocate(Quantity(lbs=375), snapshot=snap2)

        self.assertEqual(self.roll1.qty.lbs, 935)
        self.roll1.snapshot = snap1
        self.assertEqual(self.roll1.qty.lbs, 585)
        self.roll1.snapshot = snap2
        self.assertEqual(self.roll1.qty.lbs, 560)
        self.roll1.snapshot = None
        self.assertEqual(self.roll1.qty.lbs, 935)

        with self.assertRaises(KeyError):
            self.roll1.deallocate(piece2, snapshot=snap1)

        self.roll1.deallocate(piece1, snapshot=snap1)
        self.roll1.snapshot = snap1
        self.assertEqual(self.roll1.qty.lbs, 935)
        self.roll1.snapshot = snap2
        self.assertEqual(self.roll1.qty.lbs, 560)

if __name__ == '__main__':
    unittest.main()