#!/usr/bin/env python

import os
import unittest
from dataclasses import FrozenInstanceError
from datetime import date, datetime

from swmtplanner.io.loaders import SQLQuery, File, CSVFile, ExcelFile, JSONFile, conn_str

D1 = datetime(2026, 1, 1)
D2 = datetime(2026, 2, 1)
FMT = "'%Y-%m-%d'"
Q_POS = SQLQuery("WHERE d >= {0} AND d < {1}", 2, FMT, defaults=(None, lambda: D2))
Q_NAMED = SQLQuery("WHERE d >= {start} AND d < {end}", ('start', 'end'), FMT,
                   defaults=(('end', lambda: D2),))
Q_NONE = SQLQuery("SELECT 1", 0)
EXPECTED = "WHERE d >= '2026-01-01' AND d < '2026-02-01'"

CFG = {'inputs': '/data/in', 'exports': '/data/out'}
F_PLAIN = CSVFile('inputs', 'variants', '.tsv', sep='\t')
F_DATED = ExcelFile('exports', 'inv_{}', date_fmt='%Y%m%d', sheet_name='Inv')
F_JSON = JSONFile('inputs', 'machines', orient='index')

SQL_CFG = {'sql': {'HOST': 'db.local', 'PORT': 1433, 'DATABASE': 'plant', 'UID': 'u', 'PWD': 'secret'}}


def _sql_cfg(**extra):
    return {'sql': {**SQL_CFG['sql'], **extra}}


def _sql_cfg_without(key):
    return {'sql': {k: v for k, v in SQL_CFG['sql'].items() if k != key}}


class TestSQLQueryInit(unittest.TestCase):

    def test_query_init(self):
        self.assertEqual(Q_POS.raw_str, "WHERE d >= {0} AND d < {1}")
        self.assertEqual(Q_POS.date_params, 2)
        self.assertEqual(Q_POS.date_fmt, FMT)
        self.assertEqual(len(Q_POS.defaults), 2)

    def test_query_no_params_no_fmt(self):
        self.assertIsNone(SQLQuery("SELECT 1", 0).date_fmt)
        self.assertIsNone(SQLQuery("SELECT 1", ()).date_fmt)

    def test_query_params_need_fmt_positional(self):
        with self.assertRaises(ValueError):
            SQLQuery("x {0}", 1)

    def test_query_params_need_fmt_named(self):
        with self.assertRaises(ValueError):
            SQLQuery("x {a}", ('a',))

    def test_query_defaults_wrong_length(self):
        with self.assertRaises(ValueError):
            SQLQuery("x {0}", 1, FMT, defaults=(None, None))

    def test_query_defaults_not_callable(self):
        with self.assertRaises(ValueError):
            SQLQuery("x {0}", 1, FMT, defaults=(D1,))

    def test_query_defaults_unknown_name(self):
        with self.assertRaises(ValueError):
            SQLQuery("x {a}", ('a',), FMT, defaults=(('b', None),))

    def test_query_defaults_named_bad_shape(self):
        with self.assertRaises(ValueError):
            SQLQuery("x {a}", ('a',), FMT, defaults=(lambda: D1,))

    def test_query_frozen(self):
        with self.assertRaises(FrozenInstanceError):
            Q_POS.raw_str = ''


class TestSQLQueryPositional(unittest.TestCase):

    def test_pos_all_given(self):
        self.assertEqual(Q_POS.get_query(D1, D2), EXPECTED)

    def test_pos_default_omitted(self):
        self.assertEqual(Q_POS.get_query(D1), EXPECTED)

    def test_pos_default_none(self):
        self.assertEqual(Q_POS.get_query(D1, None), EXPECTED)

    def test_pos_default_evaluated_lazily(self):
        calls = []
        q = SQLQuery("{0}", 1, FMT, defaults=(lambda: calls.append(1) or D1,))
        self.assertEqual(calls, [])
        q.get_query()
        self.assertEqual(calls, [1])

    def test_pos_missing_required(self):
        with self.assertRaises(ValueError):
            Q_POS.get_query()

    def test_pos_none_for_required(self):
        with self.assertRaises(ValueError):
            Q_POS.get_query(None, D2)

    def test_pos_too_many(self):
        with self.assertRaises(ValueError):
            Q_POS.get_query(D1, D2, D1)

    def test_pos_rejects_keywords(self):
        with self.assertRaises(ValueError):
            Q_POS.get_query(start=D1)

    def test_pos_no_defaults(self):
        q = SQLQuery("{0}", 1, FMT)
        self.assertEqual(q.get_query(D1), "'2026-01-01'")
        with self.assertRaises(ValueError):
            q.get_query()

    def test_pos_date_fmt_applied(self):
        self.assertEqual(SQLQuery("{0}", 1, "%Y%m%d").get_query(D1), "20260101")


class TestSQLQueryNamed(unittest.TestCase):

    def test_named_all_given(self):
        self.assertEqual(Q_NAMED.get_query(start=D1, end=D2), EXPECTED)

    def test_named_default_omitted(self):
        self.assertEqual(Q_NAMED.get_query(start=D1), EXPECTED)

    def test_named_default_none(self):
        self.assertEqual(Q_NAMED.get_query(start=D1, end=None), EXPECTED)

    def test_named_missing_required(self):
        with self.assertRaises(ValueError):
            Q_NAMED.get_query(end=D2)

    def test_named_unknown_keyword(self):
        with self.assertRaises(ValueError):
            Q_NAMED.get_query(start=D1, foo=D2)

    def test_named_rejects_positional(self):
        with self.assertRaises(ValueError):
            Q_NAMED.get_query(D1, D2)

    def test_named_order_independent(self):
        self.assertEqual(Q_NAMED.get_query(end=D2, start=D1), EXPECTED)


