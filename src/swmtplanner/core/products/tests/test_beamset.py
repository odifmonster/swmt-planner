#!/usr/bin/env python

import unittest
from dataclasses import FrozenInstanceError

from swmtplanner.core.products import YarnAttrs, Yarn, Merge, BeamSetDesc

ATTRS_NONE = YarnAttrs(False, False, False)
ATTRS_TX = YarnAttrs(True, False, False)
YARN_75SD = Yarn(75, 'polyester', 'white', 'semidull', ATTRS_TX)
YARN_75D = Yarn(75, 'polyester', 'white', 'dull', ATTRS_TX)
YARN_40N = Yarn(40, 'nylon', 'white', 'semidull', ATTRS_NONE)
BS_1172 = BeamSetDesc(YARN_75SD, 4, 1172)


class TestYarnAttrs(unittest.TestCase):

    def test_attrs_init(self):
        a = YarnAttrs(True, False, True)
        self.assertIs(a.textured, True)
        self.assertIs(a.cationic, False)
        self.assertIs(a.recycled, True)

    def test_attrs_int_none(self):
        self.assertEqual(int(YarnAttrs(False, False, False)), 0)

    def test_attrs_int_recycled(self):
        self.assertEqual(int(YarnAttrs(False, False, True)), 1)

    def test_attrs_int_cationic(self):
        self.assertEqual(int(YarnAttrs(False, True, False)), 2)

    def test_attrs_int_textured(self):
        self.assertEqual(int(YarnAttrs(True, False, False)), 4)

    def test_attrs_int_tx_recycled(self):
        self.assertEqual(int(YarnAttrs(True, False, True)), 5)

    def test_attrs_int_all(self):
        self.assertEqual(int(YarnAttrs(True, True, True)), 7)

    def test_attrs_from_int_zero(self):
        self.assertEqual(YarnAttrs.from_int(0), YarnAttrs(False, False, False))

    def test_attrs_from_int_four(self):
        self.assertEqual(YarnAttrs.from_int(4), YarnAttrs(True, False, False))

    def test_attrs_from_int_five(self):
        self.assertEqual(YarnAttrs.from_int(5), YarnAttrs(True, False, True))

    def test_attrs_from_int_seven(self):
        self.assertEqual(YarnAttrs.from_int(7), YarnAttrs(True, True, True))

    def test_attrs_round_trip(self):
        for c in range(8):
            with self.subTest(code=c):
                self.assertEqual(int(YarnAttrs.from_int(c)), c)

    def test_attrs_from_int_negative(self):
        with self.assertRaises(ValueError):
            YarnAttrs.from_int(-1)

    def test_attrs_from_int_too_large(self):
        with self.assertRaises(ValueError):
            YarnAttrs.from_int(8)

    def test_attrs_equality(self):
        self.assertEqual(YarnAttrs(True, False, False), YarnAttrs.from_int(4))
        self.assertNotEqual(YarnAttrs(True, False, False), YarnAttrs(False, False, False))

    def test_attrs_frozen(self):
        a = YarnAttrs(True, False, False)
        with self.assertRaises(FrozenInstanceError):
            a.textured = False


