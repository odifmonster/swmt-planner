#!/usr/bin/env python

import unittest
from datetime import date

from swmtplanner.product import BeamSet, Greige
from swmtplanner.materials import GreigeRoll, NEW_ROLL_PLACEHOLDER


def _make_greige(
    sku: str = 'STYLE-A',
    port_load_tgt: float = 50.0,
    standard_size: int = 2,
) -> Greige:
    # Default port_load_tgt=50, standard_size=2 → size buckets are computed
    # against 2 * port_load_tgt = 100, matching the previous roll_tgt_wt=100
    # reference so existing qty values still land in the expected buckets.
    top = BeamSet('150D MICRO 50X4', 0.0)
    bottom = BeamSet('100D POLY 60X8 S/L', 0.0)
    return Greige(
        sku, 0.0, 'fam', 28, top, 0.4, bottom, 0.6,
        port_load_tgt, standard_size, {},
    )


class GreigeRollInstantiationTests(unittest.TestCase):
    """Covers section 1.1 of COVERAGE.md."""

    def setUp(self):
        self.greige = _make_greige()

    def test_construction_avail_date_none(self):
        """1.1.1: attribute pass-through with avail_date=None"""
        r = GreigeRoll('FS001', self.greige, 50.0, None, 'FS', 'V1', 'M1')
        self.assertEqual(r.id, 'FS001')
        self.assertIs(r.product, self.greige)
        self.assertEqual(r.qty, 50.0)
        self.assertIsNone(r.avail_date)
        self.assertEqual(r.plant, 'FS')
        self.assertEqual(r.item_variant, 'V1')
        self.assertEqual(r.yarn_merge, 'M1')

    def test_construction_avail_date_future(self):
        """1.1.1: attribute pass-through with a future avail_date"""
        d = date(2026, 7, 1)
        r = GreigeRoll('WF002', self.greige, 50.0, d, 'WF', 'V2', 'M2')
        self.assertEqual(r.id, 'WF002')
        self.assertIs(r.product, self.greige)
        self.assertEqual(r.qty, 50.0)
        self.assertEqual(r.avail_date, d)
        self.assertEqual(r.plant, 'WF')
        self.assertEqual(r.item_variant, 'V2')
        self.assertEqual(r.yarn_merge, 'M2')

    def test_size_partial(self):
        """1.1.2: qty=30 / tgt=100 -> 'partial'"""
        r = GreigeRoll('R', self.greige, 30.0, None, 'FS', '', '')
        self.assertEqual(r.size, 'partial')

    def test_size_half(self):
        """1.1.2: qty=50 / tgt=100 -> 'half'"""
        r = GreigeRoll('R', self.greige, 50.0, None, 'FS', '', '')
        self.assertEqual(r.size, 'half')

    def test_size_small(self):
        """1.1.2: qty=80 / tgt=100 -> 'small'"""
        r = GreigeRoll('R', self.greige, 80.0, None, 'FS', '', '')
        self.assertEqual(r.size, 'small')

    def test_size_full(self):
        """1.1.2: qty=100 / tgt=100 -> 'full'"""
        r = GreigeRoll('R', self.greige, 100.0, None, 'FS', '', '')
        self.assertEqual(r.size, 'full')

    def test_size_large(self):
        """1.1.2: qty=120 / tgt=100 -> 'large'"""
        r = GreigeRoll('R', self.greige, 120.0, None, 'FS', '', '')
        self.assertEqual(r.size, 'large')

    def test_size_boundary_partial_half(self):
        """1.1.3: 47.99 -> 'partial', 48 -> 'half'"""
        self.assertEqual(
            GreigeRoll('R', self.greige, 47.99, None, 'FS', '', '').size,
            'partial',
        )
        self.assertEqual(
            GreigeRoll('R', self.greige, 48.0, None, 'FS', '', '').size,
            'half',
        )

    def test_size_boundary_half_small(self):
        """1.1.3: 51.99 -> 'half', 52 -> 'small'"""
        self.assertEqual(
            GreigeRoll('R', self.greige, 51.99, None, 'FS', '', '').size,
            'half',
        )
        self.assertEqual(
            GreigeRoll('R', self.greige, 52.0, None, 'FS', '', '').size,
            'small',
        )

    def test_size_boundary_small_full(self):
        """1.1.3: 97.99 -> 'small', 98 -> 'full'"""
        self.assertEqual(
            GreigeRoll('R', self.greige, 97.99, None, 'FS', '', '').size,
            'small',
        )
        self.assertEqual(
            GreigeRoll('R', self.greige, 98.0, None, 'FS', '', '').size,
            'full',
        )

    def test_size_boundary_full_large(self):
        """1.1.3: 102 -> 'full', 102.01 -> 'large'"""
        self.assertEqual(
            GreigeRoll('R', self.greige, 102.0, None, 'FS', '', '').size,
            'full',
        )
        self.assertEqual(
            GreigeRoll('R', self.greige, 102.01, None, 'FS', '', '').size,
            'large',
        )


