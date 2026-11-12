#!/usr/bin/env python

import os
import shutil
import tempfile
import unittest
from datetime import date

import pandas as pd

from swmtplanner.core.products import Shade
from swmtplanner.io.catalog.xref import (
    XREF_FILE, FABRICS, SHADE_RATINGS, GREIGE_STYLES_SHEET, GREIGE_STYLES,
    GREIGE_STYLE_LOADER, XrefFabricLoader, FABRIC_LOADER,
)
from swmtplanner.io.loaders import CSVFile, ExcelTableLoader

JETS = [f'jet{i}' for i in range(1, 11)]
FABRIC_COLUMNS = ['item', 'greige', 'style', 'width', 'yld', 'formula', 'color',
                  'shade', 'active', *JETS, 'tanks']
XREF_SRC_COLUMNS = ['PLY 1 PART #', 'PA FIN ITEM', 'GREIGE ITEM', 'STYLE', 'WD', 'Yield',
                    'COLOR NUMBER', 'COLOR NAME', 'SHADE RATING', 'STATUS',
                    *(f'JET {i}' for i in range(1, 11)), 'TANKS', 'NOTES']
XREF_ROWS = [
    {'PLY 1 PART #': 239569, 'PA FIN ITEM': ' FF AEROKNIT D-40637-61 ',
     'GREIGE ITEM': 'AU3426H', 'STYLE': 'AEROKNIT D', 'WD': 61, 'Yield': 2.81,
     'COLOR NUMBER': 40637, 'COLOR NAME': 'TINTED GRAY ', 'SHADE RATING': 0,
     'STATUS': 'A', 'JET 1': 'X', 'JET 2': 'x', 'JET 3': ' X ', 'NOTES': 'note'},
    {'PLY 1 PART #': 242883, 'PA FIN ITEM': 'FF ANMUT-C-NA-40487-66',
     'GREIGE ITEM': 'ANMUT-C', 'WD': 66, 'Yield': 2.62, 'COLOR NUMBER': 40487,
     'SHADE RATING': 3, 'JET 10': 'X', 'TANKS': 'X'},
    {'PLY 1 PART #': '210189A', 'PA FIN ITEM': 'FF AURA30000-39064-63',
     'GREIGE ITEM': 'AU9999', 'COLOR NUMBER': 39064, 'SHADE RATING': 4, 'STATUS': 'I'},
    {},
    {},
    {'PLY 1 PART #': 229081, 'PA FIN ITEM': 'FF HANA--59', 'GREIGE ITEM': ' AU3426H ',
     'STATUS': ' i '},
]
XREF_RAW = pd.DataFrame(XREF_ROWS, columns=XREF_SRC_COLUMNS)
GREIGE_RAW = pd.DataFrame({
    'GreigeAlt': ['ANMUT-C', 'AU7805', ' AU3426H '],
    'GreigeAlt2': ['AU7805', 'AU7805', 'AU3426H '],
    'Target': [740, 340, 740],
    'Notes': ['a', 'b', 'c'],
})
WORKBOOK = 'PA Master Xref.xlsx'


def _write_workbook(path, xref=XREF_RAW):
    with pd.ExcelWriter(path) as w:
        xref.to_excel(w, sheet_name='Xref', index=False)
        GREIGE_RAW.to_excel(w, sheet_name='Greige Styles', index=False)
        pd.DataFrame({'unrelated': [1]}).to_excel(w, sheet_name='Other', index=False)


