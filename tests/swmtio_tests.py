#!/usr/bin/env python

"""Coverage of `planners/infinite/swmtio` — the translation classes, the
loaders (config, by-name matching, `run_query` against a stand-in connection,
`read_csv`, `get_file_name`), `SQLQuery`, the declared queries / tables
(pairing, column kinds, converters, the file-borne tables), and `loadinputs`
(conventions, the four generators, `make_input_file` / `plan inputs`). All
pure: no driver, no server. See `tests/spec-files/SWMTIO_TEST_SPEC.md`."""

import datetime as dt
import json
import logging
import os
import re
import tempfile
import unittest
from decimal import Decimal
from unittest import mock

import numpy as np
import pandas as pd
import typer
from typer.testing import CliRunner

from swmtplanner.planners.infinite.swmtio import loaders, queries, tables
from swmtplanner.planners.infinite.swmtio.loadinputs import (
    InputName, compute_runout, gen_doffed, gen_inventory, gen_machines,
    make_input_file,
)
from swmtplanner.planners.infinite.swmtio.loadinputs import make_input as make_input_mod
from swmtplanner.planners.infinite.swmtio.loadinputs.common import (
    as_float, as_int, as_str, from_iso_plant, is_null, iso_plant,
    planner_machine_id, to_plant_naive, log as LOADINPUTS_LOG,
)
from swmtplanner.planners.infinite.swmtio.loadinputs.machines import bar_groups
from swmtplanner.planners.infinite.swmtio.loadinputs.runout import parse_bars
from swmtplanner.planners.infinite.swmtio.translate import Column, Table
from swmtplanner.planners.infinite.swmtio.loaders import (
    SQLConfigError, SourceColumnError, align_rows, connection_string,
    get_file_name, load_sql_config, parse_sql_config, read_csv, run_query,
)
from swmtplanner.planners.infinite.swmtio.queries import (
    QueryArgumentError, SQLQuery, render_date,
)
from swmtplanner.planners.infinite.swmtio.tables import (
    norm_machine, to_number, to_string, utc_to_plant,
)

QUERY_NAMES = ('ACTIVE', 'ASSIGNED', 'DOFFED', 'THREADED', 'LAST_TKT',
               'TKTS_SINCE', 'THREADINGS_SINCE', 'SCANNED', 'ALL_VARIANTS')
DATED_QUERIES = ('DOFFED', 'TKTS_SINCE', 'THREADINGS_SINCE', 'SCANNED')


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

    def test_unpadded_directives(self):
        when = dt.datetime(2026, 1, 7, 6, 5, 4)
        self.assertEqual(render_date(when, '%-m, %-d, %-H, %-M, %-S'), '1, 7, 6, 5, 4')
        self.assertEqual(render_date(when, '%m/%-m'), '01/1')
        self.assertEqual(render_date(when, '100%% %%-d'), '100% %-d')
        with self.assertRaises(ValueError):
            render_date(when, '%-b')
        self.assertEqual(SQLQuery('{}', 1, '%Y-%-m-%-d').get_query(when), '2026-1-7')

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
        self.assertIs(tables.TKTS_SINCE.columns, tables.DOFFED.columns)

    def test_columns_match_select_list(self):
        for name in QUERY_NAMES:
            aliases = _select_aliases(getattr(queries, name).raw_str)
            self.assertTrue(aliases, name)
            self.assertEqual(getattr(tables, name).names, tuple(aliases), name)

    def test_date_arguments(self):
        for name in DATED_QUERIES:
            q = getattr(queries, name)
            self.assertEqual(q.num_args, 1, name)
            sql = q.get_query(dt.date(2026, 10, 7))
            self.assertIn('DATETIMEFROMPARTS(2026, 10, 7, 0, 0, 0, 0)', sql)
            self.assertNotIn('{}', sql)
        for name in set(QUERY_NAMES) - set(DATED_QUERIES):
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
                         {'bar', 'beams', 'nbeams', 'ends', 'denier'})

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
        self.assertEqual(tables.MACHINE_STATUS.columns[:-1], tables.LAST_TKT.columns)
        self.assertEqual(tables.MACHINE_STATUS.names[-1], 'status')
        header = '\t'.join(tables.MACHINE_STATUS.names)
        row = ['B08', 'B08-0991', '2026-10-13 07:11:19.150000', 'AU5429D-HASH/16', '4']
        row += ['47999', '2609', 'Ashfar', '40', '14.5'] * 3
        row += ['None'] * 5 + ['24.77', '2987', 'running']
        df = read_csv(self._tsv('m.tsv', header + '\n' + '\t'.join(row) + '\n'),
                      tables.MACHINE_STATUS, sep='\t')
        self.assertEqual(df['scan_ts'][0], pd.Timestamp('2026-10-13 03:11:19.150'))
        self.assertEqual(df['nbeams'][0], 4)
        self.assertEqual(df['bar1_merge'][0], '2609')
        self.assertEqual(df['bar1_pct'][0], 14.5)
        self.assertTrue(pd.isna(df['bar4_set_no'][0]) and pd.isna(df['bar4_pct'][0]))
        self.assertEqual(df['racks'][0], 2987.0)
        self.assertEqual(df['status'][0], 'running')

    def test_racks(self):
        self.assertEqual(tables.RACKS.names, ('machine', 'racks'))
        self.assertEqual(tables.RACKS.sources, ('MC', 'Racks'))
        df = read_csv(self._tsv('r.tsv', 'MC\tRacks\nB8\t2987\n e07 \t\n'),
                      tables.RACKS, sep='\t')
        self.assertEqual(df['machine'].tolist(), ['B08', 'E07'])
        self.assertEqual(df['racks'][0], 2987.0)
        self.assertTrue(pd.isna(df['racks'][1]))
        self.assertEqual(str(df['racks'].dtype), 'float64')