class TestSQLQueryNoParams(unittest.TestCase):

    def test_none_returns_raw(self):
        self.assertEqual(Q_NONE.get_query(), "SELECT 1")

    def test_none_raw_braces_untouched(self):
        self.assertEqual(SQLQuery("SELECT '{literal}'", 0).get_query(), "SELECT '{literal}'")

    def test_none_rejects_args(self):
        with self.assertRaises(ValueError):
            Q_NONE.get_query(D1)
        with self.assertRaises(ValueError):
            Q_NONE.get_query(a=D1)

    def test_mixed_forms(self):
        with self.assertRaises(ValueError):
            Q_POS.get_query(D1, end=D2)


class TestFile(unittest.TestCase):

    def test_file_init(self):
        f = File('inputs', 'variants', '.tsv')
        self.assertEqual(f.cfg_name, 'inputs')
        self.assertEqual(f.stem, 'variants')
        self.assertEqual(f.ext, '.tsv')
        self.assertIsNone(f.date_fmt)

    def test_csv_init(self):
        self.assertEqual(F_PLAIN.sep, '\t')
        self.assertEqual(F_PLAIN.ext, '.tsv')
        self.assertEqual(CSVFile('a', 'b', '.csv').sep, ',')

    def test_excel_init(self):
        self.assertEqual(F_DATED.ext, '.xlsx')
        self.assertEqual(F_DATED.sheet_name, 'Inv')
        self.assertEqual(F_DATED.header, 0)
        self.assertIsNone(F_DATED.skiprows)
        self.assertIsNone(F_DATED.nrows)
        self.assertEqual(F_DATED.skipfooter, 0)

    def test_excel_ext_override(self):
        self.assertEqual(ExcelFile('a', 'b', '.xls').ext, '.xls')

    def test_json_init(self):
        f = JSONFile('inputs', 'styles')
        self.assertEqual(f.ext, '.json')
        self.assertEqual(f.orient, 'records')
        self.assertIsNone(f.date_fmt)
        self.assertEqual(F_JSON.orient, 'index')

    def test_fpath_json(self):
        self.assertEqual(F_JSON.get_fpath(CFG), os.path.join('/data/in', 'machines.json'))

    def test_fpath_json_dated(self):
        f = JSONFile('inputs', 'm_{}', date_fmt='%Y%m%d')
        self.assertEqual(f.get_fpath(CFG, date=date(2026, 11, 4)),
                         os.path.join('/data/in', 'm_20261104.json'))

    def test_fpath_undated(self):
        self.assertEqual(F_PLAIN.get_fpath(CFG), os.path.join('/data/in', 'variants.tsv'))

    def test_fpath_undated_ignores_date(self):
        self.assertEqual(F_PLAIN.get_fpath(CFG, date=date(2026, 11, 4)),
                         os.path.join('/data/in', 'variants.tsv'))

    def test_fpath_dated(self):
        self.assertEqual(F_DATED.get_fpath(CFG, date=date(2026, 11, 4)),
                         os.path.join('/data/out', 'inv_20261104.xlsx'))

    def test_fpath_dated_default_today(self):
        self.assertEqual(F_DATED.get_fpath(CFG),
                         os.path.join('/data/out', f'inv_{date.today():%Y%m%d}.xlsx'))

    def test_fpath_dated_stem_format(self):
        f = CSVFile('inputs', 'a_{}_b', '.csv', date_fmt='%Y')
        self.assertEqual(f.get_fpath(CFG, date=date(2026, 1, 1)),
                         os.path.join('/data/in', 'a_2026_b.csv'))

    def test_fpath_override(self):
        self.assertEqual(F_PLAIN.get_fpath(CFG, override_name='old.tsv'),
                         os.path.join('/data/in', 'old.tsv'))

    def test_fpath_override_beats_date(self):
        self.assertEqual(F_DATED.get_fpath(CFG, 'x.xlsx', date(2026, 1, 1)),
                         os.path.join('/data/out', 'x.xlsx'))

    def test_fpath_missing_cfg_key(self):
        with self.assertRaises(KeyError):
            F_PLAIN.get_fpath({})

    def test_file_frozen(self):
        with self.assertRaises(FrozenInstanceError):
            F_PLAIN.stem = 'x'


class TestConnStr(unittest.TestCase):

    def test_conn_str_required_only(self):
        self.assertEqual(conn_str(SQL_CFG),
                         'DRIVER={ODBC Driver 17 for SQL Server};SERVER=db.local,1433;'
                         'DATABASE=plant;UID=u;PWD=secret')

    def test_conn_str_extra_keys(self):
        s = conn_str(_sql_cfg(Encrypt='yes', TrustServerCertificate='yes'))
        self.assertTrue(s.endswith(';Encrypt=yes;TrustServerCertificate=yes'))

    def test_conn_str_driver_override(self):
        s = conn_str(_sql_cfg(DRIVER='{X}'))
        self.assertTrue(s.startswith('DRIVER={X};'))
        self.assertNotIn('ODBC Driver 17', s)

    def test_conn_str_missing_required(self):
        with self.assertRaises(KeyError) as cm:
            conn_str(_sql_cfg_without('PWD'))
        self.assertIn('PWD', str(cm.exception))

    def test_conn_str_missing_sql_block(self):
        with self.assertRaises(KeyError):
            conn_str({})

    def test_conn_str_error_hides_password(self):
        with self.assertRaises(KeyError) as cm:
            conn_str(_sql_cfg_without('HOST'))
        self.assertNotIn('secret', str(cm.exception))


if __name__ == '__main__':
    unittest.main()
