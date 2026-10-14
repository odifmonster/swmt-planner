#!/usr/bin/env python

"""Coverage of `planners/infinite/swmtio` — the translation classes, the
loaders (config, by-name matching, `run_query` against a stand-in connection,
`read_csv`, `get_file_name`), `SQLQuery`, and the declared queries / tables
(pairing, column kinds, converters, the file-borne tables). All pure: no
driver, no server. See `tests/spec-files/SWMTIO_TEST_SPEC.md`."""

import datetime as dt
import os
import re
import tempfile
import unittest
from decimal import Decimal
from unittest import mock

import numpy as np
import pandas as pd

from swmtplanner.planners.infinite.swmtio import loaders, queries, tables
from swmtplanner.planners.infinite.swmtio.translate import Column, Table
from swmtplanner.planners.infinite.swmtio.loaders import (
    SQLConfigError, SourceColumnError, align_rows, connection_string,
    get_file_name, load_sql_config, parse_sql_config, read_csv, run_query,
)
from swmtplanner.planners.infinite.swmtio.queries import (
    QueryArgumentError, SQLQuery,
)
from swmtplanner.planners.infinite.swmtio.tables import (
    norm_machine, to_number, to_string, utc_to_plant,
)

QUERY_NAMES = ('ACTIVE', 'ASSIGNED', 'DOFFED', 'THREADED', 'LAST_TKT',
               'SCANNED', 'ALL_VARIANTS')


def _write(path, text, encoding='utf-8'):
    with open(path, 'w', encoding=encoding, newline='') as fh:
        fh.write(text)
    return path


# ===================================================================
# 1. Translations
# ===================================================================

class ColumnPipelineTests(unittest.TestCase):

    def test_null_replacement_default(self):
        seen = []
        col = Column('x', converter=lambda v: seen.append(v) or v)
        out = col.apply([None, float('nan'), np.nan, pd.NA, pd.NaT, 'v'])
        self.assertEqual(seen, [None] * 5 + ['v'])
        self.assertTrue(out.isna().tolist()[:5] == [True] * 5)
        self.assertEqual(out.tolist()[5], 'v')

    def test_null_replacement_custom(self):
        out = Column('x', read_na_as=0).apply([None, np.nan, 5])
        self.assertEqual(out.tolist(), [0, 0, 5])

    def test_converter_sees_replacement(self):
        seen = []

        def conv(v):
            seen.append(v)
            return v

        Column('x', converter=conv, read_na_as='').apply(['a', None, 'b'])
        self.assertEqual(seen, ['a', '', 'b'])

    def test_cast_after_conversion(self):
        out = Column('x', converter=int, dtype='int64').apply(['1', '2'])
        self.assertEqual(str(out.dtype), 'int64')
        self.assertEqual(out.tolist(), [1, 2])

    def test_no_dtype_infers(self):
        out = Column('n').apply([1, 2, 3])
        self.assertTrue(pd.api.types.is_integer_dtype(out.dtype))
        self.assertEqual(out.name, 'n')

    def test_source(self):
        self.assertEqual(Column('a').source, 'a')
        self.assertEqual(Column('a', src_name='A').source, 'A')


class TableFromTuplesTests(unittest.TestCase):

    def setUp(self):
        self.tbl = Table('t', (
            Column('a', src_name='A', converter=int, dtype='int64'),
            Column('b'),
        ))

    def test_shape(self):
        df = self.tbl.from_tuples([('1', 'x'), ('2', 'y')])
        self.assertEqual(df.columns.tolist(), ['a', 'b'])
        self.assertEqual(df['a'].tolist(), [1, 2])
        self.assertEqual(df['b'].tolist(), ['x', 'y'])
        self.assertEqual(self.tbl.names, ('a', 'b'))
        self.assertEqual(self.tbl.sources, ('A', 'b'))

    def test_length_check(self):
        with self.assertRaises(ValueError) as cm:
            self.tbl.from_tuples([('1', 'x'), ('2',)])
        self.assertIn("'t'", str(cm.exception))
        self.assertIn('row 1', str(cm.exception))
        with self.assertRaises(ValueError):
            self.tbl.from_tuples([('1', 'x', 'extra')])

    def test_empty_data(self):
        df = self.tbl.from_tuples([])
        self.assertEqual(df.columns.tolist(), ['a', 'b'])
        self.assertEqual(len(df), 0)

    def test_errors_propagate(self):
        with self.assertRaises(ValueError):
            self.tbl.from_tuples([('one', 'x')])      # int('one')
        bad_cast = Table('u', (Column('a', dtype='int64'),))
        with self.assertRaises((ValueError, TypeError)):
            bad_cast.from_tuples([('one',)])