# ===================================================================
# 9. loadinputs conventions
# ===================================================================

LOG_NAME = 'swmtplanner.swmtio.loadinputs'
T = pd.Timestamp


class _QuietLogs(unittest.TestCase):
    """Keep the generators' reports off the test output: a NullHandler on
    the loadinputs logger while a test runs (`assertLogs` still sees them)."""

    def setUp(self):
        self._null = logging.NullHandler()
        LOADINPUTS_LOG.addHandler(self._null)

    def tearDown(self):
        LOADINPUTS_LOG.removeHandler(self._null)


class ConventionsTests(unittest.TestCase):

    def test_planner_machine_id(self):
        for raw in ('B08', 'b8', ' B08 '):
            self.assertEqual(planner_machine_id(raw), 'B8')
        self.assertEqual(planner_machine_id('N1'), 'N1')
        self.assertEqual(planner_machine_id('K10'), 'K10')
        for bad in ('8', 'B', ''):
            with self.assertRaises(ValueError):
                planner_machine_id(bad)

    def test_is_null(self):
        for v in (None, float('nan'), pd.NA, pd.NaT):
            self.assertTrue(is_null(v))
        for v in (0, '', 'None', T('2026-10-10')):
            self.assertFalse(is_null(v))

    def test_iso_plant(self):
        self.assertEqual(iso_plant(dt.datetime(2026, 10, 13, 12, 14, 38, 500)),
                         '2026-10-13T12:14:38-04:00')
        self.assertEqual(iso_plant(dt.datetime(2026, 1, 13, 12, 14, 38)),
                         '2026-01-13T12:14:38-05:00')
        self.assertEqual(iso_plant(T('2026-10-13 12:14:38')), '2026-10-13T12:14:38-04:00')
        aware = dt.datetime(2026, 10, 13, 16, 14, 38, tzinfo=dt.timezone.utc)
        self.assertEqual(iso_plant(aware), '2026-10-13T12:14:38-04:00')
        self.assertIsNone(iso_plant(None))
        self.assertIsNone(iso_plant(pd.NaT))
        with self.assertRaises(TypeError):
            iso_plant('2026-10-13')

    def test_from_iso_plant(self):
        naive = dt.datetime(2026, 10, 13, 12, 14, 38)
        self.assertEqual(from_iso_plant(iso_plant(naive)), naive)
        self.assertEqual(from_iso_plant('2026-10-13T16:14:38+00:00'), naive)

    def test_cell_conversions(self):
        for fn in (as_int, as_float, as_str):
            for v in (None, float('nan'), pd.NA):
                self.assertIsNone(fn(v))
        self.assertEqual(as_int(2.0), 2)
        self.assertEqual(as_float(Decimal('1.5')), 1.5)
        self.assertEqual(as_str(5), '5')
        self.assertEqual(to_plant_naive(T('2026-10-13 12:14:38')),
                         dt.datetime(2026, 10, 13, 12, 14, 38))
        self.assertIsNone(to_plant_naive(None))


# ===================================================================
# 10. gen_inventory
# ===================================================================

ACTIVE_COLS = ('set_no', 'rcv_date', 'assign_date', 'lbs', 'beams', 'ends', 'merge',
               'vendor', 'denier', 'luster', 'yarn_type', 'comments', 'beam_size')
ASSIGNED_COLS = ('set_no', 'assn_ts', 'merge', 'vendor', 'lbs', 'beams', 'ends',
                 'luster', 'yarn_type', 'machine', 'bar', 'beam_size')


def _active(*rows):
    return pd.DataFrame(list(rows), columns=ACTIVE_COLS, dtype=object)


def _assigned(*rows):
    return pd.DataFrame(list(rows), columns=ASSIGNED_COLS, dtype=object)


def _floor(*rows):
    return pd.DataFrame(list(rows), columns=('machine', 'bar', 'status'), dtype=object)


