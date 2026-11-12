#!/usr/bin/env python

import unittest
from dataclasses import FrozenInstanceError

from swmtplanner.io.loaders import Column, Table

COL_A = Column('a', 'string')
COL_B = Column('b', 'int64')


class TestColumn(unittest.TestCase):

    def test_column_init_minimal(self):
        c = Column('width', 'int64')
        self.assertEqual(c.name, 'width')
        self.assertEqual(c.dtype, 'int64')
        self.assertIsNone(c.src_name)
        self.assertIsNone(c.converter)
        self.assertIsNone(c.read_na_as)

    def test_column_init_full(self):
        c = Column('rl', 'float64', src_name='bar1_rl', converter=float, read_na_as=0.0)
        self.assertEqual(c.name, 'rl')
        self.assertEqual(c.dtype, 'float64')
        self.assertEqual(c.src_name, 'bar1_rl')
        self.assertIs(c.converter, float)
        self.assertEqual(c.read_na_as, 0.0)

    def test_column_equality(self):
        self.assertEqual(Column('a', 'int64'), Column('a', 'int64'))
        self.assertNotEqual(Column('a', 'int64'), Column('a', 'string'))

    def test_column_frozen(self):
        with self.assertRaises(FrozenInstanceError):
            COL_A.dtype = 'string'


class TestTable(unittest.TestCase):

    def test_table_init(self):
        t = Table('styles', (COL_A, COL_B))
        self.assertEqual(t.name, 'styles')
        self.assertEqual(t.columns, (COL_A, COL_B))
        self.assertIsNone(t.index)

    def test_table_init_index(self):
        t = Table('styles', (COL_B,), index=COL_A)
        self.assertIs(t.index, COL_A)

    def test_table_frozen(self):
        t = Table('styles', (COL_A,))
        with self.assertRaises(FrozenInstanceError):
            t.name = 'x'


if __name__ == '__main__':
    unittest.main()