# ===================================================================
# 2. The connection config
# ===================================================================

FULL_CFG = 'HOST=h\nPORT=1433\nDATABASE=db\nUID=u\nPWD=p\n'


class ParseSqlConfigTests(unittest.TestCase):

    def test_pairs_and_case(self):
        cfg = parse_sql_config(['KEY=value', 'Encrypt=no', 'ENCRYPT=yes'])
        self.assertEqual(cfg, {'KEY': 'value', 'Encrypt': 'no', 'ENCRYPT': 'yes'})

    def test_comments_and_blanks(self):
        cfg = parse_sql_config(['# c', '', '   ', '  # indented', 'A=1'])
        self.assertEqual(cfg, {'A': '1'})

    def test_whitespace_stripped(self):
        self.assertEqual(parse_sql_config(['  A  =  1  ']), {'A': '1'})

    def test_first_equals_splits(self):
        self.assertEqual(parse_sql_config(['a=b=c']), {'a': 'b=c'})

    def test_quoted_values(self):
        self.assertEqual(parse_sql_config(['A="p=w"'])['A'], 'p=w')
        self.assertEqual(parse_sql_config(["A='p=w'"])['A'], 'p=w')
        self.assertEqual(parse_sql_config(['A="abc\''])['A'], '"abc\'')
        self.assertEqual(parse_sql_config(['A="'])['A'], '"')

    def test_malformed(self):
        with self.assertRaises(SQLConfigError) as cm:
            parse_sql_config(['A=1', 'HOST h'], source='f.cfg')
        self.assertIn('f.cfg:2', str(cm.exception))
        with self.assertRaises(SQLConfigError):
            parse_sql_config(['=v'])


class LoadSqlConfigTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, 'sql.cfg')

    def test_explicit_path(self):
        _write(self.path, FULL_CFG + 'Encrypt=no\nEXTRA=x\n')
        cfg = load_sql_config(self.path)
        self.assertEqual(cfg, {'HOST': 'h', 'PORT': '1433', 'DATABASE': 'db',
                               'UID': 'u', 'PWD': 'p', 'Encrypt': 'no',
                               'EXTRA': 'x'})

    def test_sqlconfig_env(self):
        _write(self.path, FULL_CFG)
        with mock.patch.dict(os.environ, {'SQLCONFIG': self.path}):
            self.assertEqual(load_sql_config()['HOST'], 'h')

    def test_nothing_named(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SQLConfigError):
                load_sql_config()
        with mock.patch.dict(os.environ, {'SQLCONFIG': ''}):
            with self.assertRaises(SQLConfigError):
                load_sql_config()

    def test_missing_file(self):
        with self.assertRaises(SQLConfigError):
            load_sql_config(os.path.join(self.tmp.name, 'nope.cfg'))

    def test_required_keys(self):
        _write(self.path, 'HOST=h\nPORT=\nUID=u\nPWD=p\n')
        with self.assertRaises(SQLConfigError) as cm:
            load_sql_config(self.path)
        self.assertIn('PORT', str(cm.exception))
        self.assertIn('DATABASE', str(cm.exception))
        self.assertNotIn('UID', str(cm.exception))

    def test_optional_keys_no_default(self):
        _write(self.path, FULL_CFG)
        cfg = load_sql_config(self.path)
        self.assertNotIn('TrustServerCertificate', cfg)
        self.assertNotIn('Encrypt', cfg)


class ConnectionStringTests(unittest.TestCase):

    def test_exact_text(self):
        cfg = {'HOST': 'h', 'PORT': '1433', 'DATABASE': 'db', 'UID': 'u',
               'PWD': 'p=w'}
        self.assertEqual(
            connection_string(cfg),
            'DRIVER={ODBC Driver 17 for SQL Server};SERVER=h,1433;'
            'DATABASE=db;UID=u;PWD=p=w;')

    def test_optional_segments(self):
        cfg = {'HOST': 'h', 'PORT': '1', 'DATABASE': 'd', 'UID': 'u', 'PWD': 'p',
               'Encrypt': 'no', 'TrustServerCertificate': 'yes', 'EXTRA': 'x'}
        s = connection_string(cfg)
        self.assertTrue(s.endswith('PWD=p;TrustServerCertificate=yes;Encrypt=no;'))
        self.assertNotIn('EXTRA', s)
        only_enc = dict(cfg)
        del only_enc['TrustServerCertificate']
        self.assertTrue(connection_string(only_enc).endswith('PWD=p;Encrypt=no;'))