class GenInventoryTests(_QuietLogs):

    RCV = T('2026-09-14 21:30:42')

    def _active(self):
        return _active(
            ('1-1202', self.RCV, T('2026-10-01 08:00'), 2197.0, 4, 1300, '6268G',
             'Hyosung', 75, 'SDBK', 'TEXT POLY', None, '30 x 42'),
            ('2-0001', self.RCV, None, 100.0, 2, 500, 'm', 'v', None, 'l', 'd', None, None),
            ('3-0002', self.RCV, None, 100.0, 2, 500, 'm', 'v', 70, 'l', 'd', 'bad', 'z'),
            ('4-0003', self.RCV, None, 100.0, None, 500, 'm', 'v', 70, 'l', 'd', None, 'z'),
        )

    def test_filter(self):
        inv, _ = gen_inventory(self._active(), _assigned(), _floor())
        self.assertEqual([r['set_no'] for r in inv], ['1-1202', '2-0001'])

    def test_inventory_record(self):
        inv, _ = gen_inventory(self._active(), _assigned(), _floor())
        self.assertEqual(inv[0], {
            'set_no': '1-1202', 'received': '2026-09-14T21:30:42-04:00', 'assigned': True,
            'merge': '6268G', 'vendor': 'Hyosung', 'lbs': 2197.0, 'beams': 4, 'ends': 1300,
            'denier': 75, 'luster': 'SDBK', 'desc': 'TEXT POLY', 'size': '30 x 42',
        })
        self.assertIs(inv[1]['assigned'], False)
        self.assertIsNone(inv[1]['denier'])
        self.assertIsNone(inv[1]['size'])
        self.assertIsInstance(inv[0]['beams'], int)
        self.assertIsInstance(inv[0]['lbs'], float)

    def _assigned(self):
        def row(set_no, ts, machine, bar):
            return (set_no, T(ts), 'm', 'v', 10.0, 2, 500, 'l', 'd', machine, bar, 's')
        return _assigned(
            row('S3', '2026-10-02 09:00', 'B08', 2),
            row('S1', '2026-10-01 09:00', 'B08', 1),
            row('S4', '2026-10-01 10:00', 'B08', 3),
            row('S2', '2026-10-03 09:00', 'B08', 1),
            row('S5', '2026-10-05 09:00', 'A02', 1),
        )

    def test_queue_order(self):
        _, assigned = gen_inventory(_active(), self._assigned(), _floor())
        self.assertEqual([(r['machine'], r['bar'], r['set_no']) for r in assigned],
                         [('A2', 1, 'S5'), ('B8', 1, 'S1'), ('B8', 1, 'S2'),
                          ('B8', 2, 'S3'), ('B8', 3, 'S4')])
        self.assertEqual(tuple(assigned[1]), (
            'set_no', 'assigned', 'merge', 'vendor', 'lbs', 'beams', 'ends', 'luster',
            'desc', 'machine', 'bar', 'status', 'size'))
        self.assertEqual(assigned[1]['assigned'], '2026-10-01T09:00:00-04:00')
        self.assertIsInstance(assigned[1]['bar'], int)

    def test_status_join(self):
        floor = _floor(('B08', '1', 'threaded'), ('B08', '2/3', 'staged'))
        _, assigned = gen_inventory(_active(), self._assigned(), floor)
        self.assertEqual([r['status'] for r in assigned],
                         ['inventory', 'threaded', 'threaded', 'staged', 'staged'])

    def test_floor_status_map_skips_nulls(self):
        floor = _floor(('A02', None, 'x'), (None, '1', 'x'), ('B08', '4', None),
                       ('B08', '1', 'threaded'))
        _, assigned = gen_inventory(_active(), self._assigned(), floor)
        self.assertEqual([r['status'] for r in assigned],
                         ['inventory', 'threaded', 'threaded', 'inventory', 'inventory'])

    def test_empty(self):
        self.assertEqual(gen_inventory(_active(), _assigned(), _floor()), ([], []))


# ===================================================================
# 11. gen_doffed
# ===================================================================

DOFFED_COLS = ('machine', 'ticket', 'start_ts', 'end_ts', 'style', 'rack_wt', 'racks')
DAY = '2026-10-10 '


def _rolls(*rows):
    """`(machine, ticket, start 'HH:MM', end 'HH:MM' | None, racks[, rack_wt])`."""
    out = []
    for machine, ticket, start, end, racks, *rest in rows:
        rack_wt = rest[0] if rest else 1200.0
        out.append((machine, ticket,
                    None if start is None else T(DAY + start),
                    None if end is None else T(DAY + end),
                    'S', rack_wt, racks))
    return pd.DataFrame(out, columns=DOFFED_COLS, dtype=object)


def _doff(hhmm):
    return f'2026-10-10T{hhmm}:00-04:00'


