#!/usr/bin/env python

import json
import os
import tempfile
import unittest

from swmtplanner.io.catalog.machines import (
    KNIT_MACHINES_FILE, KNIT_MACHINES, KNIT_MACHINE_LOADER, NEW_MACHINES_ONLY,
)

MACHINES = {
    'N1': {'gauge': 28, 'is_new': True, 'width': 186, 'attrs': ['tall'], 'rpm': 2200,
           'notes': 'x'},
    'B4': {'gauge': 32, 'is_new': False, 'width': 144, 'attrs': [], 'rpm': 1500,
           'notes': ''},
    '12': {'gauge': 28, 'is_new': False, 'width': 168, 'attrs': ['tall', 'wide'],
           'rpm': 1800, 'notes': ''},
}
FNAME = 'knit-machine-master.json'
MACHINE_COLUMNS = ['gauge', 'width', 'is_new', 'rpm', 'attrs']


class TestMachines(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.cfg = {'pa_supply': self.dir, 'inputs': self.dir, 'scheduling': self.dir}
        with open(os.path.join(self.dir, FNAME), 'w') as f:
            json.dump(MACHINES, f)

    def tearDown(self):
        self._tmp.cleanup()

    def load(self):
        return KNIT_MACHINE_LOADER.load(self.cfg)

    def test_machines_file(self):
        self.assertEqual(KNIT_MACHINES_FILE.cfg_name, 'inputs')
        self.assertEqual(KNIT_MACHINES_FILE.orient, 'index')
        self.assertIsNone(KNIT_MACHINES_FILE.date_fmt)
        self.assertEqual(KNIT_MACHINES_FILE.get_fpath(self.cfg),
                         os.path.join(self.dir, FNAME))

    def test_machines_table(self):
        self.assertEqual(KNIT_MACHINES.name, 'knit_machines')
        self.assertEqual(KNIT_MACHINES.index.name, 'machine')
        self.assertEqual(KNIT_MACHINES.index.src_name, 'index')
        self.assertEqual([c.name for c in KNIT_MACHINES.columns], MACHINE_COLUMNS)

    def test_machine_loader_constants(self):
        self.assertIs(KNIT_MACHINE_LOADER.tbl, KNIT_MACHINES)
        self.assertIs(KNIT_MACHINE_LOADER.source, KNIT_MACHINES_FILE)

    def test_new_machines_only(self):
        self.assertIsInstance(NEW_MACHINES_ONLY, frozenset)
        self.assertEqual(NEW_MACHINES_ONLY, {'AU7992T2A'})

    def test_machines_load_shape(self):
        df = self.load()
        self.assertEqual(len(df), 3)
        self.assertEqual(df.index.name, 'machine')
        self.assertEqual(df.index.tolist(), ['N1', 'B4', '12'])
        self.assertEqual(list(df.columns), MACHINE_COLUMNS)
        self.assertNotIn('notes', df.columns)

    def test_machines_dtypes(self):
        df = self.load()
        for name in ('gauge', 'width', 'rpm'):
            with self.subTest(name=name):
                self.assertEqual(df[name].dtype, 'int64')
        self.assertEqual(df['is_new'].dtype, 'bool')
        self.assertEqual(df.index.dtype, 'string')

    def test_machines_values(self):
        row = self.load().loc['N1']
        self.assertEqual(row['gauge'], 28)
        self.assertEqual(row['width'], 186)
        self.assertTrue(row['is_new'])
        self.assertEqual(row['rpm'], 2200)

    def test_machines_attrs(self):
        self.assertEqual(self.load()['attrs'].tolist(), [('tall',), (), ('tall', 'wide')])


if __name__ == '__main__':
    unittest.main()
