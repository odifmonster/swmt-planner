#!/usr/bin/env python

import os
import sqlite3
import tempfile
import unittest

import pandas as pd

from swmtplanner.io.catalog._sql import read_sql
from swmtplanner.io.catalog.variants import (
    SI_VARIANTS_QUERY, VARIANTS_TSV, VARIANTS, VARIANT_LOADER, VARIANT_TSV_LOADER,
)
from swmtplanner.io.loaders import SQLQuery, SQLTableLoader, CSVTableLoader

BAR_FIELDS = ['ends', 'merge', 'vendor', 'denier', 'luster', 'desc', 'pct', 'rl',
              'stitch', 'thread']
STR_FIELDS = ['merge', 'vendor', 'luster', 'desc', 'stitch', 'thread']
# the order of the query's select list (and of the extract's header)
SRC_COLUMNS = [
    'variant', 'width', 'rack_wt', 'gauge', 'beams',
    *(f'bar{i}_{f}' for i in range(1, 5)
      for f in ('ends', 'merge', 'vendor', 'denier', 'luster', 'desc')),
    *(f'bar{i}_{f}' for i in range(1, 5) for f in ('pct', 'rl', 'stitch', 'thread')),
    'extra',
]


def _bar(i, **changes):
    vals = {'ends': 1164, 'merge': '612VE2095S53', 'vendor': 'NANYA', 'denier': 40,
            'luster': 'SD', 'desc': 'POLY', 'pct': 33.3, 'rl': 61.5,
            'stitch': '1-0/1-2', 'thread': 'SOLID'}
    vals.update(changes)
    return {f'bar{i}_{k}': v for k, v in vals.items()}


ROW_3BAR = {'variant': 'TA0799/31', 'width': 168, 'rack_wt': 12.51, 'gauge': 28,
            'beams': 4, **_bar(1), **_bar(2), **_bar(3), 'extra': 'x'}
ROW_4BAR = {'variant': 'AU7805-X', 'width': 186, 'rack_wt': 20.0, 'gauge': 28,
            'beams': 4, **_bar(1), **_bar(2), **_bar(3),
            **_bar(4, denier=70, thread='1 IN, 1 OUT'), 'extra': 'y'}
Q_ALL = SQLQuery('SELECT * FROM variants', 0)


def _raw(rows):
    # object dtype with None for blanks, so integers stay integers
    df = pd.DataFrame(rows, columns=SRC_COLUMNS).astype(object)
    return df.where(df.notna(), None)


RAW_VARIANTS = _raw([ROW_3BAR, ROW_4BAR])


