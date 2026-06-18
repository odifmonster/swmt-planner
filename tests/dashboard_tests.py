#!/usr/bin/env python

"""Coverage of the dashboard persistence pieces — the `manifest` (DebugLog ->
MySQL mapping), `config` (connection resolution), and `persistence` (the writer:
pure helpers + a MySQL-gated end-to-end). See
`tests/spec-files/DASHBOARD_TEST_SPEC.md`. The PyQt6 app is out of scope here."""

import datetime
import os
import unittest

import numpy as np
import pandas as pd

from swmtplanner.planners.infinite import Costing
from swmtplanner.planners.infinite.loop import plan
from swmtplanner.planners.infinite.run import _build_debug_log
from swmtplanner.planners.infinite.dashboard import manifest
from swmtplanner.planners.infinite.dashboard.manifest import (
    ForeignKey, spec_for_name,
)
from swmtplanner.planners.infinite.dashboard.config import (
    ConnConfig, DatabaseConfigError, resolve_conn_config,
)
from swmtplanner.planners.infinite.dashboard.sqldump import persistence
from swmtplanner.planners.infinite.dashboard.sqldump.persistence import (
    PersistenceError, persist_run,
)
from swmtplanner.planners.infinite.dashboard.sqlload.helpers import (
    Filter, FKLookup, FilterError,
)
from swmtplanner.planners.infinite.dashboard.sqlload import query as sqlquery
from swmtplanner.planners.infinite.dashboard.sqlload.query import Query
from swmtplanner.planners.infinite.dashboard.sqlload import table as sqltable
from swmtplanner.planners.infinite.dashboard.sqlload.table import Table

from inf_plan_tests import _make_state, _weights


def _populated_log():
    """A `DebugLog` populated by a real (small) verbose planner run."""
    dl = _build_debug_log()
    plan(_make_state(), Costing(_weights()), debuglog=dl)
    return dl


# ===================================================================
# 1. Manifest <-> live DebugLog consistency
# ===================================================================

class ManifestConsistencyTests(unittest.TestCase):

    def setUp(self):
        self.schema = _build_debug_log().schema   # {debuglog table -> TableSchema}

    def test_table_set_matches_debuglog(self):
        # Table names are identical to the DebugLog table names now.
        manifest_names = {t.name for t in manifest.TABLES}
        self.assertEqual(manifest_names, set(self.schema))

    def test_columns_are_identity(self):
        for spec in manifest.TABLES:
            with self.subTest(table=spec.name):
                self.assertEqual(
                    set(spec.column_names),
                    set(self.schema[spec.name].columns),
                )

    def test_primary_keys_match(self):
        for spec in manifest.TABLES:
            with self.subTest(table=spec.name):
                pk = self.schema[spec.name].pk
                self.assertEqual(spec.pk, (pk,) if pk is not None else ())

    def test_manifest_fks_superset_of_debuglog(self):
        # Names match, so the DebugLog FKs map identically into the manifest's.
        for spec in manifest.TABLES:
            for fk in self.schema[spec.name].fks:
                mapped = ForeignKey(fk.column, fk.ref_table, fk.ref_column)
                with self.subTest(table=spec.name, fk=fk.column):
                    self.assertIn(mapped, spec.fks)


# ===================================================================
# 2. Manifest structure
# ===================================================================

class ManifestStructureTests(unittest.TestCase):

    def test_insert_order_is_topological(self):
        seen = {manifest.RUNS_TABLE}
        for spec in manifest.TABLES:
            for fk in spec.fks:
                self.assertIn(
                    fk.ref_table, seen,
                    f'{spec.name}.{fk.column} -> {fk.ref_table} '
                    f'references a table not inserted yet',
                )
            seen.add(spec.name)

    def test_production_has_extra_schedule_link(self):
        prod = spec_for_name('production')
        self.assertIn(
            ForeignKey('knit_id', 'sched_cost_detail', 'activity_id'), prod.fks,
        )

    def test_run_registry(self):
        self.assertEqual(manifest.RUNS.name, 'runs')
        self.assertEqual(manifest.RUNS.pk, ('run_id',))
        self.assertEqual(manifest.ALL_TABLES, (manifest.RUNS,) + manifest.TABLES)

    def test_lookups(self):
        self.assertEqual(spec_for_name('demand').name, 'demand')
        self.assertEqual(spec_for_name('production').pk, ('knit_id',))
        self.assertEqual(spec_for_name('runs'), manifest.RUNS)
        with self.assertRaises(KeyError):
            spec_for_name('nope')


# ===================================================================
# 3. Connection-config resolution
# ===================================================================

def _block(**over):
    b = {
        'host': 'db.local', 'port': 3307, 'name': 'swmtinfinite',
        'writer': {'user': 'w_user', 'password': 'w_pw'},
        'reader': {'user': 'r_user', 'password': 'r_pw'},
    }
    b.update(over)
    return b


