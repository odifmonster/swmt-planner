#!/usr/bin/env python

import unittest
from datetime import datetime

from swmtplanner.core.materials import GreigeRoll
from swmtplanner.core.materials.inventory import GreigeGroup

D1 = datetime(2026, 7, 1)


def _roll(id, qty, sku='S1', plant='FS'):
    # greige=None -> default 700 -> single_target 350
    return GreigeRoll(id=id, sku=sku, avail_date=D1, qty=qty, plant=plant,
                      variant='V', yarn_merge=1, greige=None)


def _build(rolls):
    g = GreigeGroup()
    for r in rolls:
        g.add(r)
    g.prepare_dye_pool()
    return g


def _lots(g, style):
    return sorted(sorted(r.id for r in lot) for lot in g.dye_lots(style))


class TestGreigeGroup(unittest.TestCase):

    def test_one_lot(self):
        """4.1.1 — same sku+plant, eligible, within 10 lbs -> one lot."""
        g = _build([_roll('A', 350.0), _roll('B', 352.0), _roll('C', 348.0)])
        self.assertEqual(_lots(g, 'S1'), [['A', 'B', 'C']])

    def test_split_by_plant(self):
        """4.1.2 — within 10 lbs but different plants -> separate lots."""
        g = _build([_roll('A', 350.0, plant='FS'),
                    _roll('B', 352.0, plant='FS'),
                    _roll('C', 348.0, plant='WV')])
        self.assertEqual(_lots(g, 'S1'), [['A', 'B'], ['C']])

    def test_split_by_weight(self):
        """4.1.3 — same plant, avg_port_wt spread beyond 10 lbs -> split."""
        g = _build([_roll('A', 305.0), _roll('B', 310.0), _roll('C', 395.0)])
        self.assertEqual(_lots(g, 'S1'), [['A', 'B'], ['C']])

    def test_split_by_plant_and_weight(self):
        """4.1.4 — split by both plant and weight."""
        g = _build([_roll('A', 305.0, plant='FS'),
                    _roll('B', 310.0, plant='FS'),
                    _roll('C', 305.0, plant='WV'),
                    _roll('D', 395.0, plant='WV')])
        self.assertEqual(_lots(g, 'S1'), [['A', 'B'], ['C'], ['D']])

    def test_too_small_excluded(self):
        """4.1.5 — rolls with avg_port_wt below MIN_PORT_LBS are excluded."""
        g = _build([_roll('A', 350.0), _roll('B', 250.0)])
        lots = _lots(g, 'S1')
        self.assertEqual(lots, [['A']])
        self.assertNotIn('B', {i for lot in lots for i in lot})

    def test_cache_invalidation(self):
        """4.1.6 — add/remove invalidates that style's cache."""
        g = GreigeGroup()
        g.add(_roll('A', 350.0))
        g.add(_roll('B', 352.0))
        g.prepare_dye_pool()
        self.assertTrue(g.has_cached_lots('S1'))
        g.add(_roll('C', 348.0))                 # add invalidates
        self.assertFalse(g.has_cached_lots('S1'))
        with self.assertRaises(KeyError):
            g.dye_lots('S1')
        g.prepare_dye_pool()
        self.assertTrue(g.has_cached_lots('S1'))
        g.remove('A', 'S1')                      # remove invalidates
        self.assertFalse(g.has_cached_lots('S1'))
        with self.assertRaises(KeyError):
            g.dye_lots('S1')

    def test_shift_after_change(self):
        """4.1.7 — removing the smallest standard roll and adding a larger one
        shifts the lots."""
        g = GreigeGroup()
        for r in [_roll('A', 305.0), _roll('B', 312.0), _roll('C', 320.0)]:
            g.add(r)
        g.prepare_dye_pool()
        self.assertEqual(_lots(g, 'S1'), [['A', 'B'], ['C']])
        g.remove('A', 'S1')
        g.add(_roll('D', 360.0))
        g.prepare_dye_pool()
        self.assertEqual(_lots(g, 'S1'), [['B', 'C'], ['D']])


if __name__ == '__main__':
    unittest.main()
