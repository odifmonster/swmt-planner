#!/usr/bin/env python

import json
import os
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime

import pandas as pd

from swmtplanner.io.loaders import (
    Column, Table, SQLQuery, CSVFile, ExcelFile, JSONFile,
    TableLoader, SQLTableLoader, CSVTableLoader, ExcelTableLoader, JSONTableLoader,
)

TBL = Table('styles', (
    Column('style', 'string', src_name='variant'),
    Column('width', 'int64'),
    Column('rl', 'float64', src_name='bar1_rl', read_na_as=0.0),
    Column('thread', 'string', src_name='bar1_thread', converter=str.upper, read_na_as='SOLID'),
))
RAW = pd.DataFrame({'variant': ['A/1', 'B'], 'width': [168, 144], 'bar1_rl': [61.5, None],
                    'bar1_thread': ['1 in, 1 out', None], 'extra': [1, 2]})
SRC_CSV = CSVFile('inputs', 'styles_{}', '.tsv', date_fmt='%Y-%m-%d', sep='\t')
SRC_XLSX = ExcelFile('inputs', 'inv_{}', date_fmt='%Y%m%d', sheet_name='Inv')
SRC_JSON = JSONFile('inputs', 'styles')
SRC_JSON_DATED = JSONFile('inputs', 'styles_{}', date_fmt='%Y-%m-%d')
SRC_KEYED = JSONFile('inputs', 'keyed', orient='index')
TBL_KEYED = Table('machines', (Column('gauge', 'int64'), Column('attrs', 'object', converter=tuple)),
                  index=Column('machine', 'string', src_name='index'))
KEYED = {'10': {'gauge': 28, 'attrs': ['tall']}, '2': {'gauge': 32, 'attrs': []}}
DT = date(2026, 11, 4)