class ConfigResolutionTests(unittest.TestCase):

    def test_resolves_per_role_from_block(self):
        w = resolve_conn_config(_block(), 'writer', env={})
        self.assertEqual(
            w, ConnConfig('db.local', 3307, 'swmtinfinite', 'w_user', 'w_pw'),
        )
        r = resolve_conn_config(_block(), 'reader', env={})
        self.assertEqual(r.user, 'r_user')
        self.assertEqual(r.password, 'r_pw')

    def test_env_wins_over_file(self):
        env = {
            'SWMT_DB_HOST': '10.0.0.9', 'SWMT_DB_PORT': '9999',
            'SWMT_DB_NAME': 'envdb', 'SWMT_DB_READER_PASSWORD': 'env_pw',
        }
        r = resolve_conn_config(_block(), 'reader', env=env)
        self.assertEqual(
            r, ConnConfig('10.0.0.9', 9999, 'envdb', 'r_user', 'env_pw'),
        )

    def test_env_only_no_block(self):
        env = {
            'SWMT_DB_NAME': 'envdb', 'SWMT_DB_WRITER_USER': 'envw',
            'SWMT_DB_WRITER_PASSWORD': 'p',
        }
        w = resolve_conn_config(None, 'writer', env=env)
        self.assertEqual(
            w, ConnConfig('127.0.0.1', 3306, 'envdb', 'envw', 'p'),
        )

    def test_null_password_allowed(self):
        b = _block(writer={'user': 'w_user', 'password': None})
        w = resolve_conn_config(b, 'writer', env={})
        self.assertIsNone(w.password)

    def test_defaults_host_and_port(self):
        b = {'name': 'd', 'reader': {'user': 'u', 'password': None}}
        r = resolve_conn_config(b, 'reader', env={})
        self.assertEqual((r.host, r.port), ('127.0.0.1', 3306))

    def test_unknown_role_raises(self):
        with self.assertRaises(DatabaseConfigError):
            resolve_conn_config(_block(), 'admin', env={})

    def test_missing_name_raises(self):
        b = {'writer': {'user': 'u', 'password': 'p'}}
        with self.assertRaises(DatabaseConfigError):
            resolve_conn_config(b, 'writer', env={})

    def test_missing_user_raises(self):
        b = {'name': 'd', 'writer': {'password': 'p'}}
        with self.assertRaises(DatabaseConfigError):
            resolve_conn_config(b, 'writer', env={})

    def test_invalid_port_raises(self):
        with self.assertRaises(DatabaseConfigError):
            resolve_conn_config(_block(port='not-a-port'), 'reader', env={})


# ===================================================================
# 4. Persistence — pure helpers (no server)
# ===================================================================

class PersistenceHelperTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dl = _populated_log()

    def test_to_sql_missing_values_become_none(self):
        for v in (None, float('nan'), np.float64('nan'), pd.NaT, pd.NA):
            self.assertIsNone(persistence.to_sql(v))

    def test_to_sql_numeric_and_str_passthrough(self):
        self.assertEqual(persistence.to_sql(3.5), 3.5)
        self.assertIs(type(persistence.to_sql(np.float64(3.5))), float)
        self.assertEqual(persistence.to_sql(np.int64(7)), 7)
        self.assertIs(type(persistence.to_sql(np.int64(7))), int)
        self.assertEqual(persistence.to_sql('KNIT00000001'), 'KNIT00000001')

    def test_to_sql_timestamp_becomes_datetime(self):
        out = persistence.to_sql(pd.Timestamp('2026-05-18 01:00'))
        self.assertEqual(out, datetime.datetime(2026, 5, 18, 1, 0))
        self.assertIsInstance(out, datetime.datetime)
        self.assertIsInstance(
            persistence.to_sql(pd.Timestamp('2026-05-18')), datetime.datetime,
        )

    def test_insert_sql_backticks_and_order(self):
        spec = spec_for_name('sched_cost_detail')
        sql = persistence.insert_sql(spec)
        self.assertTrue(sql.startswith(
            'INSERT INTO `sched_cost_detail` (`run_id`, `activity_id`, `move_id`, '
        ))
        for col in ('desc', 'start', 'end'):       # reserved words backticked
            self.assertIn(f'`{col}`', sql)
        self.assertEqual(sql.count('%s'), 1 + len(spec.column_names))

    def test_project_rows_shape_and_counts(self):
        for name in ('iteration_log', 'cost_summary', 'priority_detail',
                     'production', 'unmet_demand'):
            spec = spec_for_name(name)
            rows = list(persistence.project_rows(self.dl, spec, run_id=42))
            self.assertEqual(len(rows), len(self.dl.get_df(name)), name)
            for r in rows:
                self.assertEqual(r[0], 42)                         # run_id first
                self.assertEqual(len(r), 1 + len(spec.column_names))

    def test_project_rows_exposes_keyed_pk(self):
        spec = spec_for_name('iteration_log')
        mi = spec.column_names.index('move_id')                   # the PK (index in get_df)
        rows = list(persistence.project_rows(self.dl, spec, run_id=1))
        self.assertTrue(rows)
        self.assertTrue(all(isinstance(r[1 + mi], int) for r in rows))

    def test_project_rows_empty_table_yields_nothing(self):
        spec = spec_for_name('unmet_demand')                  # empty in this fixture
        self.assertEqual(list(persistence.project_rows(self.dl, spec, 1)), [])


# ===================================================================
# 5. persist_run end-to-end (MySQL-gated)
# ===================================================================

_HOST = os.environ.get('SWMT_TEST_DB_HOST', '127.0.0.1')
_PORT = int(os.environ.get('SWMT_TEST_DB_PORT', '3306'))
_DB = os.environ.get('SWMT_TEST_DB_NAME', 'swmtinftest')
_WRITER = (os.environ.get('SWMT_TEST_WRITER_USER', 'knitwritetest'),
           os.environ.get('SWMT_TEST_WRITER_PASSWORD', 'testpass'))
_READER = (os.environ.get('SWMT_TEST_READER_USER', 'knitreadtest'),
           os.environ.get('SWMT_TEST_READER_PASSWORD', 'testpass'))
_ADMIN = (os.environ.get('SWMT_TEST_ADMIN_USER', 'ktroot'),
          os.environ.get('SWMT_TEST_ADMIN_PASSWORD', 'InfTestRoot'))


def _connect(creds, autocommit=True):
    import pymysql
    user, password = creds
    return pymysql.connect(
        host=_HOST, port=_PORT, user=user, password=password,
        database=_DB, autocommit=autocommit,
    )


