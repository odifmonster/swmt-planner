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
from swmtplanner.planners.infinite.dashboard import manifest, persistence
from swmtplanner.planners.infinite.dashboard.manifest import (
    ForeignKey, spec_for_debuglog, spec_for_table,
)
from swmtplanner.planners.infinite.dashboard.config import (
    ConnConfig, DatabaseConfigError, resolve_conn_config,
)
from swmtplanner.planners.infinite.dashboard.persistence import (
    PersistenceError, persist_run,
)

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
        manifest_names = {t.debuglog for t in manifest.TABLES}
        self.assertEqual(manifest_names, set(self.schema))

    def test_columns_are_identity(self):
        for spec in manifest.TABLES:
            with self.subTest(table=spec.debuglog):
                self.assertEqual(
                    set(spec.column_names),
                    set(self.schema[spec.debuglog].columns),
                )

    def test_primary_keys_match(self):
        for spec in manifest.TABLES:
            with self.subTest(table=spec.debuglog):
                pk = self.schema[spec.debuglog].pk
                self.assertEqual(spec.pk, (pk,) if pk is not None else ())

    def test_manifest_fks_superset_of_debuglog(self):
        by_dbg = {t.debuglog: t.table for t in manifest.TABLES}
        for spec in manifest.TABLES:
            for fk in self.schema[spec.debuglog].fks:
                mapped = ForeignKey(fk.column, by_dbg[fk.ref_table], fk.ref_column)
                with self.subTest(table=spec.debuglog, fk=fk.column):
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
                    f'{spec.table}.{fk.column} -> {fk.ref_table} '
                    f'references a table not inserted yet',
                )
            seen.add(spec.table)

    def test_production_has_extra_schedule_link(self):
        prod = spec_for_debuglog('production')
        self.assertIn(
            ForeignKey('knit_id', 'knitschedcost', 'activity_id'), prod.fks,
        )

    def test_run_registry(self):
        self.assertEqual(manifest.RUNS.table, 'knitruns')
        self.assertEqual(manifest.RUNS.pk, ('run_id',))
        self.assertIsNone(manifest.RUNS.debuglog)
        self.assertEqual(manifest.ALL_TABLES, (manifest.RUNS,) + manifest.TABLES)

    def test_lookups(self):
        self.assertEqual(spec_for_debuglog('demand').table, 'knitdmnd')
        self.assertEqual(spec_for_table('knitprod').debuglog, 'production')
        self.assertEqual(spec_for_table('knitruns'), manifest.RUNS)
        with self.assertRaises(KeyError):
            spec_for_debuglog('nope')
        with self.assertRaises(KeyError):
            spec_for_table('nope')


# ===================================================================
# 3. Connection-config resolution
# ===================================================================

def _block(**over):
    b = {
        'host': 'db.local', 'port': 3307, 'name': 'swmtplanner',
        'writer': {'user': 'w_user', 'password': 'w_pw'},
        'reader': {'user': 'r_user', 'password': 'r_pw'},
    }
    b.update(over)
    return b