class GenDoffedTests(_QuietLogs):

    def setUp(self):
        super().setUp()
        self.scanned = _rolls(('B08', 'A', '08:00', '10:00', 10.0),
                              ('B08', 'B', '10:00', None, 20.0))

    def _summary(self, out, machine):
        return [(r['ticket_no'], r['doff_ts']) for r in out[machine]]

    def test_record_and_open_rolls(self):
        out = gen_doffed(self.scanned, _rolls())
        self.assertEqual(out, {'B8': [{'ticket_no': 'A', 'style': 'S', 'racks': 10.0,
                                       'lbs': 120.0, 'doff_ts': _doff('10:00')}]})
        self.assertEqual(gen_doffed(_rolls(('E08', 'R', '08:00', None, 1.0)), _rolls()), {})

    def test_order(self):
        scanned = _rolls(('C08', 'Z', '09:00', '10:00', 1.0), ('C08', 'Y', '08:00', '09:00', 1.0),
                         ('A02', 'W', '08:00', '09:00', 1.0))
        out = gen_doffed(scanned, _rolls())
        self.assertEqual(list(out), ['A2', 'C8'])
        self.assertEqual([r['ticket_no'] for r in out['C8']], ['Y', 'Z'])

    def test_splice_inside(self):
        extras = _rolls(('B08', 'X', '08:30', '09:00', 5.0))
        out = gen_doffed(self.scanned, extras)
        self.assertEqual(self._summary(out, 'B8'), [('A', _doff('08:30')), ('X', _doff('09:00'))])
        self.assertEqual(out['B8'][1]['lbs'], 60.0)
        # Hosts are the scanned rolls' original spans: 09:30 is inside A's.
        extras = _rolls(('B08', 'X', '08:30', '09:00', 5.0), ('B08', 'X2', '09:30', '09:45', 5.0),
                        ('B08', 'Y', '11:00', '12:00', 7.0))
        out = gen_doffed(self.scanned, extras)
        self.assertEqual([t for t, _ in self._summary(out, 'B8')], ['A', 'X', 'X2', 'B', 'Y'])
        self.assertEqual(dict(self._summary(out, 'B8'))['A'], _doff('08:30'))
        self.assertEqual(dict(self._summary(out, 'B8'))['B'], _doff('11:00'))

    def test_two_in_one_span(self):
        scanned = _rolls(('D08', 'P', '08:00', '10:00', 1.0), ('D08', 'Q', '10:00', '12:00', 1.0))
        extras = _rolls(('D08', 'E4', '08:40', '08:50', 1.0), ('D08', 'E3', '08:10', '08:20', 1.0))
        out = gen_doffed(scanned, extras)
        self.assertEqual(self._summary(out, 'D8'),
                         [('P', _doff('08:10')), ('E3', _doff('08:20')),
                          ('E4', _doff('08:50')), ('Q', _doff('12:00'))])

    def test_after_the_last(self):
        out = gen_doffed(self.scanned, _rolls(('B08', 'Y', '11:00', '12:00', 7.0)))
        self.assertEqual(self._summary(out, 'B8'),
                         [('A', _doff('10:00')), ('B', _doff('11:00')), ('Y', _doff('12:00'))])
        self.assertEqual(out['B8'][2]['lbs'], 84.0)
        out = gen_doffed(self.scanned, _rolls(('B08', 'Y', '11:00', None, 7.0)))
        self.assertEqual(self._summary(out, 'B8'), [('A', _doff('10:00')), ('B', _doff('11:00'))])

    def test_no_scans(self):
        extras = _rolls(('C08', 'Z2', '09:00', '10:00', 1.0), ('C08', 'Z1', '08:00', '09:00', 1.0))
        out = gen_doffed(_rolls(), extras)
        self.assertEqual(self._summary(out, 'C8'), [('Z1', _doff('09:00')), ('Z2', _doff('10:00'))])

    def test_unplaceable(self):
        scanned = _rolls(('D08', 'P', '08:00', '10:00', 1.0), ('D08', 'Q', '10:00', '12:00', 1.0))
        extras = _rolls(('D08', 'E1', '07:00', '07:30', 1.0), ('D08', 'E2', '09:30', '10:30', 1.0))
        with self.assertLogs(LOG_NAME, 'WARNING') as logs:
            out = gen_doffed(scanned, extras)
        self.assertEqual(self._summary(out, 'D8'), [('P', _doff('10:00')), ('Q', _doff('12:00'))])
        self.assertEqual(sorted(t for t in ('E1', 'E2') for m in logs.output if f'ticket {t}' in m),
                         ['E1', 'E2'])

    def test_already_scanned(self):
        extras = _rolls(('B08', 'A', '08:00', '10:00', 10.0))
        out = gen_doffed(self.scanned, extras)
        self.assertEqual(self._summary(out, 'B8'), [('A', _doff('10:00'))])

    def test_missing_weight(self):
        scanned = _rolls(('D08', 'Q', '10:00', '12:00', 1.0, None), ('D08', 'R', '12:00', '13:00', None))
        with self.assertLogs(LOG_NAME, 'WARNING') as logs:
            out = gen_doffed(scanned, _rolls())
        self.assertEqual([r['lbs'] for r in out['D8']], [None, None])
        self.assertEqual(len(logs.output), 2)

    def test_null_start_skipped(self):
        scanned = _rolls(('B08', 'A', '08:00', '10:00', 10.0), ('B08', 'N', None, '11:00', 1.0))
        extras = _rolls(('B08', 'M', None, '09:00', 1.0))
        out = gen_doffed(scanned, extras)
        self.assertEqual(self._summary(out, 'B8'), [('A', _doff('10:00'))])


# ===================================================================
# 12. compute_runout
# ===================================================================

THREADING_COLS = ('machine', 'item', 'set_no', 'bars', 'racks', 'start_ts', 'init_lbs',
                  'merge', 'vendor')
THREADED_AT = T('2026-10-10 08:00')


def _variants(*extra):
    """Style `S` (12 lbs/rack; bar shares 40/30/30) plus any `(variant, ends,
    merges, pcts)` extras; every per-bar field the generators read."""
    rows = [('S', 1200.0, [1300, 650, 650, None], ['2609', 'A716B', 'A716B', None],
             [40.0, 30.0, 30.0, None])]
    rows += [(v, 1200.0, e, m, p) for v, e, m, p in extra]
    out = []
    for variant, rack_wt, ends, merges, pcts in rows:
        r = {'variant': variant, 'rack_wt': rack_wt}
        for n in (1, 2, 3, 4):
            r[f'bar{n}_ends'] = ends[n - 1]
            r[f'bar{n}_merge'] = merges[n - 1]
            r[f'bar{n}_pct'] = pcts[n - 1]
        out.append(r)
    return pd.DataFrame(out).astype(object)