class TestYarn(unittest.TestCase):

    def test_yarn_init(self):
        self.assertEqual(YARN_75SD.denier, 75)
        self.assertEqual(YARN_75SD.material, 'polyester')
        self.assertEqual(YARN_75SD.color, 'white')
        self.assertEqual(YARN_75SD.luster, 'semidull')
        self.assertEqual(YARN_75SD.attrs, ATTRS_TX)

    def test_yarn_id_semidull(self):
        self.assertEqual(YARN_75SD.id, '75PWTS04')

    def test_yarn_id_dull(self):
        self.assertEqual(Yarn(75, 'polyester', 'white', 'dull', ATTRS_TX).id, '75PWTD04')

    def test_yarn_id_nylon_black_bright(self):
        self.assertEqual(Yarn(40, 'nylon', 'black', 'bright', ATTRS_NONE).id, '40NBKB00')

    def test_yarn_id_greener_black(self):
        y = Yarn(75, 'polyester', 'greenerblack', 'semidull', YarnAttrs(True, False, True))
        self.assertEqual(y.id, '75PGBS05')

    def test_yarn_id_grey_recycled(self):
        y = Yarn(20, 'polyester', 'grey', 'semidull', YarnAttrs(False, False, True))
        self.assertEqual(y.id, '20PGYS01')

    def test_yarn_id_three_digit_denier(self):
        y = Yarn(150, 'lycra', 'white', 'clear', YarnAttrs(False, True, False))
        self.assertEqual(y.id, '150LWTC02')

    def test_yarn_equal_by_id(self):
        a = Yarn(75, 'polyester', 'white', 'semidull', ATTRS_TX)
        b = Yarn(75, 'polyester', 'white', 'semidull', YarnAttrs.from_int(4))
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertIsNot(a, b)

    def test_yarn_unequal_luster(self):
        self.assertNotEqual(YARN_75SD, Yarn(75, 'polyester', 'white', 'dull', ATTRS_TX))

    def test_yarn_unequal_attrs(self):
        self.assertNotEqual(YARN_75SD, Yarn(75, 'polyester', 'white', 'semidull', ATTRS_NONE))

    def test_yarn_unequal_denier(self):
        self.assertNotEqual(YARN_75SD, Yarn(70, 'polyester', 'white', 'semidull', ATTRS_TX))

    def test_yarn_hashable(self):
        s = {YARN_75SD, Yarn(75, 'polyester', 'white', 'semidull', ATTRS_TX)}
        self.assertEqual(len(s), 1)

    def test_yarn_invalid_material(self):
        with self.assertRaises(ValueError):
            Yarn(75, 'polypro', 'white', 'semidull', ATTRS_TX)

    def test_yarn_invalid_color(self):
        with self.assertRaises(ValueError):
            Yarn(75, 'polyester', 'navy', 'semidull', ATTRS_TX)

    def test_yarn_invalid_luster(self):
        with self.assertRaises(ValueError):
            Yarn(75, 'polyester', 'white', 'shiny', ATTRS_TX)

    def test_yarn_frozen(self):
        with self.assertRaises(FrozenInstanceError):
            YARN_75SD.denier = 70


class TestMerge(unittest.TestCase):

    def test_merge_init(self):
        m = Merge('R204B', YARN_75SD, 'Unifi')
        self.assertEqual(m.id, 'R204B')
        self.assertIs(m.yarn, YARN_75SD)
        self.assertEqual(m.vendor, 'Unifi')
        self.assertEqual(m, Merge('R204B', YARN_75SD, 'Other'))
        self.assertNotEqual(m, YARN_75SD)


