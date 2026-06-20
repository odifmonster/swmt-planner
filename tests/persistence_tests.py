#!/usr/bin/env python

"""Coverage of the infinite planner's debug-log persistence — its concrete
`manifest` (checked against the live `DebugLog`) and the `sqldump` writer (pure
helpers + a MySQL-gated end-to-end). See
`tests/spec-files/PERSISTENCE_TEST_SPEC.md`."""

import datetime
import os
import unittest
from dataclasses import fields

import numpy as np
import pandas as pd

from swmtplanner.planners.infinite import Costing
from swmtplanner.planners.infinite.loop import plan
from swmtplanner.planners.infinite.run import _build_debug_log
from swmtplanner.planners.infinite import manifest
from swmtplanner.planners.infinite.manifest import (
    Column, ForeignKey, TableSpec, spec_for_name,
)
from swmtplanner.debuglog import DebugLog
from swmtplanner.planners.infinite.sqldump import persistence
from swmtplanner.planners.infinite.sqldump.persistence import (
    PersistenceError, persist_run,
)
from swmtplanner.dashboard.config import ConnConfig

from inf_plan_tests import _make_state, _weights
from mysql_support import _HOST, _PORT, _DB, _WRITER, _READER, _ADMIN, _connect


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
                # Both are tuples now (empty for a key-less table).
                self.assertEqual(spec.pk, self.schema[spec.name].pk)

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

    def test_run_configs_composite_key_no_fks(self):
        cfg = spec_for_name('run_configs')
        self.assertEqual(cfg.pk, ('kind', 'label'))           # composite
        self.assertEqual(cfg.fks, ())
        self.assertEqual(cfg.column_names, ('kind', 'label', 'value'))

    def test_iteration_states_keyed_and_referenced_by_log(self):
        states = spec_for_name('iteration_states')
        self.assertEqual(states.pk, ('iteration_idx',))
        self.assertEqual(states.fks, ())
        # iteration_log.iteration_idx is an FK onto it.
        log = spec_for_name('iteration_log')
        self.assertIn(
            ForeignKey('iteration_idx', 'iteration_states', 'iteration_idx'),
            log.fks,
        )
        # ...and iteration_states is inserted before iteration_log.
        names = [t.name for t in manifest.TABLES]
        self.assertLess(
            names.index('iteration_states'), names.index('iteration_log'),
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

    def test_committed_views_registered_but_not_writable(self):
        self.assertEqual(
            {v.name for v in manifest.VIEWS},
            {'committed_sched', 'committed_prod'},
        )
        writable = {t.name for t in manifest.ALL_TABLES}
        for v in manifest.VIEWS:
            with self.subTest(view=v.name):
                self.assertIs(spec_for_name(v.name), v)   # resolvable
                self.assertNotIn(v.name, writable)        # writer never touches it
                self.assertTrue(v.order_by)               # keeps the view's order
                # Keyed by the identity column it carries over, which is also an
                # FK back to sched_cost_detail (drill to the full activity row).
                self.assertEqual(len(v.pk), 1)
                self.assertEqual(v.fks, (ForeignKey(
                    v.pk[0], 'sched_cost_detail', 'activity_id'),))
                # order_by overrides the pk for display order (machine/start, …).
                self.assertNotEqual(v.order_columns, v.pk)


# ===================================================================
# 3. Persistence — pure helpers (no server)
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

    def test_project_rows_composite_pk_exposes_all_columns(self):
        # A composite-PK table keeps its PK columns as ordinary columns in
        # get_df, so project_rows yields run_id + every column (PK included).
        dl = DebugLog(cfg=[('kind', None), ('label', None), ('value', None)])
        dl.set_pk('cfg', 'kind', 'label')
        dl.add_row('cfg', kind='cost', label='lateness', value=1.5)
        dl.add_row('cfg', kind='state', label='window_adv', value=24.0)
        spec = TableSpec(
            'cfg', 'Cfg', '',
            (Column('kind', 'str'), Column('label', 'str'),
             Column('value', 'float', nullable=True)),
            pk=('kind', 'label'),
        )
        rows = sorted(persistence.project_rows(dl, spec, run_id=7))
        self.assertEqual(rows, [
            (7, 'cost', 'lateness', 1.5),
            (7, 'state', 'window_adv', 24.0),
        ])



# ===================================================================
# 3b. Debug-log population of run_configs / iteration_states (no server)
# ===================================================================

class DebugLogPopulationTests(unittest.TestCase):
    """`plan(..., debuglog=dl)` fills the new config / per-iteration tables.
    Pure — drives a small in-memory run, no MySQL."""

    @classmethod
    def setUpClass(cls):
        cls.dl = _populated_log()

    def test_run_configs_cost_rows_match_weights(self):
        df = self.dl.get_df('run_configs')
        cost = df[df.kind == 'cost']
        weights = _weights()
        expected = {f.name: float(getattr(weights, f.name))
                    for f in fields(weights)}
        self.assertEqual(dict(zip(cost.label, cost.value)), expected)

    def test_run_configs_state_rows_with_units(self):
        df = self.dl.get_df('run_configs')
        got = dict(zip(df[df.kind == 'state'].label,
                       df[df.kind == 'state'].value))
        # timedelta knobs recorded in hours; scalar knobs as-is (State defaults).
        self.assertEqual(got['window_advance_amount'], 24.0)
        self.assertEqual(got['carrying_avoidance_margin'], 24.0)
        self.assertEqual(got['planning_horizon_buffer'], 672.0)     # 4 weeks
        self.assertEqual(got['candidate_threshold'], 1.0)
        self.assertEqual(got['reference_week_idx'], 1.0)
        self.assertEqual(got['reference_advance_amount'], 1.0)
        self.assertEqual(got['reference_threshold'], 5.0)

    def test_iteration_states_cover_iteration_log(self):
        states = self.dl.get_df('iteration_states')
        log = self.dl.get_df('iteration_log')
        self.assertTrue(len(states) > 0)
        # One state row per distinct iteration_idx in the log (FK satisfiable).
        self.assertEqual(set(states.index), set(log['iteration_idx']))
        # window_end / reference_week are populated.
        self.assertTrue(states['window_end'].notna().all())
        self.assertTrue(states['reference_week'].notna().all())


# ===================================================================
# 4. persist_run end-to-end (MySQL-gated)
# ===================================================================

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
            'user': _WRITER[0], 'password': _WRITER[1],
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


if __name__ == '__main__':
    unittest.main()
