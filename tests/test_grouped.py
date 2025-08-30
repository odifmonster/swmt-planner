#!/usr/bin/env python

import unittest

import random

from swmtplanner.support import setter_like
from swmtplanner.support.grouped import Data, DataView, Atom

def random_str_id(length: int = 8):
    digits = [str(i) for i in range(10)]
    return ''.join([random.choice(digits) for _ in range(length)])

class Roll(Data[str], mut_in_group=False, read_only=('color','item'),
           priv=('init_qty','allocs')):
    
    def __init__(self, id: str, color: str, item: str, qty: float):
        super().__init__('Roll', id, RollView(self), _color=color, _item=item,
                         _init_qty=qty, _allocs=[])
        
    def __str__(self):
        return f'Roll({self.id} | {self.color}-{self.item} | {self.size})'
        
    @property
    def qty(self) -> float:
        return self._init_qty - sum(self._allocs)
    
    @property
    def size(self) -> str:
        if self.qty <= 600:
            return 'SMALL'
        if self.qty <= 800:
            return 'NORMAL'
        return 'LARGE'
    
    @setter_like
    def allocate(self, amount: float) -> None:
        self._allocs.append(amount)

class RollView(DataView[str], dunders=('str',), attrs=('color','item','qty','size')):
    pass

class TestAtom(unittest.TestCase):
        
    def setUp(self):
        colors = ['BLACK', 'GRAY', 'BLUE']
        items = list(map(lambda i: f'GREIGE{i+1:02}', range(3)))
        self.roll = Roll(random_str_id(), random.choice(colors),
                         random.choice(items), 700)
        self.atom = Atom[str](color=self.roll.color, item=self.roll.item,
                              size='NORMAL', id=self.roll.id)

    def test_bad_init(self):
        with self.assertRaises(ValueError) as cm:
            bad_at = Atom[str](color='BLACK', item='GREIGE01', size='SMALL')

        tgt_msg = '\'Atom\' initializer missing required keyword argument \'id\''
        self.assertEqual(str(cm.exception), tgt_msg)

    def test_add_rem(self):
        self.assertEqual(self.roll.size, 'NORMAL')
        self.roll.allocate(50)
        self.assertAlmostEqual(self.roll.qty, 650, places=4)

        self.atom.add(self.roll)
        with self.assertRaises(RuntimeError) as cm:
            self.roll.allocate(100)
        
        self.assertAlmostEqual(self.roll.qty, 650, places=4)
        self.assertEqual(str(cm.exception),
                         '\'Roll\' objects cannot be mutated while in a group')
        
        self.atom.remove(self.roll.view())
        self.roll.allocate(100)
        self.assertEqual(self.roll.size, 'SMALL')

        with self.assertRaises(ValueError):
            self.atom.add(self.roll)

    def test_props(self):
        self.assertEqual(self.atom.depth, 0)
        self.assertEqual(self.atom.n_items, 0)
        with self.assertRaises(AttributeError) as cm:
            dat = self.atom.data
        
        tgt_msg = 'Empty \'Atom\' object has no data'
        self.assertEqual(str(cm.exception), tgt_msg)

        self.atom.add(self.roll)
        self.assertEqual(self.atom.depth, 0)
        self.assertEqual(self.atom.n_items, 1)
        self.assertEqual(self.atom.data, self.roll)

        self.atom.remove(self.roll.view())
        self.assertEqual(self.atom.depth, 0)
        self.assertEqual(self.atom.n_items, 0)
        with self.assertRaises(AttributeError) as cm:
            dat = self.atom.data
        
        tgt_msg = 'Empty \'Atom\' object has no data'
        self.assertEqual(str(cm.exception), tgt_msg)

    def test_len(self):
        self.assertEqual(len(self.atom), 0)
        self.atom.add(self.roll)
        self.atom.add(self.roll)
        self.assertEqual(len(self.atom), 1)
        self.atom.remove(self.roll.view())
        self.assertEqual(len(self.atom), 0)

    def test_iter(self):
        self.assertEqual(list(self.atom), [])
        self.atom.add(self.roll)
        self.assertEqual(list(self.atom), [tuple()])
        self.atom.remove(self.roll.view())
        self.assertEqual(list(self.atom), [])

    def test_contains(self):
        self.assertTrue(tuple() not in self.atom)
        self.atom.add(self.roll)
        self.assertTrue(tuple() in self.atom)
        self.atom.remove(self.roll.view())
        self.assertTrue(tuple() not in self.atom)

    def test_get(self):
        with self.assertRaises(KeyError) as cm:
            roll = self.atom.get(self.roll.id)
        
        err_msg = str(cm.exception)[1:-1]
        tgt_msg = f'Object has no data with id={repr(self.roll.id)}'
        self.assertEqual(err_msg, tgt_msg)

        self.atom.add(self.roll)
        self.assertEqual(self.atom.get(self.roll.id), self.roll)

if __name__ == '__main__':
    unittest.main()