class PersistRunMySQLTests(unittest.TestCase):
    """End-to-end against a local test MySQL. Skips when the server / driver is
    unavailable. Each test truncates all knit* tables (admin role) for a clean
    slate; persists via the write role; reads back via the read role."""

    @classmethod
    def setUpClass(cls):
        try:
            _connect(_ADMIN).close()
        except Exception as exc:                   # driver missing or server down
            raise unittest.SkipTest(f'test MySQL {_DB!r} unreachable: {exc}')
        cls.dl = _build_debug_log()
        cls.report = plan(_make_state(), Costing(_weights()), debuglog=cls.dl)
        cls.writer_conn = ConnConfig(_HOST, _PORT, _DB, *_WRITER)
        cls.reader_conn = ConnConfig(_HOST, _PORT, _DB, *_READER)

    def setUp(self):
        conn = _connect(_ADMIN)
        try:
            with conn.cursor() as cur:
                cur.execute('SET FOREIGN_KEY_CHECKS=0')
                for spec in manifest.ALL_TABLES:
                    cur.execute(f'TRUNCATE TABLE `{spec.name}`')
                cur.execute('SET FOREIGN_KEY_CHECKS=1')
            conn.commit()
        finally:
            conn.close()

    def _query(self, sql, params=()):
        conn = _connect(_READER)
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()
        finally:
            conn.close()

    def _count(self, table, run_id=None):
        if run_id is None:
            return self._query(f'SELECT COUNT(*) FROM `{table}`')[0][0]
        return self._query(
            f'SELECT COUNT(*) FROM `{table}` WHERE run_id=%s', (run_id,),
        )[0][0]

    def test_round_trip_counts_and_metadata(self):
        rid = persist_run(
            self.dl, self.writer_conn,
            start_date=datetime.date(2026, 5, 18), total_score=123.5, n_unmet=7,
        )
        self.assertIsInstance(rid, int)
        self.assertEqual(self._count('runs'), 1)
        score, n_unmet, start_date = self._query(
            'SELECT total_score, n_unmet, start_date FROM runs '
            'WHERE run_id=%s', (rid,),
        )[0]
        self.assertAlmostEqual(score, 123.5)
        self.assertEqual(n_unmet, 7)
        self.assertEqual(start_date, datetime.date(2026, 5, 18))
        # every table's row count for this run matches the in-memory log; a
        # successful insert also proves the FK-topological order held.
        for spec in manifest.TABLES:
            self.assertEqual(
                self._count(spec.name, rid),
                len(self.dl.get_df(spec.name)), spec.name,
            )

    def test_role_column_round_trips(self):
        rid = persist_run(
            self.dl, self.writer_conn,
            start_date=datetime.date(2026, 5, 18), total_score=0.0, n_unmet=0,
        )
        roles = {r[0] for r in self._query(
            'SELECT DISTINCT role FROM iteration_log WHERE run_id=%s', (rid,),
        )}
        self.assertTrue(roles <= {'committed', 'rejected'})
        self.assertIn('committed', roles)
        db_committed = self._query(
            "SELECT COUNT(*) FROM iteration_log WHERE run_id=%s AND role='committed'",
            (rid,),
        )[0][0]
        il = self.dl.get_df('iteration_log')
        self.assertEqual(db_committed, int((il['role'] == 'committed').sum()))

    def test_distinct_run_ids_and_isolation(self):
        kw = dict(start_date=datetime.date(2026, 5, 18), total_score=1.0, n_unmet=0)
        rid1 = persist_run(self.dl, self.writer_conn, **kw)
        rid2 = persist_run(self.dl, self.writer_conn, **kw)
        self.assertNotEqual(rid1, rid2)
        self.assertEqual(self._count('runs'), 2)
        for spec in manifest.TABLES:
            n = len(self.dl.get_df(spec.name))
            self.assertEqual(self._count(spec.name, rid1), n, spec.name)
            self.assertEqual(self._count(spec.name, rid2), n, spec.name)
            self.assertEqual(self._count(spec.name), 2 * n, spec.name)

    def test_reader_role_cannot_write(self):
        self.assertEqual(self._count('runs'), 0)
        with self.assertRaises(PersistenceError):
            persist_run(
                self.dl, self.reader_conn,
                start_date=datetime.date(2026, 5, 18), total_score=0.0, n_unmet=0,
            )
        self.assertEqual(self._count('runs'), 0)   # rollback / denied: nothing written

    def test_run_py_wiring_persists_with_label_and_notes(self):
        # The run.py `--verbose` glue: resolve the writer config from a
        # `database` block, persist, and round-trip metadata + label + notes.
        from swmtplanner.planners.infinite.run import _persist_debuglog
        db_block = {
            'host': _HOST, 'port': _PORT, 'name': _DB,
            'writer': {'user': _WRITER[0], 'password': _WRITER[1]},
        }
        rid = _persist_debuglog(
            db_block, self.dl, self.report,
            datetime.datetime(2026, 5, 18, 8, 0),
            'baseline run', 'first line\nsecond line\n',
        )
        self.assertIsInstance(rid, int)
        self.assertEqual(self._count('runs'), 1)
        self.assertEqual(
            self._count('iteration_log', rid),
            len(self.dl.get_df('iteration_log')),
        )
        n_unmet, label, notes = self._query(
            'SELECT n_unmet, label, notes FROM runs WHERE run_id=%s', (rid,),
        )[0]
        self.assertEqual(n_unmet, len(self.report.unmet_lbs_by_item_week))
        self.assertEqual(label, 'baseline run')
        self.assertEqual(notes, 'first line\nsecond line\n')

    def test_run_py_wiring_skips_without_database_block(self):
        from swmtplanner.planners.infinite.run import _persist_debuglog
        self.assertIsNone(_persist_debuglog(
            None, self.dl, self.report, datetime.datetime(2026, 5, 18),
            'lbl', 'notes',
        ))
        self.assertEqual(self._count('runs'), 0)