class ConfigResolutionTests(unittest.TestCase):

    def test_resolves_per_role_from_block(self):
        w = resolve_conn_config(_block(), 'writer', env={})
        self.assertEqual(
            w, ConnConfig('db.local', 3307, 'swmtplanner', 'w_user', 'w_pw'),
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
        spec = spec_for_debuglog('sched_cost_detail')
        sql = persistence.insert_sql(spec)
        self.assertTrue(sql.startswith(
            'INSERT INTO `knitschedcost` (`run_id`, `activity_id`, `move_id`, '
        ))
        for col in ('desc', 'start', 'end'):       # reserved words backticked
            self.assertIn(f'`{col}`', sql)
        self.assertEqual(sql.count('%s'), 1 + len(spec.column_names))

    def test_project_rows_shape_and_counts(self):
        for name in ('iteration_log', 'cost_summary', 'priority_detail',
                     'production', 'unmet_demand'):
            spec = spec_for_debuglog(name)
            rows = list(persistence.project_rows(self.dl, spec, run_id=42))
            self.assertEqual(len(rows), len(self.dl.get_df(name)), name)
            for r in rows:
                self.assertEqual(r[0], 42)                         # run_id first
                self.assertEqual(len(r), 1 + len(spec.column_names))

    def test_project_rows_exposes_keyed_pk(self):
        spec = spec_for_debuglog('iteration_log')
        mi = spec.column_names.index('move_id')                   # the PK (index in get_df)
        rows = list(persistence.project_rows(self.dl, spec, run_id=1))
        self.assertTrue(rows)
        self.assertTrue(all(isinstance(r[1 + mi], int) for r in rows))

    def test_project_rows_empty_table_yields_nothing(self):
        spec = spec_for_debuglog('unmet_demand')                  # empty in this fixture
        self.assertEqual(list(persistence.project_rows(self.dl, spec, 1)), [])


# ===================================================================
# 5. persist_run end-to-end (MySQL-gated)
# ===================================================================

_HOST = os.environ.get('SWMT_TEST_DB_HOST', '127.0.0.1')
_PORT = int(os.environ.get('SWMT_TEST_DB_PORT', '3306'))
_DB = os.environ.get('SWMT_TEST_DB_NAME', 'swmtplannertests')
_WRITER = (os.environ.get('SWMT_TEST_WRITER_USER', 'swmtwritetests'),
           os.environ.get('SWMT_TEST_WRITER_PASSWORD', 'Writer-Password'))
_READER = (os.environ.get('SWMT_TEST_READER_USER', 'swmtreadtests'),
           os.environ.get('SWMT_TEST_READER_PASSWORD', 'Reader-Password'))
_ADMIN = (os.environ.get('SWMT_TEST_ADMIN_USER', 'stroot'),
          os.environ.get('SWMT_TEST_ADMIN_PASSWORD', 'SwmtR00tT3sts!'))


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
                    cur.execute(f'TRUNCATE TABLE `{spec.table}`')
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
        self.assertEqual(self._count('knitruns'), 1)
        score, n_unmet, start_date = self._query(
            'SELECT total_score, n_unmet, start_date FROM knitruns '
            'WHERE run_id=%s', (rid,),
        )[0]
        self.assertAlmostEqual(score, 123.5)
        self.assertEqual(n_unmet, 7)
        self.assertEqual(start_date, datetime.date(2026, 5, 18))
        # every table's row count for this run matches the in-memory log; a
        # successful insert also proves the FK-topological order held.
        for spec in manifest.TABLES:
            self.assertEqual(
                self._count(spec.table, rid),
                len(self.dl.get_df(spec.debuglog)), spec.table,
            )

    def test_role_column_round_trips(self):
        rid = persist_run(
            self.dl, self.writer_conn,
            start_date=datetime.date(2026, 5, 18), total_score=0.0, n_unmet=0,
        )
        roles = {r[0] for r in self._query(
            'SELECT DISTINCT role FROM knititerlog WHERE run_id=%s', (rid,),
        )}
        self.assertTrue(roles <= {'committed', 'rejected'})
        self.assertIn('committed', roles)
        db_committed = self._query(
            "SELECT COUNT(*) FROM knititerlog WHERE run_id=%s AND role='committed'",
            (rid,),
        )[0][0]
        il = self.dl.get_df('iteration_log')
        self.assertEqual(db_committed, int((il['role'] == 'committed').sum()))

    def test_distinct_run_ids_and_isolation(self):
        kw = dict(start_date=datetime.date(2026, 5, 18), total_score=1.0, n_unmet=0)
        rid1 = persist_run(self.dl, self.writer_conn, **kw)
        rid2 = persist_run(self.dl, self.writer_conn, **kw)
        self.assertNotEqual(rid1, rid2)
        self.assertEqual(self._count('knitruns'), 2)
        for spec in manifest.TABLES:
            n = len(self.dl.get_df(spec.debuglog))
            self.assertEqual(self._count(spec.table, rid1), n, spec.table)
            self.assertEqual(self._count(spec.table, rid2), n, spec.table)
            self.assertEqual(self._count(spec.table), 2 * n, spec.table)

    def test_reader_role_cannot_write(self):
        self.assertEqual(self._count('knitruns'), 0)
        with self.assertRaises(PersistenceError):
            persist_run(
                self.dl, self.reader_conn,
                start_date=datetime.date(2026, 5, 18), total_score=0.0, n_unmet=0,
            )
        self.assertEqual(self._count('knitruns'), 0)   # rollback / denied: nothing written

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
        self.assertEqual(self._count('knitruns'), 1)
        self.assertEqual(
            self._count('knititerlog', rid),
            len(self.dl.get_df('iteration_log')),
        )
        n_unmet, label, notes = self._query(
            'SELECT n_unmet, label, notes FROM knitruns WHERE run_id=%s', (rid,),
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
        self.assertEqual(self._count('knitruns'), 0)


if __name__ == '__main__':
    unittest.main()