def _threadings(*rows):
    return pd.DataFrame(list(rows), columns=THREADING_COLS, dtype=object)


def _racks(**per_machine):
    return pd.DataFrame({'machine': list(per_machine), 'racks': list(per_machine.values())},
                        dtype=object)


def _last_tkt(*rows):
    """`(machine, style, {bar: (set_no, merge, vendor)})` rows, in LAST_TKT's names."""
    out = []
    for machine, style, sets in rows:
        r = {n: None for n in tables.LAST_TKT.names}
        r['machine'], r['style'] = machine, style
        for bar, (set_no, merge, vendor) in sets.items():
            r[f'bar{bar}_set_no'], r[f'bar{bar}_merge'], r[f'bar{bar}_vendor'] = set_no, merge, vendor
        out.append(r)
    return pd.DataFrame(out, columns=tables.LAST_TKT.names, dtype=object)


def _threaded(*rows):
    return pd.DataFrame(list(rows), columns=('machine', 'bar', 'rem_lbs'), dtype=object)


def _rec(doff_day_hour, racks, style='S'):
    ts = dt.datetime(2026, 10, doff_day_hour[0], doff_day_hour[1])
    return {'ticket_no': f't{doff_day_hour}', 'style': style, 'racks': racks,
            'lbs': racks * 12, 'doff_ts': iso_plant(ts)}


B8_SETS = {1: ('47999', '2609', 'Ashfar'), 2: ('2-3813', 'A716B', 'Hyosung'),
           3: ('2-3813', 'A716B', 'Hyosung')}


class ComputeRunoutTests(_QuietLogs):

    def _threadings(self, racks_at_ro=100.0):
        return _threadings(
            ('B08', 'S', '47999', '1', racks_at_ro, THREADED_AT, 2000.0, '2609', 'Ashfar'),
            ('B08', 'S', '2-3813', '2-3', racks_at_ro, THREADED_AT, 3000.0, 'A716B', 'Hyosung'),
            ('B08', 'S', 'OLD', '1', 0.0, T('2026-10-01 08:00'), 100.0, 'x', 'y'),
        )

    def _doffed(self, with_earlier=True):
        rolls = [_rec((11, 9), 300.0), _rec((12, 9), 50.0)]
        if with_earlier:
            rolls.insert(0, _rec((9, 12), 500.0))
        return {'B8': rolls}

    def _run(self, threadings=None, doffed=None, racks=None, last_tkt=None, threaded=None):
        return compute_runout(
            self._threadings() if threadings is None else threadings,
            self._doffed() if doffed is None else doffed,
            _racks(B08=25.0) if racks is None else racks,
            _variants(),
            _last_tkt(('B08', 'S', B8_SETS)) if last_tkt is None else last_tkt,
            _threaded() if threaded is None else threaded,
        )

    def test_shape_single_and_split(self):
        out = self._run()
        self.assertEqual(list(out), ['B8'])
        self.assertEqual(sorted(out['B8']), [1, 2, 3])
        self.assertEqual(out['B8'][1], {'set_no': '47999', 'merge': '2609', 'vendor': 'Ashfar',
                                        'lbs': 680.0})
        for bar in (2, 3):
            self.assertEqual(out['B8'][bar], {'set_no': '2-3813', 'merge': 'A716B',
                                              'vendor': 'Hyosung', 'lbs': 510.0})
        self.assertEqual(self._run(last_tkt=_last_tkt(('B08', 'S', {}))), {'B8': {}})

    def test_rolls_before_threading_ignored(self):
        self.assertEqual(self._run(doffed=self._doffed(with_earlier=False))['B8'][1]['lbs'], 680.0)

    def test_racks_at_runout_beyond_roll(self):
        out = self._run(threadings=self._threadings(racks_at_ro=400.0))
        self.assertEqual(out['B8'][1]['lbs'], 200.0)

    def test_current_roll(self):
        thr = _threadings(('F08', 'S', 's', '1', 0.0, THREADED_AT, 1000.0, 'm', 'v'))
        tkt = _last_tkt(('F08', 'S', {1: ('s', 'm', 'v')}))
        self.assertEqual(self._run(thr, {}, _racks(F08=100.0), tkt)['F8'][1]['lbs'], 520.0)
        self.assertEqual(self._run(thr, {}, _racks(), tkt)['F8'][1]['lbs'], 1000.0)
        tkt = _last_tkt(('F08', None, {1: ('s', 'm', 'v')}))
        self.assertEqual(self._run(thr, {}, _racks(F08=100.0), tkt)['F8'][1]['lbs'], 1000.0)

    def test_fallback(self):
        tkt = _last_tkt(('C08', 'S', {1: ('F1', 'fm', 'fv'), 2: ('F2', None, None)}))
        with self.assertLogs(LOG_NAME, 'WARNING') as logs:
            out = self._run(_threadings(), {}, _racks(), tkt, _threaded(('C08', 1, 321.0)))
        self.assertEqual(out['C8'][1], {'set_no': 'F1', 'merge': 'fm', 'vendor': 'fv', 'lbs': 321.0})
        self.assertEqual(out['C8'][2], {'set_no': 'F2', 'merge': None, 'vendor': None, 'lbs': 0.0})
        self.assertEqual(len(logs.output), 2)
        self.assertTrue(all('C8 bar' in m for m in logs.output))

    def test_ran_out(self):
        thr = _threadings(('D08', 'S', 's', '1', 0.0, THREADED_AT, 100.0, 'm', 'v'))
        tkt = _last_tkt(('D08', 'S', {1: ('s', 'm', 'v')}))
        with self.assertLogs(LOG_NAME, 'WARNING') as logs:
            out = self._run(thr, {'D8': [_rec((11, 9), 300.0)]}, _racks(), tkt)
        self.assertEqual(out['D8'][1]['lbs'], 0.0)
        self.assertIn('ran out', logs.output[0])

    def test_unknown_style(self):
        thr = _threadings(('E08', 'S', 's', '1', 0.0, THREADED_AT, 100.0, 'm', 'v'))
        tkt = _last_tkt(('E08', 'S', {1: ('s', 'm', 'v')}))
        with self.assertRaisesRegex(KeyError, 'ZZZ'):
            self._run(thr, {'E8': [_rec((11, 9), 10.0, style='ZZZ')]}, _racks(), tkt)
        with self.assertRaisesRegex(KeyError, 'ZZZ'):
            self._run(thr, {}, _racks(E08=5.0), _last_tkt(('E08', 'ZZZ', {1: ('s', 'm', 'v')})))

    def test_parse_bars(self):
        self.assertEqual(parse_bars('1'), [1])
        self.assertEqual(parse_bars('2-3'), [2, 3])
        self.assertEqual(parse_bars(' 1-2 '), [1, 2])


