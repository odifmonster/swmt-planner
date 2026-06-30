#!/usr/bin/env python

import unittest

from swmtplanner.core.product.greige import (
    BeamConfig, Greige,
    load_variant_translation, load_alt_translation,
    variant_to_master, alt_greige_to_greige,
)


def _greige(id: str, alt_names: list[str]) -> Greige:
    bc = BeamConfig(beamset='BS', pct=1.0)
    return Greige(id=id, tgt_wt=100.0, safety=200.0, pattern='A',
                  top=bc, bottom=bc, alt_names=alt_names)


class TestGreigeConstruction(unittest.TestCase):

    def test_beamconfig_construction(self):
        """1.1.1 — BeamConfig fields are stored correctly."""
        bc = BeamConfig(beamset='BS-TOP', pct=0.6)
        self.assertEqual(bc.beamset, 'BS-TOP')
        self.assertEqual(bc.pct, 0.6)

    def test_greige_construction(self):
        """1.1.2 — Greige attributes are exposed as read-only properties;
        alt_names (passed as a list) is stored as a tuple."""
        top = BeamConfig(beamset='BS-TOP', pct=0.6)
        bottom = BeamConfig(beamset='BS-BOT', pct=0.4)
        g = Greige(id='G100', tgt_wt=120.0, safety=500.0, pattern='A',
                   top=top, bottom=bottom, alt_names=['G100-ALT', 'G100-OLD'])
        self.assertEqual(g.id, 'G100')
        self.assertEqual(g.tgt_wt, 120.0)
        self.assertEqual(g.safety, 500.0)
        self.assertEqual(g.pattern, 'A')
        self.assertEqual(g.top, top)
        self.assertEqual(g.bottom, bottom)
        self.assertEqual(g.alt_names, ('G100-ALT', 'G100-OLD'))
        self.assertIsInstance(g.alt_names, tuple)


class TestVariantTranslation(unittest.TestCase):

    def test_load(self):
        """1.2.1 — load_variant_translation loads the contents of the passed
        string into the table."""
        load_variant_translation(
            '[{"variant": "V1", "master": "M1"}, '
            '{"variant": "V2", "master": "M2"}]')
        self.assertEqual(variant_to_master('V1'), 'M1')
        self.assertEqual(variant_to_master('V2'), 'M2')

    def test_reload_replaces(self):
        """1.2.2 — calling load_variant_translation again replaces the table."""
        load_variant_translation('[{"variant": "V1", "master": "M1"}]')
        load_variant_translation('[{"variant": "V3", "master": "M3"}]')
        self.assertIsNone(variant_to_master('V1'))
        self.assertEqual(variant_to_master('V3'), 'M3')

    def test_to_master(self):
        """1.2.3 — variant_to_master fetches the correct master."""
        load_variant_translation(
            '[{"variant": "V1", "master": "M1"}, '
            '{"variant": "V2", "master": "M2"}]')
        self.assertEqual(variant_to_master('V2'), 'M2')

    def test_to_master_missing(self):
        """1.2.4 — variant_to_master returns None on an unknown variant."""
        load_variant_translation('[{"variant": "V1", "master": "M1"}]')
        self.assertIsNone(variant_to_master('NOPE'))


class TestAltTranslation(unittest.TestCase):

    def test_load_one_to_one(self):
        """1.2.5 — load_alt_translation works on a one-to-one table."""
        g1 = _greige('G1', ['ALT-1'])
        g2 = _greige('G2', ['ALT-2'])
        load_alt_translation([g1, g2])
        self.assertEqual(alt_greige_to_greige('ALT-1'), g1)
        self.assertEqual(alt_greige_to_greige('ALT-2'), g2)

    def test_load_many_to_one(self):
        """1.2.6 — load_alt_translation works on a many-to-one table."""
        g = _greige('G1', ['ALT-A', 'ALT-B', 'ALT-C'])
        load_alt_translation([g])
        self.assertEqual(alt_greige_to_greige('ALT-A'), g)
        self.assertEqual(alt_greige_to_greige('ALT-B'), g)
        self.assertEqual(alt_greige_to_greige('ALT-C'), g)

    def test_to_greige(self):
        """1.2.7 — alt_greige_to_greige returns the expected Greige object."""
        g = _greige('G1', ['ALT-A'])
        load_alt_translation([g])
        self.assertIs(alt_greige_to_greige('ALT-A'), g)

    def test_to_greige_unknown(self):
        """1.2.8 — alt_greige_to_greige returns None on an unknown id."""
        g = _greige('G1', ['ALT-A'])
        load_alt_translation([g])
        self.assertIsNone(alt_greige_to_greige('NOPE'))


if __name__ == '__main__':
    unittest.main()
