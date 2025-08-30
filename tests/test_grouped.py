#!/usr/bin/env python

import unittest

import random

from swmtplanner.support import setter_like
from swmtplanner.support.grouped import Data, DataView, Atom, Grouped

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

class TestGrouped(unittest.TestCase):
    
    def setUp(self):
        self.group1 = Grouped[str, str]('color', 'item', 'size', 'id')
        self.group2 = Grouped[str, str]('size', 'id', color='BLACK', item='GREIGE01')

        self.all_rolls: list[Roll] = []
        self.g2_rolls: list[Roll] = []

        colors = ['BLACK', 'GRAY', 'BLUE']
        items = list(map(lambda i: f'GREIGE{i+1:02}', range(3)))
        for _ in range(300):
            roll = Roll(random_str_id(), random.choice(colors), random.choice(items),
                        random.normalvariate(mu=700, sigma=100))
            self.all_rolls.append(roll)
            if roll.color == 'BLACK' and roll.item == 'GREIGE01':
                self.g2_rolls.append(roll)

    def test_add_rem(self):
        test_roll = self.all_rolls[0]
        init_qty = test_roll.qty
        self.group1.add(test_roll)

        with self.assertRaises(RuntimeError) as cm:
            test_roll.allocate(100)
        self.assertEqual(str(cm.exception),
                         '\'Roll\' objects cannot be mutated while in a group')
        
        self.group1.remove(test_roll.view())
        test_roll.allocate(100)
        self.assertAlmostEqual(init_qty-100, test_roll.qty, places=4)

    def test_bad_props(self):
        bad_roll1 = Roll(random_str_id(), 'BLACK', 'GREIGE02', 700)
        bad_roll2 = Roll(random_str_id(), 'BLUE', 'GREIGE01', 700)

        with self.assertRaises(ValueError) as cm:
            self.group2.add(bad_roll1)

        with self.assertRaises(ValueError) as cm:
            self.group2.add(bad_roll2)

    def test_n_items(self):
        for i, roll in enumerate(self.all_rolls):
            self.assertEqual(self.group1.n_items, i)
            self.group1.add(roll)

        for roll in self.all_rolls:
            self.group1.add(roll)
        
        self.assertEqual(self.group1.n_items, len(self.all_rolls))

        for i, roll in enumerate(self.all_rolls):
            self.assertEqual(self.group1.n_items, len(self.all_rolls)-i)
            self.group1.remove(roll.view())

    def test_len(self):
        colors: dict[str, list[Roll]] = {}
        for roll in self.all_rolls:
            self.assertEqual(len(self.group1), len(colors))
            if roll.color not in colors:
                colors[roll.color] = []
            colors[roll.color].append(roll)
            self.group1.add(roll)

        for roll in self.all_rolls:
            self.assertEqual(len(self.group1), len(colors))
            colors[roll.color].remove(roll)
            if len(colors[roll.color]) == 0:
                del colors[roll.color]
            self.group1.remove(roll)

    def test_iter(self):
        colors: dict[str, list[Roll]] = {}
        for roll in self.all_rolls:
            self.assertEqual(set(self.group1), colors.keys())
            if roll.color not in colors:
                colors[roll.color] = []
            colors[roll.color].append(roll)
            self.group1.add(roll)

        for roll in self.all_rolls:
            self.assertEqual(set(self.group1), colors.keys())
            colors[roll.color].remove(roll)
            if len(colors[roll.color]) == 0:
                del colors[roll.color]
            self.group1.remove(roll)
    
    def test_contains(self):
        colors: dict[str, list[Roll]] = {}
        for roll in self.all_rolls:
            self.assertTrue(all(map(lambda clr: clr in self.group1, colors.keys())))
            if roll.color not in colors:
                colors[roll.color] = []
            colors[roll.color].append(roll)
            self.group1.add(roll)

        rem_colors: set[str] = set()
        for roll in self.all_rolls:
            self.assertTrue(all(map(lambda clr: clr in self.group1, colors.keys())))
            self.assertTrue(all(map(lambda clr: clr not in self.group1, rem_colors)))
            colors[roll.color].remove(roll)
            if len(colors[roll.color]) == 0:
                del colors[roll.color]
                rem_colors.add(roll.color)
            self.group1.remove(roll)

if __name__ == '__main__':
    unittest.main()