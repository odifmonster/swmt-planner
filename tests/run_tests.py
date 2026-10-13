#!/usr/bin/env python

"""Coverage of the `run.py` CLI helpers added for verbose-mode persistence —
the `database`-block override resolution and the interactive `vi` notes flow.
See `tests/spec-files/RUN_TEST_SPEC.md`. The full `run()` invocation and the
DB-touching `_persist_debuglog` are covered elsewhere (manual CLI runs;
`dashboard_tests.py`'s SQL Server-gated wiring tests)."""

import json
from datetime import timedelta
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import importlib

import typer

# The package re-exports a `run` *function*, which shadows the `run` submodule
# as a package attribute — so plain `import …run as run` resolves to the
# function. Fetch the actual module from sys.modules via importlib.
run = importlib.import_module('swmtplanner.planners.infinite.run')


class _ChdirTmp(unittest.TestCase):
    """Base: each test runs in a fresh temp cwd (so `temp*.txt` never touches
    the repo) and is restored afterward."""

    def setUp(self):
        self._prev = os.getcwd()
        self._tmp = tempfile.mkdtemp()
        os.chdir(self._tmp)
        self.addCleanup(lambda: os.chdir(self._prev))


class ResolveDbBlockTests(unittest.TestCase):

    def test_inline_json_override(self):
        self.assertEqual(
            run._resolve_db_block('{"name": "x", "port": 3306}', None),
            {'name': 'x', 'port': 3306},
        )

    def test_path_override(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'db.json'
            p.write_text('{"name": "fromfile"}')
            self.assertEqual(
                run._resolve_db_block(str(p), None), {'name': 'fromfile'},
            )

    def test_falls_back_to_config_value(self):
        self.assertEqual(
            run._resolve_db_block(None, {'name': 'cfg'}), {'name': 'cfg'},
        )
        self.assertIsNone(run._resolve_db_block(None, None))


class NextTempPathTests(_ChdirTmp):

    def test_picks_first_free_name(self):
        self.assertEqual(run._next_temp_path(), Path('temp.txt'))
        Path('temp.txt').touch()
        self.assertEqual(run._next_temp_path(), Path('temp1.txt'))
        Path('temp1.txt').touch()
        self.assertEqual(run._next_temp_path(), Path('temp2.txt'))


class _FakeVi:
    """Stand-in for `subprocess.Popen(['vi', path])`: writes `content` to the
    target file (like the user editing + saving), then acts as the process."""

    def __init__(self, content):
        self.content = content

    def __call__(self, args, *a, **k):
        Path(args[1]).write_text(self.content)
        return self

    def wait(self):
        return 0


class GatherNotesTests(_ChdirTmp):

    def test_returns_contents_and_deletes_temp(self):
        with mock.patch.object(run.subprocess, 'Popen', _FakeVi('hello notes\nmore\n')):
            self.assertEqual(run._gather_notes(), 'hello notes\nmore\n')
        self.assertEqual(list(Path('.').glob('temp*.txt')), [])   # cleaned up

    def test_whitespace_only_exits_and_cleans_up(self):
        with mock.patch.object(run.subprocess, 'Popen', _FakeVi('   \n\n\t\n')):
            with self.assertRaises(typer.Exit):
                run._gather_notes()
        self.assertEqual(list(Path('.').glob('temp*.txt')), [])

    def test_vi_not_found_exits_and_cleans_up(self):
        def _boom(*a, **k):
            raise FileNotFoundError("no 'vi'")
        with mock.patch.object(run.subprocess, 'Popen', _boom):
            with self.assertRaises(typer.Exit):
                run._gather_notes()
        self.assertEqual(list(Path('.').glob('temp*.txt')), [])


class ParseDurationTests(unittest.TestCase):
    """Section 4: the `state` block's duration spellings."""

    def test_numbers_are_hours(self):
        self.assertEqual(run._parse_duration(24, 'x'), timedelta(hours=24))
        self.assertEqual(run._parse_duration(1.5, 'x'), timedelta(hours=1, minutes=30))

    def test_unit_strings(self):
        self.assertEqual(run._parse_duration('48h', 'x'), timedelta(hours=48))
        self.assertEqual(run._parse_duration('3d', 'x'), timedelta(days=3))
        self.assertEqual(run._parse_duration('2w', 'x'), timedelta(days=14))
        self.assertEqual(run._parse_duration('90m', 'x'), timedelta(minutes=90))
        self.assertEqual(run._parse_duration(' 2 D ', 'x'), timedelta(days=2))

    def test_clock_form(self):
        self.assertEqual(run._parse_duration('36:30', 'x'), timedelta(hours=36, minutes=30))

    def test_negative(self):
        self.assertEqual(run._parse_duration('-2w', 'x'), -timedelta(days=14))
        self.assertEqual(run._parse_duration(-14, 'x'), -timedelta(hours=14))

    def test_timedelta_passes_through(self):
        td = timedelta(hours=5)
        self.assertIs(run._parse_duration(td, 'x'), td)

    def test_rejects_name_the_field(self):
        for bad in ('soon', '', True):
            with self.assertRaises(typer.BadParameter) as cm:
                run._parse_duration(bad, 'window_advance_amount')
            self.assertIn('window_advance_amount', str(cm.exception))

    def test_parse_state_block(self):
        src = {'window_advance_amount': '48h', 'carrying_avoidance_margin': 72,
               'planning_horizon_buffer': '-1w', 'candidate_threshold': 10,
               'reference_threshold': 5}
        out = run._parse_state_block(src)
        self.assertEqual(out['window_advance_amount'], timedelta(hours=48))
        self.assertEqual(out['carrying_avoidance_margin'], timedelta(hours=72))
        self.assertEqual(out['planning_horizon_buffer'], -timedelta(days=7))
        self.assertEqual(out['candidate_threshold'], 10)
        self.assertEqual(out['reference_threshold'], 5)
        self.assertEqual(src['window_advance_amount'], '48h')   # input untouched
        self.assertEqual(run._parse_state_block({}), {})


if __name__ == '__main__':
    unittest.main()


# ---------------------------------------------------------------------------
# 5. `blacklisted_on_machines`

from datetime import datetime as _datetime
from swmtplanner.products import Greige as _Greige, BeamSet as _BeamSet, BeamSetDesc as _BeamSetDesc
from swmtplanner.schedule import Machine as _Machine
from swmtplanner.support import WorkCal as _WorkCal

_ITEM = _Greige('AU0001', family='A', tgt_wt=100.0, top_beam='40D BLACK 1000X4', top_pct=0.5,
                btm_beam='60D WHITE 1000X4', btm_pct=0.5, safety=0.0, machines={'M1': 100.0, 'M2': 100.0})
_T0 = _datetime(2026, 5, 18)
_CAL = _WorkCal(work_days=(0, 1, 2, 3, 4, 5, 6), day_start=0, day_end=24, holidays=())


def _set(no, merge, label, **kw):
    return _BeamSet(no, merge, 900.0, _BeamSetDesc(label), _T0, vendor='V', known_merge=True, **kw)


class BlacklistedOnMachinesTests(unittest.TestCase):

    def test_lines(self):
        m1 = _Machine('M1', _ITEM, _T0, _set('S1', 'MK', '40D BLACK 1000X4', blacklisted=True), 900.0,
                      _set('S2', 'M3', '60D WHITE 1000X4'), 900.0, _CAL,
                      init_btm_queue=(_set('Q1', 'MK', '60D WHITE 1000X4', assigned=True, blacklisted=True),
                                      _set('Q2', 'M3', '60D WHITE 1000X4', assigned=True)))
        m2 = _Machine('M2', _ITEM, _T0, _set('S3', 'M1', '40D BLACK 1000X4'), 900.0,
                      _set('S4', 'M3', '60D WHITE 1000X4'), 900.0, _CAL)
        lines = run.blacklisted_on_machines({'M2': m2, 'M1': m1})
        self.assertEqual(len(lines), 2)
        self.assertIn('M1', lines[0]); self.assertIn('top', lines[0]); self.assertIn('mounted set S1', lines[0])
        self.assertIn('merge MK', lines[0]); self.assertIn('tapes it out', lines[0])
        self.assertIn('btm', lines[1]); self.assertIn('queued set Q1', lines[1]); self.assertIn('passed over', lines[1])

    def test_nothing(self):
        m2 = _Machine('M2', _ITEM, _T0, _set('S3', 'M1', '40D BLACK 1000X4'), 900.0,
                      _set('S4', 'M3', '60D WHITE 1000X4'), 900.0, _CAL)
        self.assertEqual(run.blacklisted_on_machines({'M2': m2}), [])