# ===================================================================
# 3. Matching a source to a table
# ===================================================================

class AlignRowsTests(unittest.TestCase):

    def setUp(self):
        self.tbl = Table('t', (Column('a', src_name='A'), Column('b')))

    def test_reorder_by_name(self):
        rows = align_rows(['b', 'A'], [(1, 2), (3, 4)], self.tbl, 'src')
        self.assertEqual(rows, [(2, 1), (4, 3)])

    def test_extras_dropped(self):
        rows = align_rows(['x', 'A', 'b'], [(9, 1, 2)], self.tbl, 'src')
        self.assertEqual(rows, [(1, 2)])

    def test_missing(self):
        with self.assertRaises(SourceColumnError) as cm:
            align_rows(['a', 'b'], [], self.tbl, 'the-source')
        msg = str(cm.exception)
        self.assertIn("'A'", msg)
        self.assertIn("'t'", msg)
        self.assertIn('the-source', msg)


# ===================================================================
# 4. run_query (stand-in connection)
# ===================================================================

class _FakeCursor:
    def __init__(self, description, rows, fail=None):
        self.description = description
        self.rows = rows
        self.fail = fail
        self.executed = []

    def execute(self, sql):
        self.executed.append(sql)
        if self.fail is not None:
            raise self.fail

    def fetchall(self):
        return list(self.rows)


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


class RunQueryTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = _write(os.path.join(self.tmp.name, 'sql.cfg'), FULL_CFG)
        self.tbl = Table('t', (Column('a', src_name='A', converter=int,
                                      dtype='int64'), Column('b')))

    def _patch(self, cursor):
        conn = _FakeConn(cursor)
        calls = []

        def connect(cs):
            calls.append(cs)
            return conn

        patcher = mock.patch.object(loaders, '_connect', connect)
        patcher.start()
        self.addCleanup(patcher.stop)
        return conn, calls

    def test_wiring(self):
        cur = _FakeCursor([('b',), ('x',), ('A',)], [('p', 0, '1'), ('q', 0, '2')])
        conn, calls = self._patch(cur)
        df = run_query('SELECT {not} substituted', self.tbl, self.cfg)
        self.assertEqual(calls, [connection_string(load_sql_config(self.cfg))])
        self.assertEqual(cur.executed, ['SELECT {not} substituted'])
        self.assertEqual(df.columns.tolist(), ['a', 'b'])
        self.assertEqual(df['a'].tolist(), [1, 2])
        self.assertEqual(df['b'].tolist(), ['p', 'q'])
        self.assertTrue(conn.closed)

    def test_closed_on_failure(self):
        cur = _FakeCursor([], [], fail=RuntimeError('boom'))
        conn, _ = self._patch(cur)
        with self.assertRaises(RuntimeError):
            run_query('SELECT 1', self.tbl, self.cfg)
        self.assertTrue(conn.closed)

    def test_missing_column(self):
        cur = _FakeCursor([('b',)], [('p',)])
        conn, _ = self._patch(cur)
        with self.assertRaises(SourceColumnError):
            run_query('SELECT 1', self.tbl, self.cfg)
        self.assertTrue(conn.closed)


# ===================================================================
# 5. read_csv
# ===================================================================

class ReadCsvTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tbl = Table('t', (Column('a', src_name='A'), Column('b')))

    def _file(self, text, name='in.csv', encoding='utf-8'):
        return _write(os.path.join(self.tmp.name, name), text, encoding)

    def test_header_match_order_free(self):
        df = read_csv(self._file('b,x,A\n1,9,2\n'), self.tbl)
        self.assertEqual(df.columns.tolist(), ['a', 'b'])
        self.assertEqual(df.iloc[0].tolist(), ['2', '1'])

    def test_separator(self):
        df = read_csv(self._file('A\tb\n1\t2\n'), self.tbl, sep='\t')
        self.assertEqual(df.iloc[0].tolist(), ['1', '2'])

    def test_no_inference(self):
        df = read_csv(self._file('A,b\n1,2.0\n'), self.tbl)
        self.assertEqual(df.iloc[0].tolist(), ['1', '2.0'])

    def test_nulls(self):
        df = read_csv(self._file('A,b\n,None\nNA,x\n'), self.tbl)
        self.assertTrue(pd.isna(df['a'][0]) and pd.isna(df['b'][0]))
        self.assertEqual(df['a'][1], 'NA')
        df = read_csv(self._file('A,b\n,None\nNA,x\n'), self.tbl, na_values=('NA',))
        self.assertEqual(df['a'][0], '')
        self.assertEqual(df['b'][0], 'None')
        self.assertTrue(pd.isna(df['a'][1]))

    def test_bom_and_blank_tail(self):
        df = read_csv(self._file('A,b\n1,2\n\n', encoding='utf-8-sig'), self.tbl)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.columns.tolist(), ['a', 'b'])

    def test_no_header(self):
        with self.assertRaises(SourceColumnError):
            read_csv(self._file(''), self.tbl)

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            read_csv(os.path.join(self.tmp.name, 'nope.csv'), self.tbl)


# ===================================================================
# 6. get_file_name
# ===================================================================

class GetFileNameTests(unittest.TestCase):

    def test_dated(self):
        self.assertEqual(get_file_name('machine_status', 'tsv', dt.date(2026, 10, 14)),
                         'machine_status_20261014.tsv')

    def test_undated(self):
        self.assertEqual(get_file_name('x', 'csv', dt.date(2026, 10, 14), is_dated=False),
                         'x.csv')

    def test_default_today(self):
        fake = mock.Mock(today=mock.Mock(return_value=dt.date(2026, 1, 2)))
        with mock.patch.object(loaders, 'date', fake):
            self.assertEqual(get_file_name('y', 'txt'), 'y_20260102.txt')


# ===================================================================
# 7. SQLQuery
# ===================================================================

class SQLQueryTests(unittest.TestCase):

    def test_rendering(self):
        q = SQLQuery('WHERE d >= {} AND d < {}', 2, "'%Y-%m-%d'")
        self.assertEqual(q.get_query(dt.date(2026, 10, 1), dt.date(2026, 10, 14)),
                         "WHERE d >= '2026-10-01' AND d < '2026-10-14'")

    def test_date_or_datetime(self):
        q = SQLQuery('{}', 1, '%Y-%m-%d %H:%M:%S')
        self.assertEqual(q.get_query(dt.datetime(2026, 10, 1, 6, 30, 5)),
                         '2026-10-01 06:30:05')
        self.assertEqual(q.get_query(dt.date(2026, 10, 1)), '2026-10-01 00:00:00')

    def test_no_arguments(self):
        self.assertEqual(SQLQuery('SELECT 1', 0, None).get_query(), 'SELECT 1')

    def test_wrong_count(self):
        q = SQLQuery('{}', 1, '%Y')
        with self.assertRaises(QueryArgumentError):
            q.get_query()
        with self.assertRaises(QueryArgumentError):
            q.get_query(dt.date.today(), dt.date.today())

    def test_literal_braces(self):
        q = SQLQuery('{{fn NOW()}} {}', 1, '%Y')
        self.assertEqual(q.get_query(dt.date(2026, 1, 1)), '{fn NOW()} 2026')

    def test_definition_time_checks(self):
        with self.assertRaises(ValueError):
            SQLQuery('{}', 1, None)
        with self.assertRaises(ValueError):
            SQLQuery('x', 0, '%Y')
        with self.assertRaises(ValueError):
            SQLQuery('x', -1, '%Y')


# ===================================================================
# 8. The declared queries and tables
# ===================================================================

def _select_aliases(raw):
    """The `AS "…"` aliases of a query's final SELECT list, in order."""
    sel = max(raw.rfind(') SELECT'), raw.rfind('\nSELECT'), 0)
    frm = min(i for i in (raw.find('\nFROM', sel), raw.find('\n    FROM', sel))
              if i != -1)
    return re.findall(r'AS "([^"]+)"', raw[sel:frm])


