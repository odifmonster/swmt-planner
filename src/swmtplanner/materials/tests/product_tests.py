#!/usr/bin/env python

import unittest

from swmtplanner.materials.product import BeamSet, Greige, Fabric


class BeamSetTests(unittest.TestCase):
    """Covers section 1.1 of COVERAGE.md."""

    def test_construction(self):
        """1.1.1: construction works as expected"""
        bs = BeamSet('150D MICRO 50X4', 100.0)
        self.assertEqual(bs.id, '150D MICRO 50X4')
        self.assertEqual(bs.safety_tgt, 100.0)
        self.assertEqual(bs.denier, 150)
        self.assertEqual(bs.yarn_desc, 'MICRO')
        self.assertEqual(bs.end_count, 50)
        self.assertEqual(bs.beam_count, 4)
        self.assertFalse(bs.is_split)

    def test_sku_parsing_no_split_lease(self):
        """1.1.2: basic form (no S/L) sets is_split to False"""
        bs = BeamSet('150D MICRO 50X4', 0.0)
        self.assertFalse(bs.is_split)
        self.assertEqual(bs.denier, 150)
        self.assertEqual(bs.yarn_desc, 'MICRO')
        self.assertEqual(bs.end_count, 50)
        self.assertEqual(bs.beam_count, 4)

    def test_sku_parsing_with_split_lease(self):
        """1.1.2: trailing ' S/L' sets is_split to True without affecting other fields"""
        bs = BeamSet('100D POLY 60X8 S/L', 0.0)
        self.assertTrue(bs.is_split)
        self.assertEqual(bs.denier, 100)
        self.assertEqual(bs.yarn_desc, 'POLY')
        self.assertEqual(bs.end_count, 60)
        self.assertEqual(bs.beam_count, 8)

    def test_sku_parsing_multi_word_yarn_desc(self):
        """1.1.2: multi-word yarn description is captured correctly"""
        bs = BeamSet('200D FOO BAR 75X6', 0.0)
        self.assertEqual(bs.denier, 200)
        self.assertEqual(bs.yarn_desc, 'FOO BAR')
        self.assertEqual(bs.end_count, 75)
        self.assertEqual(bs.beam_count, 6)
        self.assertFalse(bs.is_split)

    def test_invalid_sku_raises(self):
        """1.1.3: invalid SKU raises ValueError"""
        with self.assertRaises(ValueError):
            BeamSet('not a valid sku', 0.0)


def _make_beamsets():
    return (
        BeamSet('150D MICRO 50X4', 0.0),
        BeamSet('100D POLY 60X8 S/L', 0.0),
    )


class GreigeTests(unittest.TestCase):
    """Covers section 1.2 of COVERAGE.md."""

    def setUp(self):
        self.top, self.bottom = _make_beamsets()

    def test_construction(self):
        """1.2.1: construction works as expected"""
        g = Greige(
            'STYLE-A', 25.0,
            family='fam', gauge=28,
            top_bar=self.top, top_bar_pct=0.4,
            bottom_bar=self.bottom, bottom_bar_pct=0.6,
            port_load_tgt=60.0,
            standard_size=2,
            machine_rates={'KM1': 10.0},
        )
        self.assertEqual(g.id, 'STYLE-A')
        self.assertEqual(g.safety_tgt, 25.0)
        self.assertEqual(g.family, 'fam')
        self.assertEqual(g.gauge, 28)
        self.assertIs(g.top_bar, self.top)
        self.assertEqual(g.top_bar_pct, 0.4)
        self.assertIs(g.bottom_bar, self.bottom)
        self.assertEqual(g.bottom_bar_pct, 0.6)
        self.assertEqual(g.port_load_tgt, 60.0)
        self.assertEqual(g.standard_size, 2)

    def test_can_run_on_machine(self):
        """1.2.2: can_run_on_machine reflects the machine_rates mapping"""
        g = Greige(
            'STYLE-A', 0.0, 'fam', 28, self.top, 0.4, self.bottom, 0.6,
            50.0, 2, {'KM1': 10.0, 'KM2': 8.5},
        )
        self.assertTrue(g.can_run_on_machine('KM1'))
        self.assertTrue(g.can_run_on_machine('KM2'))
        self.assertFalse(g.can_run_on_machine('KM3'))

    def test_rate_on_machine(self):
        """1.2.3: rate_on_machine returns the configured rate"""
        g = Greige(
            'STYLE-A', 0.0, 'fam', 28, self.top, 0.4, self.bottom, 0.6,
            50.0, 2, {'KM1': 10.0, 'KM2': 8.5},
        )
        self.assertEqual(g.rate_on_machine('KM1'), 10.0)
        self.assertEqual(g.rate_on_machine('KM2'), 8.5)

    def test_machine_rates_copied(self):
        """1.2.4: machine_rates is copied at construction"""
        rates = {'KM1': 10.0}
        g = Greige(
            'STYLE-A', 0.0, 'fam', 28, self.top, 0.4, self.bottom, 0.6,
            50.0, 2, rates,
        )
        rates['KM2'] = 5.0
        self.assertFalse(g.can_run_on_machine('KM2'))


