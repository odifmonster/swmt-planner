#!/usr/bin/env python

import unittest

from swmtplanner.core.product.fabric import (
    EXTRA_LIGHT, LIGHT, MEDIUM, BLACK, SD_BLACK,
    STRIP, EMPTY,
    Color, Fabric,
    load_ply1_translation, ply1_to_fabric,
)


def _fabric(id: str, ply1_parts: tuple[str, ...],
            jets: dict[str, tuple[float, float]] = {'J1': (100.0, 200.0)}
            ) -> Fabric:
    return Fabric(id=id, ply1_parts=ply1_parts, greige='G1', style='STY',
                  width=60.0, oz_sq_yd=10.0, yld_pct=0.9,
                  name='Navy', number=540, shade_rating=BLACK, jets=jets)


def _color(shade: int, number: int = 1) -> Color:
    return Color(name='C', number=number, shade_rating=shade)


class _FakeJetState:
    """Stand-in for the real JetState (defined later in core/schedule),
    exposing only the attributes get_needed_strip reads."""

    def __init__(self, cycles_since_strip: int, max_prev_shade: int | None):
        self.cycles_since_strip = cycles_since_strip
        self.max_prev_shade = max_prev_shade


class TestFabricConstruction(unittest.TestCase):

    def test_construction(self):
        """2.1.1 — the whole Fabric is constructed properly: every read-only
        property is exposed correctly, including the color built from
        name/number/shade_rating."""
        f = Fabric(id='F1', ply1_parts=('P1', 'P2'), greige='G1', style='STY',
                   width=60.0, oz_sq_yd=10.0, yld_pct=0.9,
                   name='Navy', number=540, shade_rating=BLACK,
                   jets={'J1': (100.0, 200.0)})
        self.assertEqual(f.id, 'F1')
        self.assertEqual(f.ply1_parts, ('P1', 'P2'))
        self.assertEqual(f.greige, 'G1')
        self.assertEqual(f.style, 'STY')
        self.assertEqual(f.width, 60.0)
        self.assertEqual(f.color, Color(name='Navy', number=540,
                                        shade_rating=BLACK))

    def test_yds_per_lb(self):
        """2.1.2 — yds_per_lb = 36 * 16 / (oz_sq_yd * width) * yld_pct, across a
        couple of cases."""
        f1 = Fabric(id='F1', ply1_parts=(), greige='G', style='S',
                    width=60.0, oz_sq_yd=10.0, yld_pct=0.9,
                    name='C', number=1, shade_rating=BLACK, jets={})
        self.assertAlmostEqual(f1.yds_per_lb, 36 * 16 / (10.0 * 60.0) * 0.9)

        f2 = Fabric(id='F2', ply1_parts=(), greige='G', style='S',
                    width=54.0, oz_sq_yd=8.0, yld_pct=1.0,
                    name='C', number=1, shade_rating=BLACK, jets={})
        self.assertAlmostEqual(f2.yds_per_lb, 36 * 16 / (8.0 * 54.0) * 1.0)

    def test_can_run_on_jet(self):
        """2.1.3 — can_run_on_jet returns True for jets in the jets dict and
        False for jets not in it."""
        f = _fabric('F1', (), jets={'J1': (100.0, 200.0),
                                    'J2': (120.0, 240.0)})
        self.assertTrue(f.can_run_on_jet('J1'))
        self.assertTrue(f.can_run_on_jet('J2'))
        self.assertFalse(f.can_run_on_jet('J9'))

    def test_load_range_on_jet(self):
        """2.1.4 — load_range_on_jet returns the (min, max) per-port load for a
        runnable jet and raises ValueError for a jet not in the jets dict."""
        f = _fabric('F1', (), jets={'J1': (100.0, 200.0),
                                    'J2': (120.0, 240.0)})
        self.assertEqual(f.load_range_on_jet('J1'), (100.0, 200.0))
        self.assertEqual(f.load_range_on_jet('J2'), (120.0, 240.0))
        with self.assertRaises(ValueError):
            f.load_range_on_jet('J9')


class TestPly1Translation(unittest.TestCase):

    def test_load_one_to_one(self):
        """2.2.1 — load_ply1_translation works on a one-to-one table."""
        f1 = _fabric('F1', ('P1',))
        f2 = _fabric('F2', ('P2',))
        load_ply1_translation([f1, f2])
        self.assertEqual(ply1_to_fabric('P1'), f1)
        self.assertEqual(ply1_to_fabric('P2'), f2)

    def test_load_many_to_one(self):
        """2.2.2 — load_ply1_translation works on a many-to-one table."""
        f = _fabric('F1', ('P1', 'P2', 'P3'))
        load_ply1_translation([f])
        self.assertEqual(ply1_to_fabric('P1'), f)
        self.assertEqual(ply1_to_fabric('P2'), f)
        self.assertEqual(ply1_to_fabric('P3'), f)

    def test_to_fabric(self):
        """2.2.3 — ply1_to_fabric returns the expected Fabric object."""
        f = _fabric('F1', ('P1',))
        load_ply1_translation([f])
        self.assertIs(ply1_to_fabric('P1'), f)

    def test_to_fabric_unknown(self):
        """2.2.4 — ply1_to_fabric returns None on an unknown ply1 part."""
        f = _fabric('F1', ('P1',))
        load_ply1_translation([f])
        self.assertIsNone(ply1_to_fabric('NOPE'))


