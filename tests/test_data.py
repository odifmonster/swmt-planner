#!/usr/bin/env python

import unittest

import random

from swmtplanner.support import setter_like
from swmtplanner.support.grouped import Data, DataView

def random_str_id(length: int = 8):
    digits = [str(i) for i in range(10)]
    return ''.join([random.choice(digits) for _ in range(length)])

class Roll(Data[str], mut_in_group=False, read_only=('item',),
           priv=('init_qty','allocs')):
    
    def __init__(self, id: str, item: str, qty: float):
        super().__init__('Roll', id, RollView(self), _item=item, _init_qty=qty,
                         _allocs=[])
        
    def __str__(self):
        return f'Roll(id={repr(self.id)}, item={repr(self.item)}, ' + \
            f'wt={self.qty:.2f} lbs)'
    
    @property
    def qty(self) -> float:
        return self._init_qty - sum(self._allocs)
    
    @setter_like
    def allocate(self, amount: float) -> None:
        self._allocs.append(amount)

class RollView(DataView[str], dunders=('str',), attrs=('item','qty')):
    pass

class TestData(unittest.TestCase):

    def test_init_attrs(self):
        roll = Roll('ROLL01', 'GREIGE01', 700)
        rview = roll.view()

        self.assertEqual(roll.prefix, 'Roll')
        self.assertEqual(roll.id, 'ROLL01')
        self.assertEqual(roll, rview)

        self.assertEqual(roll.item, 'GREIGE01')
        self.assertEqual(roll.qty, 700)

    def test_view_dunders(self):
        roll = Roll('ROLL01', 'GREIGE01', 700)
        self.assertEqual(hash('ROLL01'), hash(roll.view()))
        self.assertEqual(str(roll.view()), 'Roll(id=\'ROLL01\', item=\'GREIGE01\'' + \
                         ', wt=700.00 lbs)')
    
    def test_in_group(self):
        roll = Roll('ROLL01', 'GREIGE01', 700)
        roll._add_to_group()

        with self.assertRaises(RuntimeError) as cm:
            roll.allocate(350)
        
        self.assertEqual(roll.qty, 700)
        self.assertEqual(str(cm.exception),
                         '\'Roll\' objects cannot be mutated while in a group')
        
        roll._rem_from_group()
        roll.allocate(350)
        self.assertEqual(roll.qty, 350)

if __name__ == '__main__':
    unittest.main()