class _FileFixture(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.cfg = {'inputs': self.dir}
        RAW.to_csv(os.path.join(self.dir, 'styles_2026-11-04.tsv'), sep='\t', index=False)
        RAW.to_csv(os.path.join(self.dir, 'c.csv'), index=False)
        RAW.iloc[:0].to_csv(os.path.join(self.dir, 'empty.tsv'), sep='\t', index=False)
        footer = pd.DataFrame({'variant': ['TOTAL'], 'width': [0], 'bar1_rl': [0.0],
                               'bar1_thread': [''], 'extra': [0]})
        with pd.ExcelWriter(os.path.join(self.dir, 'inv_20261104.xlsx')) as w:
            pd.concat([RAW, footer]).to_excel(w, sheet_name='Inv', index=False)
        RAW.to_json(os.path.join(self.dir, 'styles.json'), orient='records')
        RAW.to_json(os.path.join(self.dir, 'styles_2026-11-04.json'), orient='records')
        with open(os.path.join(self.dir, 'keyed.json'), 'w') as f:
            json.dump(KEYED, f)

    def tearDown(self):
        self._tmp.cleanup()

    def load_csv(self, tbl=TBL):
        return CSVTableLoader(tbl, SRC_CSV).load(self.cfg, DT)


class TestTableLoaderConversion(_FileFixture):

    def test_loader_abstract(self):
        with self.assertRaises(TypeError):
            TableLoader(TBL, SRC_CSV)

    def test_convert_columns_and_rename(self):
        df = self.load_csv()
        self.assertEqual(list(df.columns), ['style', 'width', 'rl', 'thread'])
        self.assertEqual(df['style'].tolist(), ['A/1', 'B'])

    def test_convert_drops_unlisted(self):
        self.assertNotIn('extra', self.load_csv().columns)

    def test_convert_dtypes(self):
        df = self.load_csv()
        self.assertEqual(str(df['style'].dtype), 'string')
        self.assertEqual(str(df['width'].dtype), 'int64')
        self.assertEqual(str(df['rl'].dtype), 'float64')

    def test_convert_read_na_as(self):
        self.assertEqual(self.load_csv()['rl'].tolist(), [61.5, 0.0])

    def test_convert_converter(self):
        self.assertEqual(self.load_csv()['thread'].tolist(), ['1 IN, 1 OUT', 'SOLID'])

    def test_convert_na_before_converter(self):
        self.assertEqual(self.load_csv()['thread'].tolist()[1], 'SOLID')

    def test_convert_converter_without_na(self):
        tbl = Table('t', (Column('w2', 'int64', src_name='width', converter=lambda v: v * 2),))
        self.assertEqual(self.load_csv(tbl)['w2'].tolist(), [336, 288])

    def test_convert_index(self):
        df = self.load_csv(Table('styles', TBL.columns[1:], index=TBL.columns[0]))
        self.assertEqual(df.index.name, 'style')
        self.assertEqual(df.index.tolist(), ['A/1', 'B'])
        self.assertNotIn('style', df.columns)

    def test_convert_index_converted(self):
        ix = Column('style', 'string', src_name='variant', converter=str.lower)
        df = self.load_csv(Table('styles', TBL.columns[1:], index=ix))
        self.assertEqual(df.index.tolist(), ['a/1', 'b'])

    def test_convert_missing_column(self):
        with self.assertRaises(KeyError) as cm:
            self.load_csv(Table('t', (Column('nope', 'string'),)))
        self.assertIn("'t'", str(cm.exception))
        self.assertIn('nope', str(cm.exception))

    def test_convert_missing_src_name(self):
        with self.assertRaises(KeyError) as cm:
            self.load_csv(Table('t', (Column('x', 'string', src_name='nope'),)))
        self.assertIn('nope', str(cm.exception))
        self.assertNotIn("'x'", str(cm.exception))

    def test_convert_empty_source(self):
        df = CSVTableLoader(TBL, CSVFile('inputs', 'empty', '.tsv', sep='\t')).load(self.cfg)
        self.assertEqual(len(df), 0)
        self.assertEqual(list(df.columns), ['style', 'width', 'rl', 'thread'])
        self.assertEqual(str(df['style'].dtype), 'string')
        self.assertEqual(str(df['width'].dtype), 'int64')
        self.assertEqual(str(df['rl'].dtype), 'float64')
        self.assertEqual(str(df['thread'].dtype), 'string')


class TestCSVTableLoader(_FileFixture):

    def test_csv_loader_init(self):
        ldr = CSVTableLoader(TBL, SRC_CSV)
        self.assertIs(ldr.tbl, TBL)
        self.assertIs(ldr.source, SRC_CSV)

    def test_csv_wrong_source(self):
        with self.assertRaises(TypeError):
            CSVTableLoader(TBL, SRC_XLSX)

    def test_csv_load_dated(self):
        df = self.load_csv()
        self.assertEqual(len(df), 2)
        self.assertEqual(list(df.columns), [c.name for c in TBL.columns])

    def test_csv_load_override(self):
        df = CSVTableLoader(TBL, SRC_CSV).load(self.cfg, override_name='styles_2026-11-04.tsv')
        pd.testing.assert_frame_equal(df, self.load_csv())

    def test_csv_load_sep(self):
        df = CSVTableLoader(TBL, CSVFile('inputs', 'c', '.csv')).load(self.cfg)
        self.assertEqual(len(df), 2)

    def test_csv_load_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            CSVTableLoader(TBL, SRC_CSV).load(self.cfg, date(2000, 1, 1))


class TestExcelTableLoader(_FileFixture):

    def load_xlsx(self, src=SRC_XLSX, **kw):
        return ExcelTableLoader(TBL, src).load(self.cfg, DT, **kw)

    def test_excel_loader_init(self):
        ldr = ExcelTableLoader(TBL, SRC_XLSX)
        self.assertIs(ldr.tbl, TBL)
        self.assertIs(ldr.source, SRC_XLSX)

    def test_excel_wrong_source(self):
        with self.assertRaises(TypeError):
            ExcelTableLoader(TBL, SRC_CSV)

    def test_excel_load_dated(self):
        self.assertEqual(len(self.load_xlsx()), 3)

    def test_excel_load_skipfooter(self):
        df = self.load_xlsx(replace(SRC_XLSX, skipfooter=1))
        self.assertEqual(df['style'].tolist(), ['A/1', 'B'])

    def test_excel_load_nrows(self):
        df = self.load_xlsx(replace(SRC_XLSX, nrows=1))
        self.assertEqual(df['style'].tolist(), ['A/1'])

    def test_excel_load_sheet_by_index(self):
        pd.testing.assert_frame_equal(self.load_xlsx(replace(SRC_XLSX, sheet_name=0)),
                                      self.load_xlsx())

    def test_excel_load_wrong_sheet(self):
        with self.assertRaises(ValueError):
            self.load_xlsx(replace(SRC_XLSX, sheet_name='Nope'))

    def test_excel_load_override(self):
        df = ExcelTableLoader(TBL, SRC_XLSX).load(self.cfg, override_name='inv_20261104.xlsx')
        pd.testing.assert_frame_equal(df, self.load_xlsx())


class TestJSONTableLoader(_FileFixture):

    def load_keyed(self, tbl=TBL_KEYED):
        return JSONTableLoader(tbl, SRC_KEYED).load(self.cfg)

    def test_json_loader_init(self):
        ldr = JSONTableLoader(TBL, SRC_JSON)
        self.assertIs(ldr.tbl, TBL)
        self.assertIs(ldr.source, SRC_JSON)

    def test_json_wrong_source(self):
        with self.assertRaises(TypeError):
            JSONTableLoader(TBL, SRC_CSV)

    def test_json_load_records(self):
        df = JSONTableLoader(TBL, SRC_JSON).load(self.cfg)
        self.assertEqual(len(df), 2)
        self.assertEqual(df['rl'].tolist(), [61.5, 0.0])
        self.assertEqual(df['thread'].tolist(), ['1 IN, 1 OUT', 'SOLID'])
        self.assertNotIn('extra', df.columns)
        self.assertEqual([str(t) for t in df.dtypes], ['string', 'int64', 'float64', 'string'])

    def test_json_load_dated(self):
        df = JSONTableLoader(TBL, SRC_JSON_DATED).load(self.cfg, DT)
        pd.testing.assert_frame_equal(df, JSONTableLoader(TBL, SRC_JSON).load(self.cfg))

    def test_json_load_override(self):
        df = JSONTableLoader(TBL, SRC_JSON_DATED).load(self.cfg, override_name='styles.json')
        pd.testing.assert_frame_equal(df, JSONTableLoader(TBL, SRC_JSON).load(self.cfg))

    def test_json_load_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            JSONTableLoader(TBL, SRC_JSON_DATED).load(self.cfg, date(2000, 1, 1))

    def test_json_load_index_orient(self):
        df = self.load_keyed()
        self.assertEqual(df.index.name, 'machine')
        self.assertEqual(list(df.columns), ['gauge', 'attrs'])
        self.assertEqual(df['gauge'].tolist(), [28, 32])

    def test_json_load_index_keys_stay_strings(self):
        self.assertEqual(self.load_keyed().index.tolist(), ['10', '2'])

    def test_json_load_index_key_as_column(self):
        df = self.load_keyed(Table('machines', (Column('machine', 'string', src_name='index'),
                                                Column('gauge', 'int64'))))
        self.assertEqual(df['machine'].tolist(), ['10', '2'])
        self.assertEqual(df.index.tolist(), [0, 1])

    def test_json_load_list_values(self):
        self.assertEqual(self.load_keyed()['attrs'].tolist(), [('tall',), ()])

    def test_json_load_records_no_index_column(self):
        with self.assertRaises(KeyError) as cm:
            JSONTableLoader(Table('t', (Column('k', 'string', src_name='index'),)), SRC_JSON).load(self.cfg)
        self.assertIn('index', str(cm.exception))


class TestSQLTableLoader(unittest.TestCase):

    Q_ALL = SQLQuery("SELECT * FROM styles", 0)
    Q_SINCE = SQLQuery("SELECT * FROM styles WHERE doff >= {0}", 1, "'%Y-%m-%d'")

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        RAW.assign(doff=['2026-01-15', '2026-03-15']).to_sql('styles', self.conn, index=False)

    def tearDown(self):
        self.conn.close()

    def test_sql_init(self):
        ldr = SQLTableLoader(TBL, self.Q_ALL)
        self.assertIs(ldr.tbl, TBL)
        self.assertIs(ldr.source, self.Q_ALL)

    def test_sql_wrong_source(self):
        with self.assertRaises(TypeError):
            SQLTableLoader(TBL, SRC_CSV)

    def test_sql_load(self):
        df = SQLTableLoader(TBL, self.Q_ALL).load(self.conn)
        self.assertEqual(len(df), 2)
        self.assertEqual(df['rl'].tolist(), [61.5, 0.0])
        self.assertEqual(df['thread'].tolist(), ['1 IN, 1 OUT', 'SOLID'])
        self.assertNotIn('extra', df.columns)

    def test_sql_load_passes_args(self):
        df = SQLTableLoader(TBL, self.Q_SINCE).load(self.conn, datetime(2026, 2, 1))
        self.assertEqual(df['style'].tolist(), ['B'])

    def test_sql_load_missing_arg(self):
        with self.assertRaises(ValueError):
            SQLTableLoader(TBL, self.Q_SINCE).load(self.conn)

    def test_sql_load_missing_column(self):
        with self.assertRaises(KeyError):
            SQLTableLoader(Table('t', (Column('nope', 'string'),)), self.Q_ALL).load(self.conn)


if __name__ == '__main__':
    unittest.main()
