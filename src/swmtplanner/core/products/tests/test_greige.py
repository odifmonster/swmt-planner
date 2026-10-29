#!/usr/bin/env python

import unittest
from dataclasses import FrozenInstanceError

from swmtplanner.core.products import (
    YarnAttrs, Yarn, BeamSetDesc, BarConfig, BeamConfig, Greige,
)

ATTRS_NONE = YarnAttrs(False, False, False)
ATTRS_TX = YarnAttrs(True, False, False)
YARN_75SD = Yarn(75, 'polyester', 'white', 'semidull', ATTRS_TX)
YARN_75D = Yarn(75, 'polyester', 'white', 'dull', ATTRS_TX)
YARN_40N = Yarn(40, 'nylon', 'white', 'semidull', ATTRS_NONE)

BS_1172 = BeamSetDesc(YARN_75SD, 4, 1172)
BS_586 = BeamSetDesc(YARN_75SD, 4, 586)
BS_1170 = BeamSetDesc(YARN_40N, 4, 1170)
BS_390 = BeamSetDesc(YARN_40N, 4, 390)

BAR1 = BarConfig(1, 61.5, 14.71, '1/0,1/2,2/3,2/1')
BAR2 = BarConfig(2, 61.5, 14.73, '2/3,2/1,1/0,1/2')
BAR3 = BarConfig(3, 81.5, 70.56, '1/0,2/3')
BAR4 = BarConfig(4, 50.0, 33.3, '1/0,1/2')
BAR5 = BarConfig(5, 50.0, 33.3, '1/2,1/0')
BAR6 = BarConfig(6, 50.0, 33.4, '1/0,2/3')

CFG_1BAR = BeamConfig(BS_1172, (BAR3,))
CFG_2BAR = BeamConfig(BS_1172, (BAR1, BAR2))
CFG_3BAR = BeamConfig(BS_1170, (BAR4, BAR5, BAR6))

G_5429D = Greige('AU5429D', 28, 168, 24.36, 300.0, (CFG_2BAR, CFG_1BAR),
                 rates={'K1': 12.5, 'K2': 11.0})


class TestBarConfig(unittest.TestCase):

    def test_bar_init(self):
        self.assertEqual(BAR1.num, 1)
        self.assertEqual(BAR1.runlen, 61.5)
        self.assertEqual(BAR1.pct, 14.71)
        self.assertEqual(BAR1.stitch, '1/0,1/2,2/3,2/1')

    def test_bar_equality(self):
        self.assertEqual(BAR1, BarConfig(1, 61.5, 14.71, '1/0,1/2,2/3,2/1'))
        self.assertNotEqual(BAR1, BAR2)
        self.assertNotEqual(BAR1, BarConfig(1, 61.0, 14.71, '1/0,1/2,2/3,2/1'))

    def test_bar_hashable(self):
        s = {BAR1, BarConfig(1, 61.5, 14.71, '1/0,1/2,2/3,2/1'), BAR2}
        self.assertEqual(len(s), 2)

    def test_bar_frozen(self):
        with self.assertRaises(FrozenInstanceError):
            BAR1.runlen = 1.0


class TestBeamConfig(unittest.TestCase):

    def test_cfg_init(self):
        self.assertIs(CFG_2BAR.beamset, BS_1172)
        self.assertEqual(CFG_2BAR.bars, (BAR1, BAR2))

    def test_cfg_equality(self):
        self.assertEqual(CFG_2BAR, BeamConfig(BS_1172, (BAR1, BAR2)))
        self.assertNotEqual(CFG_2BAR, BeamConfig(BS_1172, (BAR2, BAR1)))
        self.assertNotEqual(CFG_2BAR, CFG_1BAR)

    def test_cfg_frozen(self):
        with self.assertRaises(FrozenInstanceError):
            CFG_2BAR.bars = ()

    # can_use, single beam set

    def test_use_one_bar_match(self):
        self.assertTrue(CFG_1BAR.can_use([BS_1172]))

    def test_use_one_bar_match_separate_instance(self):
        self.assertTrue(CFG_1BAR.can_use([BeamSetDesc(YARN_75SD, 4, 1172)]))

    def test_use_one_bar_wrong_ends(self):
        self.assertFalse(CFG_1BAR.can_use([BS_586]))

    def test_use_one_bar_wrong_yarn(self):
        self.assertFalse(CFG_1BAR.can_use([BeamSetDesc(YARN_75D, 4, 1172)]))

    def test_use_one_bar_wrong_beams(self):
        self.assertFalse(CFG_1BAR.can_use([BeamSetDesc(YARN_75SD, 3, 1172)]))

    def test_use_two_bar_match(self):
        self.assertTrue(CFG_2BAR.can_use([BS_1172]))

    def test_use_two_bar_half(self):
        self.assertFalse(CFG_2BAR.can_use([BS_586]))

    def test_use_two_bar_wrong_yarn(self):
        self.assertFalse(CFG_2BAR.can_use([BeamSetDesc(YARN_75D, 4, 1172)]))

    def test_use_three_bar_match(self):
        self.assertTrue(CFG_3BAR.can_use([BS_1170]))

    def test_use_three_bar_wrong_ends(self):
        self.assertFalse(CFG_3BAR.can_use([BS_390]))

    def test_use_empty_one_bar(self):
        self.assertFalse(CFG_1BAR.can_use([]))

    def test_use_empty_two_bar(self):
        self.assertFalse(CFG_2BAR.can_use([]))

    # can_use, multiple beam sets, false cases

    def test_use_count_one_bar_two_sets(self):
        self.assertFalse(CFG_1BAR.can_use([BS_586, BS_586]))

    def test_use_count_two_bar_three_sets(self):
        self.assertFalse(CFG_2BAR.can_use([BS_586, BS_586, BS_586]))

    def test_use_count_three_bar_two_sets(self):
        self.assertFalse(CFG_3BAR.can_use([BeamSetDesc(YARN_40N, 4, 585)] * 2))

    def test_use_merged_wrong_ends(self):
        self.assertFalse(CFG_2BAR.can_use([BeamSetDesc(YARN_75SD, 4, 585)] * 2))

    def test_use_merged_wrong_yarn(self):
        self.assertFalse(CFG_2BAR.can_use([BeamSetDesc(YARN_75D, 4, 586)] * 2))

    def test_use_merged_wrong_beams(self):
        self.assertFalse(CFG_2BAR.can_use([BeamSetDesc(YARN_75SD, 3, 586)] * 2))

    def test_use_unmergeable_ends(self):
        self.assertFalse(CFG_2BAR.can_use([BS_586, BeamSetDesc(YARN_75SD, 4, 587)]))

    def test_use_unmergeable_yarn(self):
        self.assertFalse(CFG_2BAR.can_use([BS_586, BeamSetDesc(YARN_75D, 4, 586)]))

    def test_use_unmergeable_three_bar(self):
        self.assertFalse(CFG_3BAR.can_use([BS_390, BS_390, BeamSetDesc(YARN_40N, 4, 391)]))

    # can_use, multiple beam sets, true cases

    def test_use_two_bar_two_sets(self):
        self.assertTrue(CFG_2BAR.can_use([BS_586, BS_586]))

    def test_use_two_bar_two_sets_separate_instances(self):
        self.assertTrue(CFG_2BAR.can_use([BeamSetDesc(YARN_75SD, 4, 586),
                                          BeamSetDesc(YARN_75SD, 4, 586)]))

    def test_use_three_bar_three_sets(self):
        self.assertTrue(CFG_3BAR.can_use([BS_390, BS_390, BS_390]))

    def test_use_split_round_trip(self):
        self.assertTrue(CFG_2BAR.can_use(BS_1172.split(2)))
        self.assertTrue(CFG_3BAR.can_use(BS_1170.split(3)))


