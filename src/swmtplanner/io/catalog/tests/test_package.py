#!/usr/bin/env python

import unittest

from swmtplanner import io
from swmtplanner.io import catalog
from swmtplanner.io.catalog._converters import _strip, _is_x, _is_active
from swmtplanner.io.catalog._sql import read_sql


class TestExports(unittest.TestCase):

    def test_catalog_exports(self):
        self.assertEqual(catalog.__all__,
                         ['xref', 'variants', 'masterstyles', 'demand', 'machines'])
        for name in catalog.__all__:
            self.assertTrue(hasattr(catalog, name), name)
        self.assertIn('catalog', io.__all__)


class TestConverters(unittest.TestCase):

    def test_strip_text(self):
        self.assertEqual(_strip('  FF A B '), 'FF A B')
        self.assertEqual(_strip(''), '')

    def test_strip_number(self):
        self.assertEqual(_strip(239569), '239569')

    def test_is_x_true(self):
        for v in ('X', 'x', ' X '):
            with self.subTest(v=v):
                self.assertIs(_is_x(v), True)

    def test_is_x_false(self):
        for v in ('', 'Y', 'XX', 0):
            with self.subTest(v=v):
                self.assertIs(_is_x(v), False)

    def test_is_active_true(self):
        for v in ('A', '', ' ', 'B'):
            with self.subTest(v=v):
                self.assertIs(_is_active(v), True)

    def test_is_active_false(self):
        for v in ('I', 'i', ' I '):
            with self.subTest(v=v):
                self.assertIs(_is_active(v), False)


class TestReadSQL(unittest.TestCase):

    def test_read_sql(self):
        text = read_sql('si_variants.sql')
        self.assertIsInstance(text, str)
        self.assertTrue(text.startswith('WITH merges AS'))

    def test_read_sql_missing(self):
        with self.assertRaises(FileNotFoundError):
            read_sql('nope.sql')


if __name__ == '__main__':
    unittest.main()