class FabricTests(unittest.TestCase):
    """Covers section 1.3 of COVERAGE.md."""

    def test_construction(self):
        """1.3.1: construction works as expected with a basic SKU"""
        f = Fabric(
            'FF 1234-12345-58.0', 25.0,
            greige_style='STYLE-A', yld=1.8, color_shade=2,
            omits_port=False,
            jets=['JET 1'],
        )
        self.assertEqual(f.id, 'FF 1234-12345-58.0')
        self.assertEqual(f.safety_tgt, 25.0)
        self.assertEqual(f.style, '1234')
        self.assertEqual(f.dye_formula, '12345')
        self.assertEqual(f.width, 58.0)
        self.assertEqual(f.greige_style, 'STYLE-A')
        self.assertEqual(f.yld, 1.8)
        self.assertEqual(f.color_shade, 2)
        self.assertFalse(f.omits_port)
        self.assertEqual(f.jets, frozenset({'JET 1'}))

    def test_omits_port_attribute(self):
        """1.3.1: omits_port is stored and returned as supplied"""
        f = Fabric(
            'FF 1234-12345-58.0', 0.0, 's', 1.0, 0,
            omits_port=True, jets=['JET 1'],
        )
        self.assertTrue(f.omits_port)

    def test_sku_parsing_single_token_style(self):
        """1.3.2: single-token style"""
        f = Fabric('FF 1234-12345-58.0', 0.0, 's', 1.0, 0, False, [])
        self.assertEqual(f.style, '1234')
        self.assertEqual(f.dye_formula, '12345')
        self.assertEqual(f.width, 58.0)

    def test_sku_parsing_style_with_one_dash(self):
        """1.3.2: style containing one dash"""
        f = Fabric('FF 1234-AB-12345-58.0', 0.0, 's', 1.0, 0, False, [])
        self.assertEqual(f.style, '1234-AB')
        self.assertEqual(f.dye_formula, '12345')
        self.assertEqual(f.width, 58.0)

    def test_sku_parsing_style_with_multiple_dashes(self):
        """1.3.2: style containing multiple dashes"""
        f = Fabric('FF A-B-C-99999-57', 0.0, 's', 1.0, 0, False, [])
        self.assertEqual(f.style, 'A-B-C')
        self.assertEqual(f.dye_formula, '99999')
        self.assertEqual(f.width, 57.0)

    def test_invalid_sku_missing_prefix(self):
        """1.3.3: malformed prefix raises ValueError"""
        with self.assertRaises(ValueError):
            Fabric('1234-12345-58.0', 0.0, 's', 1.0, 0, False, [])

    def test_invalid_sku_non_numeric_color(self):
        """1.3.3: non-numeric color field raises ValueError"""
        with self.assertRaises(ValueError):
            Fabric('FF 1234-NAVY-58.0', 0.0, 's', 1.0, 0, False, [])

    def test_invalid_sku_wrong_color_digit_count(self):
        """1.3.3: color field that is not exactly 5 digits raises ValueError"""
        with self.assertRaises(ValueError):
            Fabric('FF 1234-9999-58.0', 0.0, 's', 1.0, 0, False, [])

    def test_invalid_sku_missing_width(self):
        """1.3.3: missing width raises ValueError"""
        with self.assertRaises(ValueError):
            Fabric('FF 1234-12345', 0.0, 's', 1.0, 0, False, [])

    def test_can_run_on_jet(self):
        """1.3.4: can_run_on_jet reflects the jets set"""
        f = Fabric(
            'FF 1234-12345-58.0', 0.0, 's', 1.0, 0, False,
            jets=['JET 1', 'JET 2'],
        )
        self.assertTrue(f.can_run_on_jet('JET 1'))
        self.assertTrue(f.can_run_on_jet('JET 2'))
        self.assertFalse(f.can_run_on_jet('JET 3'))

    def test_jets_property_is_frozenset(self):
        """1.3.4: jets is exposed as a frozenset; duplicates in the input are collapsed"""
        f = Fabric(
            'FF 1234-12345-58.0', 0.0, 's', 1.0, 0, False,
            jets=['JET 1', 'JET 2', 'JET 2'],
        )
        self.assertEqual(f.jets, frozenset({'JET 1', 'JET 2'}))

    def test_jets_input_isolated(self):
        """1.3.5: mutating the input iterable after construction does not affect Fabric"""
        jets = ['JET 1']
        f = Fabric('FF 1234-12345-58.0', 0.0, 's', 1.0, 0, False, jets)
        jets.append('JET 2')
        self.assertFalse(f.can_run_on_jet('JET 2'))


if __name__ == '__main__':
    unittest.main()