class TestGreige(unittest.TestCase):

    def test_greige_init(self):
        self.assertEqual(G_5429D.id, 'AU5429D')
        self.assertEqual(G_5429D.gauge, 28)
        self.assertEqual(G_5429D.width, 168)
        self.assertEqual(G_5429D.rack_wt, 24.36)
        self.assertEqual(G_5429D.std_wt, 300.0)
        self.assertEqual(G_5429D.beam_cfgs, (CFG_2BAR, CFG_1BAR))

    def test_greige_pattern(self):
        self.assertEqual(G_5429D.pattern,
                         [('1/0,1/2,2/3,2/1', '2/3,2/1,1/0,1/2'), ('1/0,2/3',)])

    def test_greige_beamsets(self):
        self.assertEqual(G_5429D.beamsets,
                         [('75PWTS04-1172-4', (1, 2)), ('75PWTS04-1172-4', (3,))])

    def test_greige_pattern_reversed(self):
        g = Greige('AU5429H', 28, 168, 24.36, 300.0, (CFG_1BAR, CFG_2BAR), rates={})
        self.assertEqual(g.pattern, list(reversed(G_5429D.pattern)))
        self.assertEqual(g.pattern[1], ('1/0,1/2,2/3,2/1', '2/3,2/1,1/0,1/2'))

    def test_greige_pattern_empty(self):
        self.assertEqual(Greige('X', 28, 168, 1.0, 1.0, (), rates={}).pattern, [])

    def test_greige_can_run(self):
        self.assertTrue(G_5429D.can_run_on_machine('K1'))
        self.assertTrue(G_5429D.can_run_on_machine('K2'))
        self.assertFalse(G_5429D.can_run_on_machine('K9'))

    def test_greige_rate(self):
        self.assertEqual(G_5429D.get_rate_on_machine('K1'), 12.5)
        self.assertEqual(G_5429D.get_rate_on_machine('K2'), 11.0)

    def test_greige_rate_unknown(self):
        with self.assertRaises(KeyError):
            G_5429D.get_rate_on_machine('K9')

    def test_greige_rates_copied(self):
        src = {'K1': 1.0}
        g = Greige('X', 28, 168, 1.0, 1.0, (), rates=src)
        src['K2'] = 2.0
        self.assertFalse(g.can_run_on_machine('K2'))

    def test_greige_rates_private(self):
        self.assertFalse(hasattr(G_5429D, 'rates'))
        self.assertNotIn('K1', repr(G_5429D))

    def test_greige_equal_by_id(self):
        other = Greige('AU5429D', 32, 1, 0.0, 0.0, (), rates={})
        self.assertEqual(G_5429D, other)
        self.assertEqual(hash(G_5429D), hash(other))

    def test_greige_unequal_id(self):
        other = Greige('AU5429H', 28, 168, 24.36, 300.0, (CFG_2BAR, CFG_1BAR),
                       rates={'K1': 12.5, 'K2': 11.0})
        self.assertNotEqual(G_5429D, other)

    def test_greige_hashable(self):
        s = {G_5429D, Greige('AU5429D', 28, 168, 24.36, 300.0, (), rates={})}
        self.assertEqual(len(s), 1)

    def test_greige_frozen(self):
        with self.assertRaises(FrozenInstanceError):
            G_5429D.gauge = 32


if __name__ == '__main__':
    unittest.main()