def _kind(col):
    if col.converter is utc_to_plant and col.dtype is None:
        return 'timestamp'
    if col.converter is to_string and col.dtype == tables.STRING_DTYPE:
        return 'string'
    if col.converter is to_number and col.dtype == tables.COUNT_DTYPE:
        return 'count'
    if col.converter is to_number and col.dtype == tables.NUMBER_DTYPE:
        return 'number'
    if col.converter is norm_machine and col.dtype == tables.STRING_DTYPE:
        return 'string'
    return None


def _base(name):
    return re.sub(r'^bar[1-4]_', '', name)


class QueryTablePairingTests(unittest.TestCase):

    def test_every_query_has_its_table(self):
        for name in QUERY_NAMES:
            self.assertIsInstance(getattr(queries, name), SQLQuery, name)
            tbl = getattr(tables, name)
            self.assertIsInstance(tbl, Table, name)
            self.assertEqual(tbl.name, name)

    def test_columns_match_select_list(self):
        for name in QUERY_NAMES:
            aliases = _select_aliases(getattr(queries, name).raw_str)
            self.assertTrue(aliases, name)
            self.assertEqual(getattr(tables, name).names, tuple(aliases), name)

    def test_date_arguments(self):
        for name in ('DOFFED', 'SCANNED'):
            q = getattr(queries, name)
            self.assertEqual(q.num_args, 1, name)
            sql = q.get_query(dt.date(2026, 10, 7))
            self.assertIn('DATETIMEFROMPARTS(2026, 10, 07, 00, 00, 00, 0)', sql)
            self.assertNotIn('{}', sql)
        for name in set(QUERY_NAMES) - {'DOFFED', 'SCANNED'}:
            q = getattr(queries, name)
            self.assertEqual(q.num_args, 0, name)
            self.assertNotIn('{}', q.raw_str, name)
            self.assertEqual(q.get_query(), q.raw_str, name)


class ColumnKindTests(unittest.TestCase):

    ALL = QUERY_NAMES + ('FLOOR_STATUS', 'MACHINE_STATUS', 'RACKS')

    def test_four_kinds_only(self):
        for name in self.ALL:
            for col in getattr(tables, name).columns:
                self.assertIsNotNone(_kind(col), f'{name}.{col.name}')

    def test_consistent_across_tables(self):
        kinds = {}
        for name in self.ALL:
            for col in getattr(tables, name).columns:
                if name == 'FLOOR_STATUS' and col.name == 'bar':
                    continue      # the one stated exception: text (`2/3`)
                kinds.setdefault(_base(col.name), set()).add(_kind(col))
        for base, ks in kinds.items():
            self.assertEqual(len(ks), 1, f'{base}: {ks}')
        self.assertEqual(_kind(tables.FLOOR_STATUS.columns[1]), 'string')
        self.assertEqual({b for b, k in kinds.items() if 'timestamp' in k},
                         {'rcv_date', 'assign_date', 'assn_ts', 'start_ts',
                          'end_ts', 'scan_ts'})
        self.assertEqual({b for b, k in kinds.items() if 'count' in k},
                         {'bar', 'beams', 'nbeams', 'ends'})

    def test_utc_to_plant(self):
        self.assertEqual(utc_to_plant(dt.datetime(2026, 10, 14, 12, 0)),
                         dt.datetime(2026, 10, 14, 8, 0))
        self.assertEqual(utc_to_plant(dt.datetime(2026, 1, 14, 12, 0)),
                         dt.datetime(2026, 1, 14, 7, 0))
        aware = dt.datetime(2026, 10, 14, 12, 0,
                            tzinfo=dt.timezone(dt.timedelta(hours=2)))
        self.assertEqual(utc_to_plant(aware), dt.datetime(2026, 10, 14, 6, 0))
        self.assertEqual(utc_to_plant('2026-10-14T12:00:00'),
                         dt.datetime(2026, 10, 14, 8, 0))
        self.assertEqual(utc_to_plant('2026-10-14 12:00:00+00:00'),
                         dt.datetime(2026, 10, 14, 8, 0))
        self.assertIsNone(utc_to_plant(None))

    def test_to_number(self):
        self.assertEqual(to_number(3), 3.0)
        self.assertEqual(to_number(Decimal('743.72')), 743.72)
        self.assertEqual(to_number('70'), 70.0)
        self.assertIsNone(to_number(None))
        with self.assertRaises(ValueError):
            to_number('abc')

    def test_to_string(self):
        self.assertEqual(to_string(70150), '70150')
        self.assertEqual(to_string(2.0), '2')
        self.assertEqual(to_string(2.5), '2.5')
        self.assertEqual(to_string('B20806C'), 'B20806C')
        self.assertIsNone(to_string(None))

    def test_norm_machine(self):
        for raw in ('b8', 'B8', 'B08', ' B8 '):
            self.assertEqual(norm_machine(raw), 'B08', raw)
        self.assertIsNone(norm_machine(None))
        for bad in ('B', 'B123', 'BB8', '8'):
            with self.assertRaises(ValueError, msg=bad):
                norm_machine(bad)

    def test_same_frame_from_both_sources(self):
        db_rows = [('N03', 1, Decimal('743.72'), 2, 'S1234', 70150, 'Unifi',
                    Decimal('70')),
                   ('N04', None, None, None, None, None, None, None)]
        csv_rows = [('N03', '1', '743.72', '2', 'S1234', '70150', 'Unifi', '70'),
                    ('N04', None, None, None, None, None, None, None)]
        a = tables.THREADED.from_tuples(db_rows)
        b = tables.THREADED.from_tuples(csv_rows)
        pd.testing.assert_frame_equal(a, b)
        self.assertEqual(str(a['bar'].dtype), 'Int64')
        self.assertEqual(str(a['rem_lbs'].dtype), 'float64')
        self.assertEqual(str(a['merge'].dtype), 'string')
        self.assertEqual(a['merge'][0], '70150')
        self.assertTrue(pd.isna(a['bar'][1]) and pd.isna(a['merge'][1]))
        with self.assertRaises((TypeError, ValueError)):
            tables.THREADED.from_tuples([('N03', 1.5, 1, 1, 'x', 'm', 'v', 1)])


class FileTableTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _tsv(self, name, text):
        return _write(os.path.join(self.tmp.name, name), text)

    def test_floor_status(self):
        self.assertEqual(tables.FLOOR_STATUS.names, ('machine', 'bar', 'status'))
        df = read_csv(self._tsv('f.tsv', 'machine\tbar\tstatus\nb8\t1\tempty\nE7\t2/3\tthreading\n'),
                      tables.FLOOR_STATUS, sep='\t')
        self.assertEqual(df['machine'].tolist(), ['B08', 'E07'])
        self.assertEqual(df['bar'].tolist(), ['1', '2/3'])
        self.assertTrue(all(str(d) == 'string' for d in df.dtypes))

    def test_machine_status(self):
        self.assertIs(tables.MACHINE_STATUS.columns, tables.LAST_TKT.columns)
        header = '\t'.join(tables.LAST_TKT.names)
        row = ['B08', 'B08-0991', '2026-10-13 07:11:19.150000', 'AU5429D-HASH/16', '4']
        row += ['47999', '2609', 'Ashfar', '40', '14.5'] * 3
        row += ['None'] * 5 + ['24.77', '2987']
        df = read_csv(self._tsv('m.tsv', header + '\n' + '\t'.join(row) + '\n'),
                      tables.MACHINE_STATUS, sep='\t')
        self.assertEqual(df['scan_ts'][0], pd.Timestamp('2026-10-13 03:11:19.150'))
        self.assertEqual(df['nbeams'][0], 4)
        self.assertEqual(df['bar1_merge'][0], '2609')
        self.assertEqual(df['bar1_pct'][0], 14.5)
        self.assertTrue(pd.isna(df['bar4_set_no'][0]) and pd.isna(df['bar4_pct'][0]))
        self.assertEqual(df['racks'][0], 2987.0)

    def test_racks(self):
        self.assertEqual(tables.RACKS.names, ('machine', 'racks'))
        self.assertEqual(tables.RACKS.sources, ('MC', 'Racks'))
        df = read_csv(self._tsv('r.tsv', 'MC\tRacks\nB8\t2987\n e07 \t\n'),
                      tables.RACKS, sep='\t')
        self.assertEqual(df['machine'].tolist(), ['B08', 'E07'])
        self.assertEqual(df['racks'][0], 2987.0)
        self.assertTrue(pd.isna(df['racks'][1]))
        self.assertEqual(str(df['racks'].dtype), 'float64')


if __name__ == '__main__':
    unittest.main()
