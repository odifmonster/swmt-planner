#!/usr/bin/env python

import os
import tempfile
import unittest
from datetime import date

import pandas as pd

from swmtplanner.io.catalog.demand import PA_DEMAND_FILE, PA_DEMAND, PA_DEMAND_LOADER

WEEKS = [f'wk{i}' for i in range(0, 9)]
QTY_COLUMNS = ['past_due', *WEEKS]
DEMAND_COLUMNS = ['item', 'bill_to', 'plant', 'ship_day', *QTY_COLUMNS]
QTY_SOURCES = ["FAB req'd past due", *(f"FAB req'd WK{i}" for i in range(0, 9))]
SRC_COLUMNS = ['Ply1 Item', 'PA Item', 'Bill To', 'Plant', 'Ship Day', *QTY_SOURCES,
               'Customer']
DEMAND_RAW = pd.DataFrame([
    {'Ply1 Item': '210189A', 'PA Item': 'FF AURA30000-39064-63 ', 'Bill To': 17191,
     'Plant': 20, 'Ship Day': 2, "FAB req'd WK0": 3181, "FAB req'd WK3": 9069.405,
     "FAB req'd WK8": 5800, 'Customer': 'a'},
    {'Ply1 Item': 222127, 'PA Item': 'FF TAFFETAHP-38712-60', 'Bill To': 17191,
     'Plant': 20, 'Ship Day': 2, "FAB req'd past due": 150.5, 'Customer': 'b'},
    {'Ply1 Item': 'FO000001', 'PA Item': 'FF HANA-40001-59', 'Bill To': 30012,
     'Plant': 1350, 'Ship Day': 4, 'Customer': 'c'},
], columns=SRC_COLUMNS)
DT = date(2026, 11, 4)


class _DemandFixture(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.cfg = {'pa_supply': self.dir, 'inputs': self.dir, 'scheduling': self.dir}
        for day in (DT, date.today()):
            with pd.ExcelWriter(os.path.join(self.dir, f'pa_dmnd_{day:%Y%m%d}.xlsx')) as w:
                DEMAND_RAW.to_excel(w, sheet_name='Fab shortage', index=False)
                pd.DataFrame({'unrelated': [1]}).to_excel(w, sheet_name='Summary',
                                                          index=False)

    def tearDown(self):
        self._tmp.cleanup()

    def load(self):
        return PA_DEMAND_LOADER.load(self.cfg, DT)


class TestDemandConstants(_DemandFixture):

    def test_demand_file(self):
        self.assertEqual(PA_DEMAND_FILE.cfg_name, 'scheduling')
        self.assertEqual(PA_DEMAND_FILE.sheet_name, 'Fab shortage')
        self.assertEqual(PA_DEMAND_FILE.get_fpath(self.cfg, date=DT),
                         os.path.join(self.dir, 'pa_dmnd_20261104.xlsx'))

    def test_demand_table(self):
        self.assertEqual(PA_DEMAND.name, 'pa_demand')
        self.assertEqual(PA_DEMAND.index.name, 'part_no')
        self.assertEqual([c.name for c in PA_DEMAND.columns], DEMAND_COLUMNS)

    def test_demand_week_sources(self):
        by_name = {c.name: c for c in PA_DEMAND.columns}
        for name, src in zip(QTY_COLUMNS, QTY_SOURCES):
            with self.subTest(name=name):
                self.assertEqual(by_name[name].src_name, src)

    def test_demand_loader_constants(self):
        self.assertIs(PA_DEMAND_LOADER.tbl, PA_DEMAND)
        self.assertIs(PA_DEMAND_LOADER.source, PA_DEMAND_FILE)


class TestDemandLoader(_DemandFixture):

    def test_demand_load_shape(self):
        df = self.load()
        self.assertEqual(len(df), 3)
        self.assertEqual(df.index.name, 'part_no')
        self.assertEqual(len(df.columns), 14)
        self.assertEqual(list(df.columns), DEMAND_COLUMNS)
        self.assertNotIn('Customer', df.columns)

    def test_demand_part_numbers(self):
        self.assertEqual(self.load().index.tolist(), ['210189A', '222127', 'FO000001'])

    def test_demand_dtypes(self):
        df = self.load()
        for name in ('item', 'plant'):
            with self.subTest(name=name):
                self.assertEqual(df[name].dtype, 'string')
        for name in ('bill_to', 'ship_day'):
            with self.subTest(name=name):
                self.assertEqual(df[name].dtype, 'int64')
        for name in QTY_COLUMNS:
            with self.subTest(name=name):
                self.assertEqual(df[name].dtype, 'float64')

    def test_demand_text(self):
        df = self.load()
        self.assertEqual(df.loc['210189A', 'item'], 'FF AURA30000-39064-63')
        self.assertEqual(df['plant'].tolist(), ['20', '20', '1350'])

    def test_demand_quantities(self):
        row = self.load().loc['210189A']
        expected = {name: 0.0 for name in QTY_COLUMNS}
        expected.update(wk0=3181.0, wk3=9069.405, wk8=5800.0)
        self.assertEqual(row[QTY_COLUMNS].to_dict(), expected)

    def test_demand_past_due(self):
        row = self.load().loc['222127']
        self.assertEqual(row['past_due'], 150.5)
        self.assertEqual(row[WEEKS].tolist(), [0.0] * 9)

    def test_demand_blank_weeks(self):
        row = self.load().loc['FO000001']
        self.assertEqual(row[QTY_COLUMNS].tolist(), [0.0] * 10)
        self.assertFalse(row[QTY_COLUMNS].isna().any())

    def test_demand_load_default_today(self):
        pd.testing.assert_frame_equal(PA_DEMAND_LOADER.load(self.cfg), self.load())

    def test_demand_load_missing_date(self):
        with self.assertRaises(FileNotFoundError):
            PA_DEMAND_LOADER.load(self.cfg, date(2000, 1, 1))


if __name__ == '__main__':
    unittest.main()