# ===================================================================
# 13. gen_machines
# ===================================================================

def _status(*rows):
    """`(machine, style, status, {bar: (set_no, merge, vendor)}[, rack_wt])` rows
    in MACHINE_STATUS's names."""
    out = []
    for machine, style, status, sets, *rest in rows:
        r = {n: None for n in tables.MACHINE_STATUS.names}
        r['machine'], r['style'], r['status'] = machine, style, status
        r['rack_wt'] = rest[0] if rest else 1200.0
        for bar, (set_no, merge, vendor) in sets.items():
            r[f'bar{bar}_set_no'], r[f'bar{bar}_merge'], r[f'bar{bar}_vendor'] = set_no, merge, vendor
        out.append(r)
    return pd.DataFrame(out, columns=tables.MACHINE_STATUS.names, dtype=object)


def _entry(set_no, lbs):
    return {'set_no': set_no, 'merge': 'm', 'vendor': 'v', 'lbs': lbs}


class GenMachinesTests(_QuietLogs):

    RUNOUT = {'B8': {1: _entry('47999', 317.5), 2: _entry('2-3813', 255.0),
                     3: _entry('2-3813', 255.0)}}

    def test_one_record_per_row(self):
        status = _status(('M02', 'S', 'standing', {}), ('B08', 'S', None, B8_SETS))
        out = gen_machines(self.RUNOUT, status, _racks(), _variants())
        self.assertEqual([r['id'] for r in out], ['M2', 'B8'])
        self.assertEqual(tuple(out[0]), ('id', 'is_new', 'init_item', 'status', 'init_top_lbs',
                                         'init_btm_lbs', 'init_roll_lbs', 'init_btm_set',
                                         'init_top_set'))
        self.assertIs(out[0]['is_new'], True)
        self.assertIs(out[1]['is_new'], False)
        self.assertEqual(out[0]['init_item'], 'S')
        self.assertEqual(out[0]['status'], 'standing')
        self.assertEqual(out[1]['status'], 'running')

    def test_grouping(self):
        out = gen_machines(self.RUNOUT, _status(('B08', 'S', 'running', B8_SETS)),
                           _racks(), _variants())[0]
        self.assertEqual(out['init_btm_lbs'], 317.5)
        self.assertEqual(out['init_top_lbs'], 510.0)
        self.assertEqual(out['init_btm_set'], {'set_no': '47999', 'merge': 'm', 'vendor': 'v'})
        self.assertEqual(out['init_top_set'], {'set_no': '2-3813', 'merge': 'm', 'vendor': 'v'})

    def test_identity_fallback(self):
        runout = {'B8': {1: _entry('47999', 100.0), 3: _entry('2-3813', 50.0)}}
        status = _status(('B08', 'S', 'running', {2: ('T2', 'tm', 'tv')}))
        out = gen_machines(runout, status, _racks(), _variants())[0]
        self.assertEqual(out['init_top_set'], {'set_no': '2-3813', 'merge': 'm', 'vendor': 'v'})
        self.assertEqual(out['init_top_lbs'], 50.0)
        runout = {'B8': {1: _entry('47999', 100.0)}}
        with self.assertLogs(LOG_NAME, 'WARNING') as logs:
            out = gen_machines(runout, status, _racks(), _variants())[0]
        self.assertEqual(out['init_top_set'], {'set_no': 'T2', 'merge': 'tm', 'vendor': 'tv'})
        self.assertIn('bar 2 not in runout', logs.output[0])
        status = _status(('B08', 'S', 'running', {}))
        out = gen_machines(runout, status, _racks(), _variants())[0]
        self.assertIsNone(out['init_top_set'])

    def test_ungroupable(self):
        variants = _variants(
            ('ONE', [1, 1, 1, None], ['a', 'a', 'a', None], [50, 25, 25, None]),
            ('THREE', [1, 1, 1, None], ['a', 'b', 'c', None], [50, 25, 25, None]),
        )
        runout = {'B8': {1: _entry('s1', 10.0), 2: _entry('s2', 20.0), 4: _entry('s4', 5.0)}}
        for style in ('ZZZ', 'ONE', 'THREE'):
            with self.assertLogs(LOG_NAME, 'WARNING') as logs:
                out = gen_machines(runout, _status(('B08', style, 'running', {})),
                                   _racks(), variants)[0]
            self.assertIn('does not group', logs.output[0])
            self.assertEqual((out['init_btm_lbs'], out['init_top_lbs']), (10.0, 25.0))
            self.assertEqual(out['init_top_set']['set_no'], 's2')

    def test_roll(self):
        status = _status(('B08', 'S', 'running', B8_SETS))
        self.assertEqual(gen_machines(self.RUNOUT, status, _racks(B08=40.0), _variants())[0]['init_roll_lbs'], 480.0)
        self.assertEqual(gen_machines(self.RUNOUT, status, _racks(), _variants())[0]['init_roll_lbs'], 0.0)
        status = _status(('B08', 'S', 'running', B8_SETS, None))
        self.assertEqual(gen_machines(self.RUNOUT, status, _racks(B08=40.0), _variants())[0]['init_roll_lbs'], 0.0)

    def test_missing_machine(self):
        status = _status(('C08', 'S', 'running', {1: ('c1', 'cm', 'cv'), 2: ('c2', 'cm', 'cv')}))
        with self.assertLogs(LOG_NAME, 'WARNING'):
            out = gen_machines({}, status, _racks(), _variants())[0]
        self.assertEqual((out['init_btm_lbs'], out['init_top_lbs']), (0.0, 0.0))
        self.assertEqual(out['init_btm_set']['set_no'], 'c1')
        self.assertEqual(out['init_top_set']['set_no'], 'c2')

    def test_bar_groups(self):
        variants = _variants(
            ('ONE', [1, 1, 1, None], ['a', 'a', 'a', None], [50, 25, 25, None]),
            ('THREE', [1, 1, 1, None], ['a', 'b', 'c', None], [50, 25, 25, None]),
            ('NOBAR1', [None, 1, 1, None], [None, 'a', 'b', None], [None, 50, 50, None]),
        )
        self.assertEqual(bar_groups(variants, 'S'), ((1,), (2, 3)))
        for style in ('ZZZ', None, 'ONE', 'THREE', 'NOBAR1'):
            self.assertIsNone(bar_groups(variants, style))