class SplitTests(unittest.TestCase):
    """Covers section 1.2 of COVERAGE.md."""

    def setUp(self):
        self.greige = _make_greige()

    def _roll(self, qty: float, id_: str = 'FS001') -> GreigeRoll:
        return GreigeRoll(id_, self.greige, qty, None, 'FS', 'V1', 'M1')

    def test_split_weights_under_qty_raises(self):
        """1.2.1: lbs1 + lbs2 < self.qty raises ValueError"""
        with self.assertRaises(ValueError):
            self._roll(100.0).split(40.0, 50.0)

    def test_split_weights_over_qty_raises(self):
        """1.2.1: lbs1 + lbs2 > self.qty raises ValueError"""
        with self.assertRaises(ValueError):
            self._roll(100.0).split(60.0, 50.0)

    def test_split_id_suffix_scheme(self):
        """1.2.2: new rolls' IDs are the parent's ID suffixed with 'A' and 'B'"""
        a, b = self._roll(100.0, id_='FS001').split(40.0, 60.0)
        self.assertEqual(a.id, 'FS001A')
        self.assertEqual(b.id, 'FS001B')
        self.assertEqual(a.qty, 40.0)
        self.assertEqual(b.qty, 60.0)

    def test_split_half_into_two_partials(self):
        """1.2.3: half (50) -> 25 + 25 produces two 'partial' rolls"""
        a, b = self._roll(50.0).split(25.0, 25.0)
        self.assertEqual(a.size, 'partial')
        self.assertEqual(b.size, 'partial')

    def test_split_small_into_two_partials(self):
        """1.2.3: small (70) -> 35 + 35 produces two 'partial' rolls"""
        a, b = self._roll(70.0).split(35.0, 35.0)
        self.assertEqual(a.size, 'partial')
        self.assertEqual(b.size, 'partial')

    def test_split_small_into_half_and_partial(self):
        """1.2.3: small (90) -> 50 + 40 produces 'half' and 'partial'"""
        a, b = self._roll(90.0).split(50.0, 40.0)
        self.assertEqual(a.size, 'half')
        self.assertEqual(b.size, 'partial')

    def test_split_full_into_two_halves(self):
        """1.2.3: full (100) -> 50 + 50 produces two 'half' rolls"""
        a, b = self._roll(100.0).split(50.0, 50.0)
        self.assertEqual(a.size, 'half')
        self.assertEqual(b.size, 'half')

    def test_split_full_into_partial_and_small(self):
        """1.2.3: full (100) -> 30 + 70 produces 'partial' and 'small'"""
        a, b = self._roll(100.0).split(30.0, 70.0)
        self.assertEqual(a.size, 'partial')
        self.assertEqual(b.size, 'small')

    def test_split_large_into_two_smalls(self):
        """1.2.3: large (150) -> 75 + 75 produces two 'small' rolls"""
        a, b = self._roll(150.0).split(75.0, 75.0)
        self.assertEqual(a.size, 'small')
        self.assertEqual(b.size, 'small')

    def test_split_large_into_half_and_small(self):
        """1.2.3: large (140) -> 50 + 90 produces 'half' and 'small'"""
        a, b = self._roll(140.0).split(50.0, 90.0)
        self.assertEqual(a.size, 'half')
        self.assertEqual(b.size, 'small')

    def test_split_large_into_partial_and_full(self):
        """1.2.3: large (130) -> 30 + 100 produces 'partial' and 'full'"""
        a, b = self._roll(130.0).split(30.0, 100.0)
        self.assertEqual(a.size, 'partial')
        self.assertEqual(b.size, 'full')