class TestGetNeededStrip(unittest.TestCase):

    def test_no_prep_needed(self):
        """2.3.1 — get_needed_strip returns [] when no preparation is needed:
        the same color again before the 9-cycle limit; a different color of the
        same shade; a different shade in the same tier; any non-extra-light
        color right after a strip; and a darker shade after a lighter one."""
        # same color again, before the 9-cycle limit
        self.assertEqual(
            _color(MEDIUM).get_needed_strip(_FakeJetState(3, MEDIUM)), [])
        # a different color of the same shade
        self.assertEqual(
            _color(MEDIUM, number=2).get_needed_strip(
                _FakeJetState(3, MEDIUM)), [])
        # a different shade in the same tier (light tier, both directions)
        self.assertEqual(
            _color(LIGHT).get_needed_strip(_FakeJetState(1, EXTRA_LIGHT)), [])
        self.assertEqual(
            _color(EXTRA_LIGHT).get_needed_strip(_FakeJetState(1, LIGHT)), [])
        # a different shade in the same tier (black tier, both directions)
        self.assertEqual(
            _color(BLACK).get_needed_strip(_FakeJetState(1, SD_BLACK)), [])
        self.assertEqual(
            _color(SD_BLACK).get_needed_strip(_FakeJetState(1, BLACK)), [])
        # any non-extra-light color immediately after a strip
        for shade in (LIGHT, MEDIUM, BLACK, SD_BLACK):
            self.assertEqual(
                _color(shade).get_needed_strip(_FakeJetState(0, None)), [])
        # a darker shade after a lighter shade
        self.assertEqual(
            _color(MEDIUM).get_needed_strip(_FakeJetState(1, LIGHT)), [])
        self.assertEqual(
            _color(BLACK).get_needed_strip(_FakeJetState(1, MEDIUM)), [])

    def test_single_strip(self):
        """2.3.2 — get_needed_strip returns [STRIP]: a light after a medium; a
        light after an SD black; a medium after an SD black; the 9-cycle limit
        cases (medium with a non-black max; black and SD black with a black and
        a medium max); and a light or medium after a black once one strip has
        already run."""
        # a light after a medium
        self.assertEqual(
            _color(LIGHT).get_needed_strip(_FakeJetState(2, MEDIUM)), [STRIP])
        # a light after an SD black
        self.assertEqual(
            _color(LIGHT).get_needed_strip(_FakeJetState(2, SD_BLACK)), [STRIP])
        # a medium after an SD black
        self.assertEqual(
            _color(MEDIUM).get_needed_strip(_FakeJetState(2, SD_BLACK)),
            [STRIP])
        # a medium at the 9-cycle limit, max shade not black
        self.assertEqual(
            _color(MEDIUM).get_needed_strip(_FakeJetState(9, MEDIUM)), [STRIP])
        # a black at the 9-cycle limit, max shade black then medium
        self.assertEqual(
            _color(BLACK).get_needed_strip(_FakeJetState(9, BLACK)), [STRIP])
        self.assertEqual(
            _color(BLACK).get_needed_strip(_FakeJetState(9, MEDIUM)), [STRIP])
        # an SD black at the 9-cycle limit, max shade black then medium
        self.assertEqual(
            _color(SD_BLACK).get_needed_strip(_FakeJetState(9, BLACK)), [STRIP])
        self.assertEqual(
            _color(SD_BLACK).get_needed_strip(_FakeJetState(9, MEDIUM)),
            [STRIP])
        # a light or medium after a black with one strip already run
        self.assertEqual(
            _color(LIGHT).get_needed_strip(_FakeJetState(0, BLACK)), [STRIP])
        self.assertEqual(
            _color(MEDIUM).get_needed_strip(_FakeJetState(0, BLACK)), [STRIP])

    def test_double_strip(self):
        """2.3.3 — get_needed_strip returns [STRIP, STRIP] for a light or medium
        after a black, both before and at the 9-cycle limit."""
        # before the 9-cycle limit
        self.assertEqual(
            _color(LIGHT).get_needed_strip(_FakeJetState(3, BLACK)),
            [STRIP, STRIP])
        self.assertEqual(
            _color(MEDIUM).get_needed_strip(_FakeJetState(3, BLACK)),
            [STRIP, STRIP])
        # at the 9-cycle limit
        self.assertEqual(
            _color(LIGHT).get_needed_strip(_FakeJetState(9, BLACK)),
            [STRIP, STRIP])
        self.assertEqual(
            _color(MEDIUM).get_needed_strip(_FakeJetState(9, BLACK)),
            [STRIP, STRIP])

    def test_extra_light(self):
        """2.3.4 — the extra-light priming rule: an empty cycle after a strip;
        a double strip and empty after a black with no strip; a strip and empty
        after a black with one strip already run; and a strip and empty after a
        medium or an SD black."""
        # immediately after a strip (max_prev_shade None)
        self.assertEqual(
            _color(EXTRA_LIGHT).get_needed_strip(_FakeJetState(0, None)),
            [EMPTY])
        # after a black with no strip yet
        self.assertEqual(
            _color(EXTRA_LIGHT).get_needed_strip(_FakeJetState(3, BLACK)),
            [STRIP, STRIP, EMPTY])
        # after a black with one strip already run
        self.assertEqual(
            _color(EXTRA_LIGHT).get_needed_strip(_FakeJetState(0, BLACK)),
            [STRIP, EMPTY])
        # after a medium or an SD black
        self.assertEqual(
            _color(EXTRA_LIGHT).get_needed_strip(_FakeJetState(2, MEDIUM)),
            [STRIP, EMPTY])
        self.assertEqual(
            _color(EXTRA_LIGHT).get_needed_strip(_FakeJetState(2, SD_BLACK)),
            [STRIP, EMPTY])


if __name__ == '__main__':
    unittest.main()