# ===================================================================
# 14. make_input_file / plan inputs
# ===================================================================

class _Recorder:
    """A stand-in `run_query`: records `(table, statement, cfgpath)` and
    serves `rows[table]` (default none) through the table."""

    def __init__(self, rows=None):
        self.calls = []
        self.rows = rows or {}

    def __call__(self, query_str, tbl, cfgpath=None):
        self.calls.append((tbl.name, query_str, cfgpath))
        return tbl.from_tuples(self.rows.get(tbl.name, []))

    @property
    def names(self):
        return [c[0] for c in self.calls]


class MakeInputFileTests(_QuietLogs):

    SINCE = dt.date(2026, 10, 1)
    DATED = dt.date(2026, 1, 1)

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name
        self.out = os.path.join(self.dir, 'out.json')
        status_row = ['B08', 't', '2026-10-10 12:00:00', 'S', '3'] + ['47999', 'm', 'v', '', ''] \
            + ['2-3813', 'm', 'v', '', ''] * 2 + [''] * 5 + ['1200', '40', 'running']
        for stamp in (self.DATED, None):
            self._tsv('racks', stamp, 'MC\tRacks\nB08\t40\n')
            self._tsv('machine_status', stamp,
                      '\t'.join(tables.MACHINE_STATUS.names) + '\n' + '\t'.join(status_row) + '\n')
            self._tsv('floor_status', stamp, 'machine\tbar\tstatus\nB08\t1\tx\n')
        self.rec = _Recorder()
        self.reads = []
        real = make_input_mod.read_csv

        def spy(fpath, tbl, sep=','):
            self.reads.append((os.path.basename(fpath), tbl.name))
            return real(fpath, tbl, sep)
        for target, repl in (('run_query', self.rec), ('read_csv', spy)):
            p = mock.patch.object(make_input_mod, target, repl)
            p.start()
            self.addCleanup(p.stop)

    def _tsv(self, stem, stamp, text):
        _write(os.path.join(self.dir, get_file_name(stem, 'tsv', stamp)), text)

    def _make(self, name, **kw):
        kw.setdefault('since', self.SINCE)
        kw.setdefault('files_dir', self.dir)
        make_input_file(name, self.out, **kw)
        with open(self.out, encoding='utf-8') as fh:
            return fh.read()

    def test_name_to_loads(self):
        runout_q = ['THREADINGS_SINCE', 'DOFFED', 'TKTS_SINCE', 'ALL_VARIANTS', 'LAST_TKT', 'THREADED']
        expect = {
            InputName.MACHINES: (runout_q, ['RACKS', 'MACHINE_STATUS']),
            InputName.RUNOUT: (runout_q, ['RACKS']),
            InputName.DOFFED_ROLLS: (['DOFFED', 'TKTS_SINCE'], []),
            InputName.BEAM_SETS: (['ACTIVE', 'ASSIGNED'], ['FLOOR_STATUS']),
            InputName.ASSIGNED_SETS: (['ACTIVE', 'ASSIGNED'], ['FLOOR_STATUS']),
        }
        for name, (queries_run, files_read) in expect.items():
            self.rec.calls.clear()
            self.reads.clear()
            self._make(name)
            self.assertEqual(sorted(self.rec.names), sorted(queries_run), name)
            self.assertEqual(len(self.rec.names), len(queries_run), name)
            self.assertEqual(sorted(t for _, t in self.reads), sorted(files_read), name)

    def test_dates_and_config(self):
        self._make(InputName.RUNOUT, dt=self.DATED, cfgpath='cfg.txt')
        for name, stmt, cfg in self.rec.calls:
            self.assertEqual(cfg, 'cfg.txt')
            if name in DATED_QUERIES:
                self.assertIn('DATETIMEFROMPARTS(2026, 10, 1, 0, 0, 0', stmt)
            else:
                self.assertNotIn('DATETIMEFROMPARTS(2026', stmt)
        self.assertEqual(self.reads, [('racks_20260101.tsv', 'RACKS')])

    def test_output(self):
        self.rec.rows['DOFFED'] = [('B08', 'A', '2026-10-10 12:00:00', '2026-10-10 14:00:00',
                                    'Ü', '1200', '10')]
        text = self._make(InputName.DOFFED_ROLLS)
        self.assertTrue(text.endswith('}\n'))
        self.assertIn('\n    "B8"', text)
        self.assertIn('Ü', text)
        self.assertNotIn('\\u00dc', text)
        self.assertEqual(json.loads(text)['B8'][0]['style'], 'Ü')
        self.rec.rows['ACTIVE'] = [('1-1', '2026-10-01 12:00:00', None, '10', '2', '100',
                                    'm', 'v', '75', 'l', 'd', None, 's')]
        self.assertEqual(json.loads(self._make(InputName.BEAM_SETS))[0]['set_no'], '1-1')
        self.assertEqual(json.loads(self._make(InputName.ASSIGNED_SETS)), [])
        self.rec.rows['LAST_TKT'] = [['B08', 't', None, 'S', None, '47999', 'm', 'v', None, None]
                                     + [None] * 17]
        self.assertEqual(list(json.loads(self._make(InputName.RUNOUT))['B8']), ['1'])

    def test_name_forms(self):
        self._make('doffed-rolls')
        self._make(InputName.DOFFED_ROLLS)
        with self.assertRaises(ValueError):
            self._make('bogus')

    def test_errors(self):
        with self.assertRaises(typer.BadParameter):
            self._make(InputName.BEAM_SETS, dt=dt.date(1999, 1, 1))
        self.rec.rows['LAST_TKT'] = [['B08', 't', None, 'ZZZ', None, '47999', 'm', 'v', None, None]
                                     + [None] * 17]
        self.rec.rows['THREADINGS_SINCE'] = [('B08', 'S', '47999', '1', '100',
                                              '2026-10-10 12:00:00', '2000', 'm', 'v')]
        with self.assertRaisesRegex(typer.BadParameter, 'ZZZ'):
            self._make(InputName.RUNOUT)

    def test_reporting(self):
        with self.assertLogs(LOG_NAME, 'WARNING') as logs:
            self._make(InputName.MACHINES)
        self.assertTrue(any('does not group' in m for m in logs.output))
        root = logging.getLogger()
        saved = (list(LOADINPUTS_LOG.handlers), list(root.handlers))
        LOADINPUTS_LOG.handlers.clear()
        root.handlers.clear()
        try:
            self._make(InputName.DOFFED_ROLLS)
            self.assertEqual(len(LOADINPUTS_LOG.handlers), 1)
            self.assertIsInstance(LOADINPUTS_LOG.handlers[0], logging.StreamHandler)
            self._make(InputName.DOFFED_ROLLS)
            self.assertEqual(len(LOADINPUTS_LOG.handlers), 1)
        finally:
            LOADINPUTS_LOG.handlers[:] = saved[0]
            root.handlers[:] = saved[1]

    def test_command(self):
        from swmtplanner.planners.cli import app
        runner = CliRunner()
        text = re.sub(r'\s+', '', runner.invoke(app, ['inputs', '--help']).output)
        for name in InputName:
            self.assertIn(name.value, text)
        r = runner.invoke(app, ['inputs', 'doffed-rolls', self.out,
                                '--since', '2026-10-01', '--files-dir', self.dir])
        self.assertEqual(r.exit_code, 0, r.output)
        with open(self.out, encoding='utf-8') as fh:
            self.assertEqual(json.load(fh), {})
        self.assertIn('DATETIMEFROMPARTS(2026, 10, 1, 0, 0, 0', self.rec.calls[0][1])
        r = runner.invoke(app, ['inputs', 'bogus', self.out,
                                '--since', '2026-10-01', '--files-dir', self.dir])
        self.assertNotEqual(r.exit_code, 0)


if __name__ == '__main__':
    unittest.main()