class CombineTests(unittest.TestCase):
    """Covers section 1.3 of COVERAGE.md."""

    def setUp(self):
        self.greige_a = _make_greige('STYLE-A')
        self.greige_b = _make_greige('STYLE-B')

    def _roll(
        self,
        qty: float,
        id_: str,
        plant: str = 'FS',
        variant: str = 'V',
        merge: str = 'M',
        greige: Greige | None = None,
    ) -> GreigeRoll:
        return GreigeRoll(
            id_, greige or self.greige_a, qty, None, plant, variant, merge,
        )

    def test_different_plants_raises(self):
        """1.3.1: combining rolls from different plants raises ValueError"""
        r1 = self._roll(30.0, 'FS001', plant='FS')
        r2 = self._roll(30.0, 'WF001', plant='WF')
        with self.assertRaises(ValueError):
            r1.combine(r2)

    def test_different_items_raises(self):
        """1.3.1: combining rolls of different greige items raises ValueError"""
        r1 = self._roll(30.0, 'FS001', greige=self.greige_a)
        r2 = self._roll(30.0, 'FS002', greige=self.greige_b)
        with self.assertRaises(ValueError):
            r1.combine(r2)

    def test_combined_id_always_concatenated(self):
        """1.3.2: id is always the concatenation of the two source ids"""
        r1 = self._roll(30.0, 'FS001', variant='V1', merge='M1')
        r2 = self._roll(30.0, 'FS002', variant='V2', merge='M2')
        self.assertEqual(r1.combine(r2).id, 'FS001FS002')

    def test_combined_variant_and_merge_match(self):
        """1.3.2: matching variant and matching merge keep single values"""
        r1 = self._roll(20.0, 'FS001', variant='V1', merge='M1')
        r2 = self._roll(20.0, 'FS002', variant='V1', merge='M1')
        c = r1.combine(r2)
        self.assertEqual(c.item_variant, 'V1')
        self.assertEqual(c.yarn_merge, 'M1')

    def test_combined_variant_and_merge_differ(self):
        """1.3.2: differing variant and differing merge both get concatenated"""
        r1 = self._roll(20.0, 'FS001', variant='V1', merge='M1')
        r2 = self._roll(20.0, 'FS002', variant='V2', merge='M2')
        c = r1.combine(r2)
        self.assertEqual(c.item_variant, 'V1V2')
        self.assertEqual(c.yarn_merge, 'M1M2')

    def test_combine_partials_to_half(self):
        """1.3.3: partial (30) + partial (20) = half (50)"""
        r1 = self._roll(30.0, 'F1')
        r2 = self._roll(20.0, 'F2')
        self.assertEqual(r1.combine(r2).size, 'half')

    def test_combine_partials_to_small(self):
        """1.3.3: partial (35) + partial (35) = small (70)"""
        r1 = self._roll(35.0, 'F1')
        r2 = self._roll(35.0, 'F2')
        self.assertEqual(r1.combine(r2).size, 'small')

    def test_combine_partial_and_half_to_small(self):
        """1.3.3: partial (30) + half (50) = small (80)"""
        r1 = self._roll(30.0, 'F1')
        r2 = self._roll(50.0, 'F2')
        self.assertEqual(r1.combine(r2).size, 'small')

    def test_combine_halves_to_full(self):
        """1.3.3: half (50) + half (50) = full (100)"""
        r1 = self._roll(50.0, 'F1')
        r2 = self._roll(50.0, 'F2')
        self.assertEqual(r1.combine(r2).size, 'full')

    def test_combine_half_and_small_to_large(self):
        """1.3.3: half (50) + small (80) = large (130)"""
        r1 = self._roll(50.0, 'F1')
        r2 = self._roll(80.0, 'F2')
        self.assertEqual(r1.combine(r2).size, 'large')

    def test_combine_small_and_partial_to_full(self):
        """1.3.3: small (70) + partial (30) = full (100)"""
        r1 = self._roll(70.0, 'F1')
        r2 = self._roll(30.0, 'F2')
        self.assertEqual(r1.combine(r2).size, 'full')

    def test_combine_smalls_to_large(self):
        """1.3.3: small (70) + small (80) = large (150)"""
        r1 = self._roll(70.0, 'F1')
        r2 = self._roll(80.0, 'F2')
        self.assertEqual(r1.combine(r2).size, 'large')


class NewArrivalTests(unittest.TestCase):
    """Covers section 1.4 of COVERAGE.md."""

    def setUp(self):
        self.greige = _make_greige()  # defaults give 2 * port_load_tgt = 100

    def test_attributes_populated(self):
        """1.4.1: attributes are populated correctly"""
        d = date(2026, 7, 1)
        r = GreigeRoll.new_arrival('FS', self.greige, d)
        self.assertIs(r.product, self.greige)
        self.assertEqual(r.qty, 100.0)
        self.assertEqual(r.size, 'full')
        self.assertEqual(r.avail_date, d)
        self.assertEqual(r.plant, 'FS')
        self.assertEqual(r.item_variant, NEW_ROLL_PLACEHOLDER)
        self.assertEqual(r.yarn_merge, NEW_ROLL_PLACEHOLDER)

    def test_id_starts_with_plant_prefix(self):
        """1.4.2: id begins with the plant prefix"""
        d = date(2026, 7, 1)
        fs_roll = GreigeRoll.new_arrival('FS', self.greige, d)
        wf_roll = GreigeRoll.new_arrival('WF', self.greige, d)
        self.assertTrue(fs_roll.id.startswith('FS'))
        self.assertTrue(wf_roll.id.startswith('WF'))

    def test_successive_calls_return_distinct_ids(self):
        """1.4.3: two consecutive calls with the same plant return different ids"""
        d = date(2026, 7, 1)
        r1 = GreigeRoll.new_arrival('FS', self.greige, d)
        r2 = GreigeRoll.new_arrival('FS', self.greige, d)
        self.assertNotEqual(r1.id, r2.id)

    def test_counters_independent_across_plants(self):
        """1.4.4: FS and WF counters do not collide"""
        d = date(2026, 7, 1)
        fs_ids = {GreigeRoll.new_arrival('FS', self.greige, d).id for _ in range(3)}
        wf_ids = {GreigeRoll.new_arrival('WF', self.greige, d).id for _ in range(3)}
        # No id appears in both sets — distinct prefixes guarantee disjoint sets
        self.assertEqual(fs_ids & wf_ids, set())
        # Each plant produced unique ids
        self.assertEqual(len(fs_ids), 3)
        self.assertEqual(len(wf_ids), 3)


if __name__ == '__main__':
    unittest.main()
