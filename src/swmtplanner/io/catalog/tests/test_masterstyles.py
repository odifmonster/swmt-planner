#!/usr/bin/env python

import json
import os
import tempfile
import unittest

from swmtplanner.io.catalog.masterstyles import (
    MASTER_STYLES_FILE, MASTER_STYLES, MASTER_STYLE_LOADER,
)

RECORDS = [
    {'master': 'AU7805', 'variant': 'AU7805-X', 'safety_tgt': 5000},
    {'master': 'AU2958G', 'variant': 'AU2958G-HA/2', 'safety_tgt': 0},
]
FNAME = 'greige-master-styles.json'


class TestMasterStyles(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.cfg = {'pa_supply': self.dir, 'inputs': self.dir, 'scheduling': self.dir}
        with open(os.path.join(self.dir, FNAME), 'w') as f:
            json.dump(RECORDS, f)

    def tearDown(self):
        self._tmp.cleanup()

    def test_master_styles_file(self):
        self.assertEqual(MASTER_STYLES_FILE.cfg_name, 'inputs')
        self.assertEqual(MASTER_STYLES_FILE.orient, 'records')
        self.assertIsNone(MASTER_STYLES_FILE.date_fmt)
        self.assertEqual(MASTER_STYLES_FILE.get_fpath(self.cfg),
                         os.path.join(self.dir, FNAME))

    def test_master_styles_table(self):
        self.assertEqual(MASTER_STYLES.name, 'master_styles')
        self.assertEqual(MASTER_STYLES.index.name, 'master')
        self.assertEqual([c.name for c in MASTER_STYLES.columns], ['variant'])

    def test_master_style_loader_constants(self):
        self.assertIs(MASTER_STYLE_LOADER.tbl, MASTER_STYLES)
        self.assertIs(MASTER_STYLE_LOADER.source, MASTER_STYLES_FILE)

    def test_master_styles_load(self):
        df = MASTER_STYLE_LOADER.load(self.cfg)
        self.assertEqual(len(df), 2)
        self.assertEqual(df.index.name, 'master')
        self.assertEqual(df.index.tolist(), ['AU7805', 'AU2958G'])
        self.assertEqual(list(df.columns), ['variant'])
        self.assertNotIn('safety_tgt', df.columns)

    def test_master_styles_values(self):
        df = MASTER_STYLE_LOADER.load(self.cfg)
        self.assertEqual(df.loc['AU2958G', 'variant'], 'AU2958G-HA/2')
        self.assertEqual(df['variant'].dtype, 'string')
        self.assertEqual(df.index.dtype, 'string')


if __name__ == '__main__':
    unittest.main()