# ===================================================================
# 6. Read layer (sqlload) — query inputs: Filter / FKLookup (no server)
# ===================================================================

class FilterTests(unittest.TestCase):

    def test_validation_is_lazy(self):
        # A mismatched kind/rule is accepted at construction; the error only
        # surfaces when to_sql_str() is called.
        bad = [
            Filter('selection', [1, 2]),       # non-set rule
            Filter('range', (None, None)),     # unbounded both ends
            Filter('pattern', 5),              # non-str rule
            Filter('bogus', 'x'),              # unknown kind
        ]
        for f in bad:
            with self.subTest(filter=f):
                with self.assertRaises(FilterError):
                    f.to_sql_str()

    def test_unknown_kind_raises(self):
        with self.assertRaises(FilterError):
            Filter('between', (1, 2)).to_sql_str()

    def test_bad_membership_rule_raises(self):
        for kind in ('selection', 'exclusion'):
            with self.subTest(kind=kind, case='non-set'):
                with self.assertRaises(FilterError):
                    Filter(kind, [1, 2]).to_sql_str()
            with self.subTest(kind=kind, case='empty'):
                with self.assertRaises(FilterError):
                    Filter(kind, set()).to_sql_str()

    def test_bad_range_rule_raises(self):
        for rule in ((1,), (1, 2, 3), [1, 2], (None, None)):
            with self.subTest(rule=rule):
                with self.assertRaises(FilterError):
                    Filter('range', rule).to_sql_str()

    def test_bad_pattern_rule_raises(self):
        with self.assertRaises(FilterError):
            Filter('pattern', 5).to_sql_str()

    def test_selection_compiles(self):
        self.assertEqual(
            Filter('selection', {3, 1, 2}).to_sql_str(),
            '{colname} IN (1, 2, 3)',
        )
        # strings are quoted; the list is sorted for a deterministic statement
        self.assertEqual(
            Filter('selection', {'b', 'a'}).to_sql_str(),
            "{colname} IN ('a', 'b')",
        )
        # the {colname} field is filled by the Query
        self.assertEqual(
            Filter('selection', {1}).to_sql_str().format(colname='`t`.`c`'),
            '`t`.`c` IN (1)',
        )

    def test_exclusion_compiles(self):
        self.assertEqual(
            Filter('exclusion', {'b', 'a'}).to_sql_str(),
            "{colname} NOT IN ('a', 'b')",
        )

    def test_range_low_only(self):
        self.assertEqual(
            Filter('range', (10, None)).to_sql_str(), '{colname} >= 10',
        )

    def test_range_high_only(self):
        self.assertEqual(
            Filter('range', (None, 5)).to_sql_str(), '{colname} <= 5',
        )

    def test_range_both_bounds(self):
        self.assertEqual(
            Filter('range', (10, 20)).to_sql_str(),
            '{colname} >= 10 AND {colname} <= 20',
        )

    def test_pattern_compiles(self):
        self.assertEqual(
            Filter('pattern', 'AB%').to_sql_str(), "{colname} LIKE 'AB%'",
        )


class FKLookupTests(unittest.TestCase):

    def test_empty_vals_raises(self):
        fk = FKLookup('demand', 'order_id', set())      # construction is fine
        with self.assertRaises(FilterError):
            fk.to_sql_str()

    def test_valid_output(self):
        fk = FKLookup('demand', 'order_id', {'O2', 'O1'})
        out = fk.to_sql_str().format(
            ftable='iteration_log', fcol='order_id', run_id=7,
        )
        self.assertEqual(
            out,
            'INNER JOIN (SELECT `run_id`, `order_id` FROM `demand` '
            "WHERE `run_id` = 7 AND `order_id` IN ('O1', 'O2')) "
            'AS `fk_order_id` '
            'ON `iteration_log`.`run_id` = `fk_order_id`.`run_id` '
            'AND `iteration_log`.`order_id` = `fk_order_id`.`order_id`',
        )


# ===================================================================
# 7. Read layer (sqlload) — Query (MySQL-gated)
# ===================================================================

class _CountingCursor:
    """Wraps a real cursor, counting `execute` calls (to check lazy loading)."""

    def __init__(self, cur):
        self._cur = cur
        self.executes = 0

    def execute(self, sql, *args, **kw):
        self.executes += 1
        return self._cur.execute(sql, *args, **kw)

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()