class TestBeamSetDesc(unittest.TestCase):

    def test_bsd_init(self):
        self.assertIs(BS_1172.yarn, YARN_75SD)
        self.assertEqual(BS_1172.beam_count, 4)
        self.assertEqual(BS_1172.end_count, 1172)

    def test_bsd_id(self):
        self.assertEqual(BS_1172.id, '75PWTS04-1172-4')

    def test_bsd_id_other_yarn(self):
        self.assertEqual(BeamSetDesc(YARN_40N, 7, 370).id, '40NWTS00-370-7')

    def test_bsd_id_single_beam(self):
        self.assertEqual(BeamSetDesc(YARN_75D, 1, 586).id, '75PWTD04-586-1')

    def test_bsd_equal_by_id(self):
        other = BeamSetDesc(Yarn(75, 'polyester', 'white', 'semidull', YarnAttrs.from_int(4)), 4, 1172)
        self.assertEqual(BS_1172, other)
        self.assertEqual(hash(BS_1172), hash(other))

    def test_bsd_unequal_yarn(self):
        self.assertNotEqual(BS_1172, BeamSetDesc(YARN_75D, 4, 1172))

    def test_bsd_unequal_ends(self):
        self.assertNotEqual(BS_1172, BeamSetDesc(YARN_75SD, 4, 1173))

    def test_bsd_unequal_beams(self):
        self.assertNotEqual(BS_1172, BeamSetDesc(YARN_75SD, 3, 1172))

    def test_bsd_frozen(self):
        with self.assertRaises(FrozenInstanceError):
            BS_1172.end_count = 1

    # split

    def test_split_zero(self):
        with self.assertRaises(ValueError):
            BS_1172.split(0)

    def test_split_negative(self):
        with self.assertRaises(ValueError):
            BS_1172.split(-2)

    def test_split_uneven(self):
        with self.assertRaises(ValueError):
            BS_1172.split(3)

    def test_split_larger_than_ends(self):
        with self.assertRaises(ValueError):
            BeamSetDesc(YARN_75SD, 4, 2).split(4)

    def test_split_one(self):
        self.assertEqual(BS_1172.split(1), [BS_1172])

    def test_split_two(self):
        parts = BS_1172.split(2)
        self.assertEqual(len(parts), 2)
        for p in parts:
            self.assertEqual(p, BeamSetDesc(YARN_75SD, 4, 586))
            self.assertEqual(p.id, '75PWTS04-586-4')

    def test_split_four(self):
        parts = BS_1172.split(4)
        self.assertEqual(len(parts), 4)
        for p in parts:
            self.assertEqual(p, BeamSetDesc(YARN_75SD, 4, 293))

    def test_split_preserves_rest(self):
        for p in BeamSetDesc(YARN_40N, 7, 370).split(2):
            self.assertIs(p.yarn, YARN_40N)
            self.assertEqual(p.beam_count, 7)
            self.assertEqual(p.end_count, 185)

    def test_split_leaves_original(self):
        BS_1172.split(2)
        self.assertEqual(BS_1172.end_count, 1172)

    # merge

    def test_merge_none(self):
        with self.assertRaises(ValueError):
            BeamSetDesc.merge()

    def test_merge_mismatch_yarn(self):
        with self.assertRaises(ValueError):
            BeamSetDesc.merge(BeamSetDesc(YARN_75SD, 4, 586), BeamSetDesc(YARN_75D, 4, 586))

    def test_merge_mismatch_ends(self):
        with self.assertRaises(ValueError):
            BeamSetDesc.merge(BeamSetDesc(YARN_75SD, 4, 586), BeamSetDesc(YARN_75SD, 4, 587))

    def test_merge_mismatch_beams(self):
        with self.assertRaises(ValueError):
            BeamSetDesc.merge(BeamSetDesc(YARN_75SD, 4, 586), BeamSetDesc(YARN_75SD, 3, 586))

    def test_merge_mismatch_third(self):
        h = BeamSetDesc(YARN_75SD, 4, 586)
        with self.assertRaises(ValueError):
            BeamSetDesc.merge(h, h, BeamSetDesc(YARN_75SD, 4, 587))

    def test_merge_one(self):
        self.assertEqual(BeamSetDesc.merge(BS_1172), BS_1172)

    def test_merge_two(self):
        h = BeamSetDesc(YARN_75SD, 4, 586)
        merged = BeamSetDesc.merge(h, h)
        self.assertEqual(merged, BS_1172)
        self.assertEqual(merged.id, '75PWTS04-1172-4')

    def test_merge_four(self):
        self.assertEqual(BeamSetDesc.merge(*[BeamSetDesc(YARN_75SD, 4, 293)] * 4), BS_1172)

    def test_merge_separate_instances(self):
        merged = BeamSetDesc.merge(BeamSetDesc(YARN_40N, 7, 185), BeamSetDesc(YARN_40N, 7, 185))
        self.assertEqual(merged, BeamSetDesc(YARN_40N, 7, 370))

    def test_merge_preserves_rest(self):
        merged = BeamSetDesc.merge(BeamSetDesc(YARN_40N, 7, 185), BeamSetDesc(YARN_40N, 7, 185))
        self.assertEqual(merged.yarn, YARN_40N)
        self.assertEqual(merged.beam_count, 7)

    def test_merge_split_round_trip(self):
        for n in (1, 2, 4):
            with self.subTest(n=n):
                self.assertEqual(BeamSetDesc.merge(*BS_1172.split(n)), BS_1172)


if __name__ == '__main__':
    unittest.main()
