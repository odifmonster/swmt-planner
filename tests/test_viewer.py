#!/usr/bin/env python

import unittest

from swmtplanner.support import HasID
from swmtplanner.support.supers import SwmtBase, setter_like, Viewer

_CTR = 0

class Data(SwmtBase, HasID[int], read_only=('id','value')):

    def __init__(self, value: float):
        globals()['_CTR'] += 1
        SwmtBase.__init__(self, _id=globals()['_CTR'], _value=value)

    @property
    def prefix(self) -> str:
        return 'Data'
    
    def is_negative(self) -> bool:
        return self.value < 0
    
    @setter_like
    def use(self, amount: float) -> None:
        self._value -= amount

class DataView(Viewer[Data], dunders=('hash','eq','repr'), attrs=('prefix','id','value'),
               funcs=('is_negative','use')):
    pass

class TestViewer(unittest.TestCase):

    def test_viewed_attrs(self):
        dat = Data(20)
        datview = DataView(dat)

        self.assertEqual(dat, datview)
        self.assertEqual(datview.value, 20)

    def test_viewed_dunders(self):
        dat = Data(15)
        datview = DataView(dat)

        self.assertEqual(f'Data(id={dat.id})', repr(datview))
        self.assertEqual(hash(datview), hash(dat.id))

    def test_viewed_funcs(self):
        dat1 = Data(20)
        dat2 = Data(-5)
        dview1 = DataView(dat1)
        dview2 = DataView(dat2)

        self.assertFalse(dview1.is_negative())
        self.assertTrue(dview2.is_negative())
    
    def test_view_updates(self):
        dat = Data(20)
        dview = DataView(dat)

        dat.use(10)
        self.assertEqual(dview.value, 10)

        dat.use(20)
        self.assertTrue(dview.is_negative())

if __name__ == '__main__':
    unittest.main()