class _XrefFixture(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.cfg = {'pa_supply': self.dir, 'inputs': self.dir, 'scheduling': self.dir}
        _write_workbook(os.path.join(self.dir, WORKBOOK))

    def tearDown(self):
        self._tmp.cleanup()

    def fabrics(self):
        return FABRIC_LOADER.load(self.cfg)


class TestXrefConstants(_XrefFixture):

    def test_xref_file(self):
        self.assertEqual(XREF_FILE.cfg_name, 'pa_supply')
        self.assertEqual(XREF_FILE.sheet_name, 'Xref')
        self.assertIsNone(XREF_FILE.date_fmt)
        self.assertEqual(XREF_FILE.get_fpath(self.cfg), os.path.join(self.dir, WORKBOOK))

    def test_greige_styles_sheet(self):
        self.assertEqual(GREIGE_STYLES_SHEET.get_fpath(self.cfg),
                         XREF_FILE.get_fpath(self.cfg))
        self.assertEqual(GREIGE_STYLES_SHEET.sheet_name, 'Greige Styles')

    def test_fabrics_table(self):
        self.assertEqual(FABRICS.name, 'fabrics')
        self.assertEqual(FABRICS.index.name, 'part_no')
        self.assertEqual([c.name for c in FABRICS.columns], FABRIC_COLUMNS)

    def test_fabrics_jet_sources(self):
        by_name = {c.name: c for c in FABRICS.columns}
        for i in range(1, 11):
            with self.subTest(i=i):
                self.assertEqual(by_name[f'jet{i}'].src_name, f'JET {i}')

    def test_greige_styles_table(self):
        self.assertEqual(GREIGE_STYLES.name, 'greige_styles')
        self.assertEqual(GREIGE_STYLES.index.name, 'alias')
        self.assertEqual([c.name for c in GREIGE_STYLES.columns], ['master', 'std_wt'])

    def test_shade_ratings(self):
        self.assertEqual(SHADE_RATINGS, {
            0: Shade.LIGHT0, 1: Shade.LIGHT1, 2: Shade.MEDIUM,
            3: Shade.BLACK, 4: Shade.SD_BLACK,
        })

    def test_shade_ratings_cover_shades(self):
        self.assertEqual(set(SHADE_RATINGS.values()), set(Shade))
        self.assertEqual(len(SHADE_RATINGS), len(Shade))

    def test_loader_constants(self):
        self.assertIsInstance(GREIGE_STYLE_LOADER, ExcelTableLoader)
        self.assertIs(GREIGE_STYLE_LOADER.tbl, GREIGE_STYLES)
        self.assertIs(GREIGE_STYLE_LOADER.source, GREIGE_STYLES_SHEET)
        self.assertIsInstance(FABRIC_LOADER, XrefFabricLoader)
        self.assertIs(FABRIC_LOADER.tbl, FABRICS)
        self.assertIs(FABRIC_LOADER.source, XREF_FILE)
        self.assertIs(FABRIC_LOADER.aliases, GREIGE_STYLE_LOADER)


class TestGreigeStyleLoader(_XrefFixture):

    def test_greige_styles_load(self):
        df = GREIGE_STYLE_LOADER.load(self.cfg)
        self.assertEqual(len(df), 3)
        self.assertEqual(df.index.name, 'alias')
        self.assertEqual(list(df.columns), ['master', 'std_wt'])
        self.assertNotIn('Notes', df.columns)

    def test_greige_styles_stripped(self):
        df = GREIGE_STYLE_LOADER.load(self.cfg)
        self.assertEqual(df.index.tolist(), ['ANMUT-C', 'AU7805', 'AU3426H'])
        self.assertEqual(df['master'].tolist(), ['AU7805', 'AU7805', 'AU3426H'])

    def test_greige_styles_std_wt(self):
        df = GREIGE_STYLE_LOADER.load(self.cfg)
        self.assertEqual(df['std_wt'].dtype, 'float64')
        self.assertEqual(df.loc['AU7805', 'std_wt'], 340.0)
        self.assertEqual(df.loc['ANMUT-C', 'std_wt'], 740.0)


class TestFabricLoader(_XrefFixture):

    def test_fabric_loader_wrong_source(self):
        with self.assertRaises(TypeError):
            XrefFabricLoader(FABRICS, CSVFile('pa_supply', 'x', '.csv'), GREIGE_STYLE_LOADER)

    def test_fabrics_load_shape(self):
        df = self.fabrics()
        self.assertEqual(len(df), 6)
        self.assertEqual(df.index.name, 'part_no')
        self.assertEqual(len(df.columns), 20)
        self.assertEqual(list(df.columns), FABRIC_COLUMNS)
        self.assertNotIn('NOTES', df.columns)

    def test_fabrics_part_numbers(self):
        self.assertEqual(self.fabrics().index.tolist(),
                         ['239569', '242883', '210189A', '', '', '229081'])

    def test_fabrics_text_stripped(self):
        row = self.fabrics().loc['239569']
        self.assertEqual(row['item'], 'FF AEROKNIT D-40637-61')
        self.assertEqual(row['color'], 'TINTED GRAY')
        self.assertEqual(row['style'], 'AEROKNIT D')

    def test_fabrics_dtypes(self):
        df = self.fabrics()
        for name in ('item', 'greige', 'style', 'color'):
            with self.subTest(name=name):
                self.assertEqual(df[name].dtype, 'string')
        for name in ('width', 'yld'):
            with self.subTest(name=name):
                self.assertEqual(df[name].dtype, 'float64')
        for name in ('formula', 'shade'):
            with self.subTest(name=name):
                self.assertEqual(df[name].dtype, 'Int64')
        for name in ('active', *JETS, 'tanks'):
            with self.subTest(name=name):
                self.assertEqual(df[name].dtype, 'bool')

    def test_fabrics_numbers(self):
        df = self.fabrics()
        self.assertEqual(df.loc[['239569', '242883'], 'width'].tolist(), [61.0, 66.0])
        self.assertEqual(df.loc[['239569', '242883'], 'yld'].tolist(), [2.81, 2.62])
        self.assertEqual(df.loc[['239569', '242883'], 'formula'].tolist(), [40637, 40487])
        self.assertEqual(df.loc[['239569', '242883'], 'shade'].tolist(), [0, 3])

    def test_fabrics_active(self):
        self.assertEqual(self.fabrics()['active'].tolist(),
                         [True, True, False, True, True, False])

    def test_fabrics_jets(self):
        row = self.fabrics().loc['239569']
        for name in ('jet1', 'jet2', 'jet3'):
            with self.subTest(name=name):
                self.assertTrue(row[name])
        for name in (*JETS[3:], 'tanks'):
            with self.subTest(name=name):
                self.assertFalse(row[name])

    def test_fabrics_tanks(self):
        row = self.fabrics().loc['242883']
        self.assertTrue(row['jet10'])
        self.assertTrue(row['tanks'])
        for name in JETS[:9]:
            with self.subTest(name=name):
                self.assertFalse(row[name])

    def test_fabrics_blank_row(self):
        blank = self.fabrics().loc['']
        self.assertEqual(len(blank), 2)
        for name in ('item', 'greige', 'style', 'color'):
            with self.subTest(name=name):
                self.assertEqual(blank[name].tolist(), ['', ''])
        for name in ('width', 'yld', 'formula', 'shade'):
            with self.subTest(name=name):
                self.assertTrue(blank[name].isna().all())
        self.assertEqual(blank['active'].tolist(), [True, True])
        for name in (*JETS, 'tanks'):
            with self.subTest(name=name):
                self.assertEqual(blank[name].tolist(), [False, False])

    def test_fabrics_greige_converted(self):
        self.assertEqual(self.fabrics().loc['242883', 'greige'], 'AU7805')

    def test_fabrics_greige_same_name(self):
        df = self.fabrics()
        self.assertEqual(df.loc['239569', 'greige'], 'AU3426H')
        self.assertEqual(df.loc['229081', 'greige'], 'AU3426H')

    def test_fabrics_greige_unknown(self):
        self.assertEqual(self.fabrics().loc['210189A', 'greige'], 'AU9999')

    def test_fabrics_greige_blank(self):
        self.assertEqual(self.fabrics().loc['', 'greige'].tolist(), ['', ''])

    def test_fabrics_greige_dtype(self):
        df = self.fabrics()
        self.assertEqual(df['greige'].dtype, 'string')
        self.assertFalse(df['greige'].isna().any())

    def test_fabrics_load_override(self):
        expected = self.fabrics()
        shutil.copy(os.path.join(self.dir, WORKBOOK), os.path.join(self.dir, 'copy.xlsx'))
        # with the default workbook gone, both tabs must come from the override
        os.remove(os.path.join(self.dir, WORKBOOK))
        pd.testing.assert_frame_equal(
            FABRIC_LOADER.load(self.cfg, override_name='copy.xlsx'), expected)

    def test_fabrics_load_ignores_date(self):
        pd.testing.assert_frame_equal(FABRIC_LOADER.load(self.cfg, date(2000, 1, 1)),
                                      self.fabrics())

    def test_fabrics_missing_column(self):
        _write_workbook(os.path.join(self.dir, 'no_tanks.xlsx'),
                        XREF_RAW.drop(columns='TANKS'))
        with self.assertRaises(KeyError) as ctx:
            FABRIC_LOADER.load(self.cfg, override_name='no_tanks.xlsx')
        self.assertIn('fabrics', str(ctx.exception))
        self.assertIn('TANKS', str(ctx.exception))

    def test_fabrics_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            FABRIC_LOADER.load({'pa_supply': os.path.join(self.dir, 'nowhere')})


if __name__ == '__main__':
    unittest.main()