class _VariantFixture(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.cfg = {'pa_supply': self.dir, 'inputs': self.dir, 'scheduling': self.dir}
        self.write_tsv(RAW_VARIANTS)
        self.conn = sqlite3.connect(':memory:')
        RAW_VARIANTS.to_sql('variants', self.conn, index=False)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def write_tsv(self, raw):
        raw.to_csv(os.path.join(self.dir, 'variants.tsv'), sep='\t', index=False,
                   na_rep='None')

    def load(self):
        return VARIANT_TSV_LOADER.load(self.cfg)

    def row(self, variant):
        df = self.load()
        return df[df['variant'] == variant].iloc[0]


class TestVariantConstants(_VariantFixture):

    def test_variants_tsv(self):
        self.assertEqual(VARIANTS_TSV.cfg_name, 'inputs')
        self.assertEqual(VARIANTS_TSV.sep, '\t')
        self.assertIsNone(VARIANTS_TSV.date_fmt)
        self.assertEqual(VARIANTS_TSV.get_fpath(self.cfg),
                         os.path.join(self.dir, 'variants.tsv'))

    def test_variants_query(self):
        self.assertEqual(SI_VARIANTS_QUERY.date_params, 0)
        self.assertEqual(SI_VARIANTS_QUERY.get_query(), read_sql('si_variants.sql'))

    def test_variants_table(self):
        self.assertEqual(VARIANTS.name, 'variants')
        self.assertIsNone(VARIANTS.index)
        self.assertEqual(len(VARIANTS.columns), 45)
        self.assertEqual([c.name for c in VARIANTS.columns[:5]],
                         ['variant', 'width', 'rack_wt', 'gauge', 'beams'])

    def test_variants_bar_columns(self):
        expected = [f'bar{i}_{f}' for i in range(1, 5) for f in BAR_FIELDS]
        self.assertEqual([c.name for c in VARIANTS.columns[5:]], expected)

    def test_variants_no_renames(self):
        for col in VARIANTS.columns:
            with self.subTest(col=col.name):
                self.assertIsNone(col.src_name)

    def test_query_names_every_column(self):
        query = SI_VARIANTS_QUERY.get_query()
        for col in VARIANTS.columns:
            with self.subTest(col=col.name):
                self.assertIn(f'AS "{col.name}"', query)

    def test_variant_loader_constants(self):
        self.assertIsInstance(VARIANT_LOADER, SQLTableLoader)
        self.assertIs(VARIANT_LOADER.tbl, VARIANTS)
        self.assertIs(VARIANT_LOADER.source, SI_VARIANTS_QUERY)
        self.assertIsInstance(VARIANT_TSV_LOADER, CSVTableLoader)
        self.assertIs(VARIANT_TSV_LOADER.tbl, VARIANTS)
        self.assertIs(VARIANT_TSV_LOADER.source, VARIANTS_TSV)


class TestVariantTSVLoader(_VariantFixture):

    def test_variants_load_shape(self):
        df = self.load()
        self.assertEqual(len(df), 2)
        self.assertEqual(list(df.columns), [c.name for c in VARIANTS.columns])
        self.assertEqual(len(df.columns), 45)
        self.assertNotIn('extra', df.columns)
        self.assertEqual(df.index.tolist(), [0, 1])

    def test_variants_dtypes(self):
        df = self.load()
        strings = ['variant', *(f'bar{i}_{f}' for i in range(1, 5) for f in STR_FIELDS)]
        ints = ['width', 'gauge', 'beams',
                *(f'bar{i}_{f}' for i in range(1, 5) for f in ('ends', 'denier'))]
        floats = ['rack_wt', *(f'bar{i}_{f}' for i in range(1, 5) for f in ('pct', 'rl'))]
        self.assertEqual(len(strings) + len(ints) + len(floats), 45)
        for names, dtype in ((strings, 'string'), (ints, 'int64'), (floats, 'float64')):
            for name in names:
                with self.subTest(name=name):
                    self.assertEqual(df[name].dtype, dtype)

    def test_variants_values(self):
        row = self.row('TA0799/31')
        self.assertEqual(row['width'], 168)
        self.assertEqual(row['rack_wt'], 12.51)
        self.assertEqual(row['gauge'], 28)
        self.assertEqual(row['beams'], 4)
        self.assertEqual(row['bar1_ends'], 1164)
        self.assertEqual(row['bar1_merge'], '612VE2095S53')
        self.assertEqual(row['bar1_denier'], 40)
        self.assertEqual(row['bar1_rl'], 61.5)
        self.assertEqual(row['bar1_thread'], 'SOLID')

    def test_variants_unused_bar_numbers(self):
        row = self.row('TA0799/31')
        self.assertEqual(row['bar4_ends'], 0)
        self.assertEqual(row['bar4_denier'], 0)
        self.assertEqual(row['bar4_pct'], 0.0)
        self.assertEqual(row['bar4_rl'], 0.0)

    def test_variants_unused_bar_text(self):
        row = self.row('TA0799/31')
        for f in STR_FIELDS:
            with self.subTest(field=f):
                self.assertTrue(pd.isna(row[f'bar4_{f}']))

    def test_variants_denier_not_normalised(self):
        self.assertEqual(self.row('AU7805-X')['bar4_denier'], 70)

    def test_variants_duplicates_kept(self):
        self.write_tsv(_raw([ROW_3BAR, ROW_3BAR]))
        df = self.load()
        self.assertEqual(df['variant'].tolist(), ['TA0799/31', 'TA0799/31'])


class TestVariantsOverConnection(_VariantFixture):

    def test_variants_sql_matches_tsv(self):
        df = SQLTableLoader(VARIANTS, Q_ALL).load(self.conn)
        pd.testing.assert_frame_equal(df, self.load())


if __name__ == '__main__':
    unittest.main()
