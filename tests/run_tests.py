#!/usr/bin/env python

"""Coverage of the `run.py` CLI helpers added for verbose-mode persistence —
the `database`-block override resolution and the interactive `vi` notes flow.
See `tests/spec-files/RUN_TEST_SPEC.md`. The full `run()` invocation and the
DB-touching `_persist_debuglog` are covered elsewhere (manual CLI runs;
`dashboard_tests.py`'s MySQL-gated wiring tests)."""

import json
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


if __name__ == '__main__':
    unittest.main()