class QueryMySQLTests(unittest.TestCase):
    """`Query` against a populated run in the local test MySQL. Skips when the
    server / driver is unavailable. `CHUNK_SIZE` is shrunk so the fixture spans
    several chunks; the original is restored in `tearDownClass`."""

    CHUNK = 50

    @classmethod
    def setUpClass(cls):
        try:
            _connect(_ADMIN).close()
        except Exception as exc:
            raise unittest.SkipTest(f'test MySQL {_DB!r} unreachable: {exc}')
        cls.dl = _build_debug_log()
        plan(_make_state(), Costing(_weights()), debuglog=cls.dl)
        conn = _connect(_ADMIN)                     # clean slate
        try:
            with conn.cursor() as cur:
                cur.execute('SET FOREIGN_KEY_CHECKS=0')
                for spec in manifest.ALL_TABLES:
                    cur.execute(f'TRUNCATE TABLE `{spec.name}`')
                cur.execute('SET FOREIGN_KEY_CHECKS=1')
            conn.commit()
        finally:
            conn.close()
        cls.run_id = persist_run(
            cls.dl, ConnConfig(_HOST, _PORT, _DB, *_WRITER),
            start_date=datetime.date(2026, 5, 18), total_score=0.0, n_unmet=0,
        )
        cls.rconn = _connect(_READER)
        cls._orig_chunk = (sqlquery.CHUNK_SIZE, sqlquery._HALF)
        sqlquery.CHUNK_SIZE = cls.CHUNK
        sqlquery._HALF = cls.CHUNK // 2

    @classmethod
    def tearDownClass(cls):
        sqlquery.CHUNK_SIZE, sqlquery._HALF = cls._orig_chunk
        cls.rconn.close()

    # ----- helpers -------------------------------------------------------

    def _fetch(self, sql, params=()):
        with self.rconn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def _ordered(self, table, extra='', params=()):
        """The run's rows for `table`, display columns in order, ordered by the
        spec's `order_columns` — the independent oracle for chunk contents."""
        spec = spec_for_name(table)
        cols = [c for c in spec.column_names if c != manifest.RUN_ID]
        collist = ', '.join(f'`{c}`' for c in cols)
        order = ', '.join(f'`{c}`' for c in spec.order_columns)
        sql = f'SELECT {collist} FROM `{table}` WHERE run_id=%s'
        if extra:
            sql += ' AND ' + extra
        sql += f' ORDER BY {order}'
        return list(self._fetch(sql, (self.run_id,) + tuple(params)))

    def _build(self, table, **conds):
        return Query.build(self.rconn.cursor(), self.run_id, table, **conds)

    # ----- 7.1 build column validation -----------------------------------

    def test_build_rejects_unknown_column(self):
        with self.assertRaises(ValueError):
            Query.build(self.rconn.cursor(), self.run_id, 'cost_summary',
                        nope=Filter('selection', {1}))

    def test_build_rejects_non_constraint(self):
        with self.assertRaises(TypeError):
            Query.build(self.rconn.cursor(), self.run_id, 'cost_summary',
                        cost='not-a-filter')

    # ----- 7.2 nrows -----------------------------------------------------

    def test_nrows_within_chunk(self):
        q = self._build('production')
        self.assertEqual(q.nrows, len(self.dl.get_df('production')))
        self.assertLessEqual(q.nrows, self.CHUNK)

    def test_nrows_across_chunks(self):
        q = self._build('cost_summary')
        self.assertEqual(q.nrows, len(self.dl.get_df('cost_summary')))
        self.assertGreater(q.nrows, self.CHUNK)

    def test_nrows_filtered(self):
        kind = self._fetch(
            'SELECT kind FROM cost_summary WHERE run_id=%s LIMIT 1', (self.run_id,),
        )[0][0]
        q = self._build('cost_summary', kind=Filter('selection', {kind}))
        expected = self._fetch(
            'SELECT COUNT(*) FROM cost_summary WHERE run_id=%s AND kind=%s',
            (self.run_id, kind),
        )[0][0]
        self.assertGreater(expected, 0)
        self.assertEqual(q.nrows, expected)

    # ----- 7.3 unique ----------------------------------------------------

    def test_unique_matches_and_caps(self):
        q = self._build('cost_summary')
        for col in spec_for_name('cost_summary').column_names:
            n = self._fetch(
                f'SELECT COUNT(DISTINCT `{col}`) FROM cost_summary WHERE run_id=%s',
                (self.run_id,),
            )[0][0]
            with self.subTest(col=col):
                if n > self.CHUNK:                  # e.g. the PK summary_id
                    self.assertIsNone(q.unique(col))
                else:
                    vals = {r[0] for r in self._fetch(
                        f'SELECT DISTINCT `{col}` FROM cost_summary WHERE run_id=%s',
                        (self.run_id,),
                    )}
                    self.assertEqual(set(q.unique(col)), vals)

    # ----- 7.4 next_chunk / prev_chunk -----------------------------------

    def test_chunks_match_expected(self):
        rows = self._ordered('cost_summary')
        half = sqlquery._HALF
        q = self._build('cost_summary')
        for step in range(5):                       # forward, half-chunk steps
            chunk = q.next_chunk()
            start = step * half
            self.assertEqual(q.row_offset, start)
            self.assertEqual(list(chunk), rows[start:start + self.CHUNK])
        chunk = q.prev_chunk()                       # back one half-chunk
        start = 3 * half
        self.assertEqual(q.row_offset, start)
        self.assertEqual(list(chunk), rows[start:start + self.CHUNK])

    def test_lazy_loading(self):
        cur = _CountingCursor(self.rconn.cursor())
        q = Query.build(cur, self.run_id, 'cost_summary')
        cur.executes = 0
        q.next_chunk()                               # first chunk -> one fetch
        self.assertEqual(cur.executes, 1)
        before = q.row_offset
        q.next_chunk()                               # moves -> one more fetch
        self.assertEqual(cur.executes, 2)
        self.assertNotEqual(q.row_offset, before)
        prev = -1                                    # drive to the end
        while q.row_offset != prev:
            prev = q.row_offset
            q.next_chunk()
        n = cur.executes
        q.next_chunk()                               # at the end: no movement
        self.assertEqual(cur.executes, n)            # ... so no fetch

    def test_clamp_at_end(self):
        q = self._build('cost_summary')
        q.next_chunk()
        while True:
            before = q.row_offset
            chunk = q.next_chunk()
            if q.row_offset == before:
                break
        again = q.next_chunk()                       # past the end
        self.assertEqual(q.row_offset, before)
        self.assertEqual(list(again), list(chunk))

    def test_clamp_at_start(self):
        q = self._build('cost_summary')
        first = q.next_chunk()
        self.assertEqual(q.row_offset, 0)
        again = q.prev_chunk()                       # cannot retreat before row 0
        self.assertEqual(q.row_offset, 0)
        self.assertEqual(list(again), list(first))


# ===================================================================
# 8. Read layer (sqlload) — Table / Row paging (MySQL-gated)
# ===================================================================

class TableMySQLTests(unittest.TestCase):
    """`Table` paging against a populated run. Skips when MySQL is unavailable.
    `CHUNK_SIZE` and the page-size cap are shrunk (and the page size set) so a
    few-hundred-row fixture spans several chunks and pages; all shared state is
    restored in `tearDownClass`."""

    CHUNK = 50
    PAGE = 10

    @classmethod
    def setUpClass(cls):
        try:
            _connect(_ADMIN).close()
        except Exception as exc:
            raise unittest.SkipTest(f'test MySQL {_DB!r} unreachable: {exc}')
        cls.dl = _build_debug_log()
        plan(_make_state(), Costing(_weights()), debuglog=cls.dl)
        conn = _connect(_ADMIN)
        try:
            with conn.cursor() as cur:
                cur.execute('SET FOREIGN_KEY_CHECKS=0')
                for spec in manifest.ALL_TABLES:
                    cur.execute(f'TRUNCATE TABLE `{spec.name}`')
                cur.execute('SET FOREIGN_KEY_CHECKS=1')
            conn.commit()
        finally:
            conn.close()
        cls.run_id = persist_run(
            cls.dl, ConnConfig(_HOST, _PORT, _DB, *_WRITER),
            start_date=datetime.date(2026, 5, 18), total_score=0.0, n_unmet=0,
        )
        cls.rconn = _connect(_READER)
        cls._orig = (sqlquery.CHUNK_SIZE, sqlquery._HALF,
                     sqltable._MAX_PAGE_SIZE, Table._page_size)
        sqlquery.CHUNK_SIZE = cls.CHUNK
        sqlquery._HALF = cls.CHUNK // 2
        sqltable._MAX_PAGE_SIZE = cls.CHUNK // 2          # page must fit a half-chunk

    @classmethod
    def tearDownClass(cls):
        (sqlquery.CHUNK_SIZE, sqlquery._HALF,
         sqltable._MAX_PAGE_SIZE, Table._page_size) = cls._orig
        cls.rconn.close()

    def setUp(self):
        Table.set_page_size(self.PAGE)                   # known size each test

    # ----- helpers -------------------------------------------------------

    def _table(self, name):
        return Table(spec_for_name(name), self.rconn.cursor(), self.run_id)

    def _ordered(self, table):
        spec = spec_for_name(table)
        cols = ', '.join(
            f'`{c}`' for c in spec.column_names if c != manifest.RUN_ID
        )
        order = ', '.join(f'`{c}`' for c in spec.order_columns)
        with self.rconn.cursor() as cur:
            cur.execute(
                f'SELECT {cols} FROM `{table}` WHERE run_id=%s ORDER BY {order}',
                (self.run_id,),
            )
            return list(cur.fetchall())

    @staticmethod
    def _data(page):
        return [r.data for r in page]

    def _to_last_page(self, t, page=None):
        """Page `t` to its last page; return the last page's rows."""
        page = page or self.PAGE
        rows = t.next_page()
        last_start = ((t.nrows - 1) // page) * page
        while t.displayed_range[0] < last_start:
            rows = t.next_page()
        return rows, last_start

    # ----- 8.1 initial state ---------------------------------------------

    def test_initial_state(self):
        t = self._table('cost_summary')
        self.assertEqual(t.nrows, len(self.dl.get_df('cost_summary')))
        self.assertEqual(t.selected_keys, set())
        self.assertEqual(t.displayed_range, (0, 0))
        self.assertIsNone(t._chunk)
        self.assertTrue(all(v is None for v in t._conds.values()))
        self.assertEqual(t._offset, 0)

    # ----- 8.2 after the first next_page ---------------------------------

    def test_after_first_next_page(self):
        t = self._table('cost_summary')
        n0 = t.nrows
        page = t.next_page()
        self.assertEqual(t.nrows, n0)
        self.assertEqual(t.selected_keys, set())
        self.assertIsNotNone(t._chunk)
        self.assertEqual(self._data(page), self._ordered('cost_summary')[:self.PAGE])
        self.assertEqual(t.displayed_range, (0, self.PAGE))

    # ----- 8.3 next_page then prev_page round-trip -----------------------

    def test_next_then_prev_round_trip(self):
        t = self._table('cost_summary')
        first = t.next_page()
        r0 = t.displayed_range
        t.next_page()
        back = t.prev_page()
        self.assertEqual(t.displayed_range, r0)
        self.assertEqual(self._data(back), self._data(first))
        self.assertEqual(t.nrows, len(self.dl.get_df('cost_summary')))
        self.assertEqual(t.selected_keys, set())

    # ----- 8.4 next_page on the last page --------------------------------

    def test_next_page_on_last_page_is_idempotent(self):
        t = self._table('cost_summary')
        last, _ = self._to_last_page(t)
        dr, off, chunk = t.displayed_range, t._offset, t._chunk
        again = t.next_page()
        self.assertEqual(t.displayed_range, dr)
        self.assertEqual(self._data(again), self._data(last))
        self.assertEqual(t._offset, off)
        self.assertEqual(t._chunk, chunk)

    # ----- 8.5 prev_page -------------------------------------------------

    def test_prev_page_moves_back(self):
        t = self._table('cost_summary')
        first = t.next_page()
        t.next_page()
        back = t.prev_page()
        self.assertEqual(t.displayed_range, (0, self.PAGE))
        self.assertEqual(self._data(back), self._data(first))
        self.assertEqual(t.nrows, len(self.dl.get_df('cost_summary')))
        self.assertEqual(t.selected_keys, set())

    def test_prev_page_on_first_page_is_idempotent(self):
        t = self._table('cost_summary')
        first = t.next_page()
        dr, off, chunk = t.displayed_range, t._offset, t._chunk
        again = t.prev_page()
        self.assertEqual(t.displayed_range, dr)
        self.assertEqual(self._data(again), self._data(first))
        self.assertEqual(t._offset, off)
        self.assertEqual(t._chunk, chunk)

    # ----- 8.6 row counts vs. page size ----------------------------------

    def test_displayed_range_capped_at_nrows(self):
        t = self._table('cost_summary')
        self._to_last_page(t)
        self.assertEqual(t.displayed_range[1], t.nrows)         # ends exactly at nrows

    def test_whole_table_in_one_page(self):
        Table.set_page_size(20)                                 # >= priority_detail's rows
        t = self._table('priority_detail')
        t.next_page()
        self.assertLessEqual(t.nrows, 20)
        self.assertEqual(t.displayed_range, (0, t.nrows))

    def test_set_page_size_rejects_invalid(self):
        orig = Table._page_size
        for bad in (0, -1, sqltable._MAX_PAGE_SIZE + 1, 2.5):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    Table.set_page_size(bad)
        self.assertEqual(Table._page_size, orig)                # unchanged

    def test_resize_then_reload_keeps_start(self):
        rows = self._ordered('cost_summary')
        t = self._table('cost_summary')
        t.next_page(); t.next_page()                            # start 10
        start = t.displayed_range[0]
        Table.set_page_size(5)                                  # shrink
        page = t.reload_page()
        self.assertEqual(t.displayed_range, (start, start + 5))
        self.assertEqual(self._data(page), rows[start:start + 5])
        Table.set_page_size(20)                                 # grow
        page = t.reload_page()
        self.assertEqual(t.displayed_range, (start, start + 20))
        self.assertEqual(self._data(page), rows[start:start + 20])

    def test_reload_vs_next_page_on_last_page_after_resize(self):
        Table.set_page_size(15)
        t = self._table('cost_summary')
        _, last_start = self._to_last_page(t, page=15)          # last 15-page start
        Table.set_page_size(20)
        t.reload_page()                                         # keeps the same first row
        self.assertEqual(t.displayed_range[0], last_start)
        self.assertEqual(t.displayed_range[1], t.nrows)         # a partial page to the end
        t.next_page()                                           # re-aligns to a 20-boundary
        aligned = ((t.nrows - 1) // 20) * 20
        self.assertEqual(t.displayed_range[0], aligned)
        self.assertNotEqual(aligned, last_start)                # the two genuinely differ


# ===================================================================
# 9. Read layer (sqlload) — selection & filtering (MySQL-gated)
# ===================================================================

class SelectFilterMySQLTests(unittest.TestCase):
    """Row selection, filters, and FK lookups against a populated run. Skips
    when MySQL is unavailable. The page size is set large enough that a filtered
    result fits in one page (so a single `next_page()` is the whole result);
    `Table._page_size` is restored in `tearDownClass`."""

    @classmethod
    def setUpClass(cls):
        try:
            _connect(_ADMIN).close()
        except Exception as exc:
            raise unittest.SkipTest(f'test MySQL {_DB!r} unreachable: {exc}')
        cls.dl = _build_debug_log()
        plan(_make_state(), Costing(_weights()), debuglog=cls.dl)
        conn = _connect(_ADMIN)
        try:
            with conn.cursor() as cur:
                cur.execute('SET FOREIGN_KEY_CHECKS=0')
                for spec in manifest.ALL_TABLES:
                    cur.execute(f'TRUNCATE TABLE `{spec.name}`')
                cur.execute('SET FOREIGN_KEY_CHECKS=1')
            conn.commit()
        finally:
            conn.close()
        cls.run_id = persist_run(
            cls.dl, ConnConfig(_HOST, _PORT, _DB, *_WRITER),
            start_date=datetime.date(2026, 5, 18), total_score=0.0, n_unmet=0,
        )
        cls.rconn = _connect(_READER)
        cls._orig_page = Table._page_size

    @classmethod
    def tearDownClass(cls):
        Table._page_size = cls._orig_page
        cls.rconn.close()

    def setUp(self):
        Table.set_page_size(1000)            # whole fixture fits in one page

    # ----- helpers -------------------------------------------------------

    def _table(self, name):
        return Table(spec_for_name(name), self.rconn.cursor(), self.run_id)

    def _fetch(self, sql, params=()):
        with self.rconn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def _ordered_where(self, table, where='1=1', params=()):
        spec = spec_for_name(table)
        cols = ', '.join(
            f'`{c}`' for c in spec.column_names if c != manifest.RUN_ID
        )
        order = ', '.join(f'`{c}`' for c in spec.order_columns)
        return list(self._fetch(
            f'SELECT {cols} FROM `{table}` WHERE run_id=%s AND {where} '
            f'ORDER BY {order}', (self.run_id,) + tuple(params),
        ))

    @staticmethod
    def _data(page):
        return [r.data for r in page]

    def _committed_order_id(self):
        return self._fetch(
            "SELECT order_id FROM iteration_log WHERE run_id=%s "
            "AND role='committed' AND order_id IS NOT NULL LIMIT 1", (self.run_id,),
        )[0][0]

    # ----- 9.1 Row selection ---------------------------------------------

    def test_select_keyless_raises(self):
        row = self._table('priority_detail').next_page()[0]
        self.assertIsNone(row.pk_col)
        with self.assertRaises(TypeError):
            row.select()
        with self.assertRaises(TypeError):
            row.deselect()

    def test_redundant_select_deselect_are_noops(self):
        t = self._table('iteration_log')
        row = t.next_page()[0]
        row.select()
        keys = t.selected_keys
        row.select()                                 # already selected
        self.assertEqual(t.selected_keys, keys)
        row.deselect()
        self.assertEqual(t.selected_keys, set())
        row.deselect()                               # not selected
        self.assertEqual(t.selected_keys, set())

    def test_select_updates_selected_keys(self):
        t = self._table('iteration_log')
        rows = t.next_page()
        r0, r1 = rows[0], rows[1]
        r0.select()
        r1.select()
        self.assertEqual(
            t.selected_keys, {r0.get('move_id'), r1.get('move_id')},
        )
        self.assertTrue(r0.selected)
        r0.deselect()
        self.assertEqual(t.selected_keys, {r1.get('move_id')})
        self.assertFalse(r0.selected)

    def test_selection_survives_paging(self):
        Table.set_page_size(5)                       # several pages over 16 rows
        t = self._table('iteration_log')
        page1 = t.next_page()
        key = page1[0].get('move_id')
        page1[0].select()
        t.next_page()                                # page 2
        back = t.prev_page()                         # back to page 1
        self.assertIn(key, t.selected_keys)
        self.assertTrue(back[0].selected)

    # ----- 9.2 Filters ---------------------------------------------------

    def test_apply_filter_resets_state(self):
        t = self._table('iteration_log')
        t.next_page()[0].select()
        self.assertTrue(t.selected_keys)
        t.apply_filter_to('role', 'selection', {'committed'})
        self.assertIsInstance(t._conds['role'], Filter)
        self.assertIsNone(t._chunk)
        self.assertEqual(t._offset, 0)
        self.assertEqual(t.selected_keys, set())

    def test_filtered_rows(self):
        t = self._table('iteration_log')
        t.apply_filter_to('role', 'selection', {'committed'})
        expected = self._ordered_where('iteration_log', 'role=%s', ('committed',))
        self.assertEqual(t.nrows, len(expected))
        self.assertEqual(self._data(t.next_page()), expected)

    def test_remove_filter_without_one_resets_and_keeps_full(self):
        t = self._table('iteration_log')
        t.next_page()[0].select()
        t.remove_filter('role')                      # no filter on role yet
        self.assertEqual(t.selected_keys, set())     # still a rebuild/reset
        self.assertEqual(t.nrows, len(self.dl.get_df('iteration_log')))
        self.assertEqual(self._data(t.next_page()), self._ordered_where('iteration_log'))

    def test_remove_active_filter_restores_full(self):
        t = self._table('iteration_log')
        t.apply_filter_to('role', 'selection', {'committed'})
        self.assertLess(t.nrows, len(self.dl.get_df('iteration_log')))
        t.remove_filter('role')
        self.assertEqual(t.nrows, len(self.dl.get_df('iteration_log')))
        self.assertEqual(self._data(t.next_page()), self._ordered_where('iteration_log'))

    def test_two_filters_remove_one(self):
        oid = self._committed_order_id()
        t = self._table('iteration_log')
        t.apply_filter_to('role', 'selection', {'committed'})
        t.apply_filter_to('order_id', 'selection', {oid})
        committed = self._ordered_where('iteration_log', 'role=%s', ('committed',))
        self.assertLess(t.nrows, len(committed))     # order_id genuinely subsets
        t.remove_filter('order_id')
        self.assertEqual(t.nrows, len(committed))
        self.assertEqual(self._data(t.next_page()), committed)

    # ----- 9.3 FK lookups ------------------------------------------------

    def test_fk_lookup_on_non_fk_raises(self):
        t = self._table('iteration_log')
        with self.assertRaises(KeyError):
            t.apply_fk_lookup('machine', {'M1'})     # a column, but not an FK
        with self.assertRaises(KeyError):
            t.apply_fk_lookup('nope', {'x'})         # not a column at all

    def test_fk_lookup_selects_matching_rows(self):
        oid = self._committed_order_id()
        t = self._table('iteration_log')
        t.apply_fk_lookup('order_id', {oid})
        expected = self._ordered_where('iteration_log', 'order_id=%s', (oid,))
        self.assertGreater(len(expected), 0)
        self.assertEqual(t.nrows, len(expected))
        self.assertEqual(self._data(t.next_page()), expected)

    def test_fk_lookup_end_to_end_routing(self):
        # Select demand PKs, then route them into iteration_log's FK column.
        t1 = self._table('demand')
        picked = t1.next_page()[:2]
        for r in picked:
            r.select()
        keys = t1.selected_keys
        t2 = self._table('iteration_log')
        t2.apply_fk_lookup('order_id', keys)
        placeholders = ', '.join(['%s'] * len(keys))
        expected = self._ordered_where(
            'iteration_log', f'order_id IN ({placeholders})', tuple(keys),
        )
        self.assertGreater(len(expected), 0)
        self.assertEqual(t2.nrows, len(expected))
        self.assertEqual(self._data(t2.next_page()), expected)

    def test_remove_filter_clears_fk_lookup(self):
        oid = self._committed_order_id()
        t = self._table('iteration_log')
        t.apply_fk_lookup('order_id', {oid})
        self.assertLess(t.nrows, len(self.dl.get_df('iteration_log')))
        t.remove_filter('order_id')
        self.assertEqual(t.nrows, len(self.dl.get_df('iteration_log')))
        self.assertEqual(self._data(t.next_page()), self._ordered_where('iteration_log'))

    def test_remove_fk_leaves_other_filters(self):
        oid = self._committed_order_id()
        t = self._table('iteration_log')
        t.apply_filter_to('role', 'selection', {'committed'})
        t.apply_fk_lookup('order_id', {oid})
        committed = self._ordered_where('iteration_log', 'role=%s', ('committed',))
        self.assertLess(t.nrows, len(committed))     # the FK lookup subsets
        t.remove_filter('order_id')                  # drop only the FK lookup
        self.assertEqual(t.nrows, len(committed))    # the role filter remains
        self.assertEqual(self._data(t.next_page()), committed)


if __name__ == '__main__':
    unittest.main()
