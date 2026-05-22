#!/usr/bin/env python

import operator
import unittest

from swmtplanner.product import BeamSet, Greige
from swmtplanner.materials import GreigeRoll, RawMat
from swmtplanner.materials.inventory import (
    GroupKey, Inventory, InvGroup, in_range,
)


def _make_greige() -> Greige:
    """Helper to build a Greige with 2 * port_load_tgt = 100."""
    bs = BeamSet('150D MICRO 50X4', 0.0)
    return Greige(
        'STYLE-A', 0.0, 'fam', 28, bs, 0.4, bs, 0.6, 50.0, 2, {},
    )


def _make_roll(
    g: Greige,
    id_: str,
    qty: float,
    plant: str = 'FS',
    item_variant: str = 'V',
) -> GreigeRoll:
    return GreigeRoll(id_, g, qty, None, plant, item_variant, 'M')


# ============================================================
# Section 1: InvGroup
# ============================================================


class InvGroupConstructionTests(unittest.TestCase):
    """Covers section 1.1 of COVERAGE.md."""

    def test_construction(self):
        """1.1.1: construction works as expected"""
        grp = InvGroup[GreigeRoll]('qty')
        self.assertEqual(grp.attr_name, 'qty')
        self.assertEqual(grp.sorted_keys, [])
        self.assertEqual(grp.mapping, {})
        self.assertEqual(grp.snapshots, {})


class InvGroupAddTests(unittest.TestCase):
    """Covers section 1.2 of COVERAGE.md."""

    def setUp(self):
        self.greige = _make_greige()
        self.group = InvGroup[GreigeRoll]('qty')

    def test_distinct_values_distinct_buckets(self):
        """1.2.1: items with distinct attribute values land in different buckets"""
        r1 = _make_roll(self.greige, 'R1', 50.0)
        r2 = _make_roll(self.greige, 'R2', 75.0)
        r3 = _make_roll(self.greige, 'R3', 100.0)
        self.group.add(r1)
        self.group.add(r2)
        self.group.add(r3)
        self.assertEqual(
            self.group.mapping,
            {50.0: {r1}, 75.0: {r2}, 100.0: {r3}},
        )
        self.assertEqual(
            self.group.snapshots,
            {'R1': 50.0, 'R2': 75.0, 'R3': 100.0},
        )

    def test_same_value_same_bucket(self):
        """1.2.2: items with the same attribute value share a bucket"""
        r1 = _make_roll(self.greige, 'R1', 50.0)
        r2 = _make_roll(self.greige, 'R2', 50.0)
        self.group.add(r1)
        self.group.add(r2)
        self.assertEqual(self.group.mapping, {50.0: {r1, r2}})
        self.assertEqual(self.group.sorted_keys, [50.0])

    def test_sorted_keys_independent_of_order(self):
        """1.2.3: sorted_keys stays sorted regardless of insertion order"""
        rolls = [
            _make_roll(self.greige, 'R75', 75.0),
            _make_roll(self.greige, 'R25', 25.0),
            _make_roll(self.greige, 'R100', 100.0),
            _make_roll(self.greige, 'R50', 50.0),
        ]
        for r in rolls:
            self.group.add(r)
        self.assertEqual(self.group.sorted_keys, [25.0, 50.0, 75.0, 100.0])

    def test_re_add_updates_snapshot(self):
        """1.2.4: re-adding an item with the same id snapshots the current value"""
        r1 = _make_roll(self.greige, 'R1', 50.0)
        self.group.add(r1)
        self.group.remove(r1)
        # Construct a new roll with the same id but a different qty.
        r1_new = _make_roll(self.greige, 'R1', 75.0)
        self.group.add(r1_new)
        self.assertEqual(self.group.snapshots, {'R1': 75.0})
        self.assertEqual(self.group.mapping, {75.0: {r1_new}})
        self.assertEqual(self.group.sorted_keys, [75.0])


class InvGroupRemoveTests(unittest.TestCase):
    """Covers section 1.3 of COVERAGE.md."""

    def setUp(self):
        self.greige = _make_greige()
        self.group = InvGroup[GreigeRoll]('qty')

    def test_basic_removal(self):
        """1.3.1: basic removal drops item from mapping and snapshots"""
        r1 = _make_roll(self.greige, 'R1', 50.0)
        r2 = _make_roll(self.greige, 'R2', 75.0)
        self.group.add(r1)
        self.group.add(r2)
        self.group.remove(r1)
        self.assertNotIn('R1', self.group.snapshots)
        self.assertEqual(self.group.mapping, {75.0: {r2}})

    def test_remove_last_drops_bucket(self):
        """1.3.2: removing the last item from a bucket drops the key"""
        r1 = _make_roll(self.greige, 'R1', 50.0)
        r2 = _make_roll(self.greige, 'R2', 75.0)
        self.group.add(r1)
        self.group.add(r2)
        self.group.remove(r1)
        self.assertNotIn(50.0, self.group.mapping)
        self.assertEqual(self.group.sorted_keys, [75.0])

    def test_remove_non_last_keeps_bucket(self):
        """1.3.3: removing one of several items leaves the bucket intact"""
        r1 = _make_roll(self.greige, 'R1', 50.0)
        r2 = _make_roll(self.greige, 'R2', 50.0)
        r3 = _make_roll(self.greige, 'R3', 75.0)
        self.group.add(r1)
        self.group.add(r2)
        self.group.add(r3)
        self.group.remove(r1)
        self.assertEqual(self.group.mapping, {50.0: {r2}, 75.0: {r3}})
        self.assertEqual(self.group.sorted_keys, [50.0, 75.0])


class InvGroupVerifyTests(unittest.TestCase):
    """Covers section 1.4 of COVERAGE.md."""

    def setUp(self):
        self.greige = _make_greige()
        self.group = InvGroup[GreigeRoll]('qty')

    def test_verify_unknown_item_is_noop(self):
        """1.4.1: no-op when the item is not in the group"""
        r = _make_roll(self.greige, 'R1', 50.0)
        # Never added; should not raise.
        self.group.verify(r)

    def test_verify_unchanged_is_noop(self):
        """1.4.2: no-op when present and unchanged"""
        r = _make_roll(self.greige, 'R1', 50.0)
        self.group.add(r)
        self.group.verify(r)  # should not raise

    def test_verify_raises_on_mutation(self):
        """1.4.3: raises RuntimeError on mutation, with snapshot/current diff in the message"""
        r = _make_roll(self.greige, 'R1', 50.0)
        self.group.add(r)
        r._qty = 75.0
        with self.assertRaises(RuntimeError) as cm:
            self.group.verify(r)
        msg = str(cm.exception)
        self.assertIn("'qty'", msg)
        self.assertIn('50', msg)
        self.assertIn('75', msg)

    def test_remove_on_mutated_raises_with_state_intact(self):
        """1.4.4: remove reports mutation before touching mapping/sorted_keys/snapshots"""
        r = _make_roll(self.greige, 'R1', 50.0)
        self.group.add(r)
        orig_mapping = {k: set(v) for k, v in self.group.mapping.items()}
        orig_keys = list(self.group.sorted_keys)
        orig_snapshots = dict(self.group.snapshots)
        r._qty = 75.0
        with self.assertRaises(RuntimeError):
            self.group.remove(r)
        # State should be untouched.
        self.assertEqual(
            {k: set(v) for k, v in self.group.mapping.items()},
            orig_mapping,
        )
        self.assertEqual(self.group.sorted_keys, orig_keys)
        self.assertEqual(self.group.snapshots, orig_snapshots)


class InvGroupGetGroupTests(unittest.TestCase):
    """Covers section 1.5 of COVERAGE.md."""

    def setUp(self):
        self.greige = _make_greige()
        self.group = InvGroup[GreigeRoll]('qty')

    # ---- 1.5.1 empty-result cases ----

    def test_empty_group_returns_empty(self):
        """1.5.1: an empty group returns set() for any GroupKey"""
        self.assertEqual(
            self.group.get_group(GroupKey(operator.eq, 50.0)), set(),
        )
        self.assertEqual(
            self.group.get_group(GroupKey(operator.lt, 100.0)), set(),
        )
        self.assertEqual(
            self.group.get_group(GroupKey(in_range(), (0.0, 1000.0))),
            set(),
        )

    def test_eq_miss_returns_empty(self):
        """1.5.1: eq predicate with no matching items returns empty"""
        for r in (
            _make_roll(self.greige, 'A', 25.0),
            _make_roll(self.greige, 'B', 75.0),
        ):
            self.group.add(r)
        self.assertEqual(
            self.group.get_group(GroupKey(operator.eq, 50.0)), set(),
        )

    def test_lt_all_ge_returns_empty(self):
        """1.5.1: lt predicate when every item has attr >= cutoff returns empty"""
        for r in (
            _make_roll(self.greige, 'A', 50.0),
            _make_roll(self.greige, 'B', 75.0),
            _make_roll(self.greige, 'C', 100.0),
        ):
            self.group.add(r)
        self.assertEqual(
            self.group.get_group(GroupKey(operator.lt, 50.0)), set(),
        )

    def test_in_range_no_overlap_returns_empty(self):
        """1.5.1: in_range predicate with no items in [lo, hi) returns empty"""
        for r in (
            _make_roll(self.greige, 'A', 10.0),  # below
            _make_roll(self.greige, 'B', 100.0),  # at hi (excluded by default)
            _make_roll(self.greige, 'C', 150.0),  # above
        ):
            self.group.add(r)
        # Range [50, 100): nothing inside.
        self.assertEqual(
            self.group.get_group(GroupKey(in_range(), (50.0, 100.0))),
            set(),
        )

    # ---- 1.5.2 basic non-empty cases ----

    def _populate_basic(self):
        self.r25 = _make_roll(self.greige, 'R25', 25.0)
        self.r50 = _make_roll(self.greige, 'R50', 50.0)
        self.r75 = _make_roll(self.greige, 'R75', 75.0)
        self.r100 = _make_roll(self.greige, 'R100', 100.0)
        for r in (self.r25, self.r50, self.r75, self.r100):
            self.group.add(r)

    def test_basic_eq(self):
        """1.5.2: eq returns the single matching item"""
        self._populate_basic()
        self.assertEqual(
            self.group.get_group(GroupKey(operator.eq, 50.0)),
            {self.r50},
        )

    def test_basic_gt(self):
        """1.5.2: gt returns all items strictly greater than the cutoff"""
        self._populate_basic()
        self.assertEqual(
            self.group.get_group(GroupKey(operator.gt, 50.0)),
            {self.r75, self.r100},
        )

    def test_basic_le(self):
        """1.5.2: le returns all items less than or equal to the cutoff"""
        self._populate_basic()
        self.assertEqual(
            self.group.get_group(GroupKey(operator.le, 50.0)),
            {self.r25, self.r50},
        )

    def test_basic_in_range(self):
        """1.5.2: in_range returns items in [lo, hi) with the default excl_hi"""
        self._populate_basic()
        # 50 included (>=), 100 excluded (excl_hi). 75 in between.
        self.assertEqual(
            self.group.get_group(GroupKey(in_range(), (50.0, 100.0))),
            {self.r50, self.r75},
        )

    # ---- 1.5.3 / 1.5.4 / 1.5.5 add/remove sequences ----

    def test_remove_shrinks_result_set(self):
        """1.5.3: removing one of several matching items shrinks the result but leaves it non-empty"""
        a = _make_roll(self.greige, 'A', 50.0)
        b = _make_roll(self.greige, 'B', 50.0)
        c = _make_roll(self.greige, 'C', 75.0)
        for r in (a, b, c):
            self.group.add(r)
        gk = GroupKey(operator.eq, 50.0)
        self.assertEqual(self.group.get_group(gk), {a, b})
        self.group.remove(a)
        self.assertEqual(self.group.get_group(gk), {b})

    def test_remove_last_matching_empties_result(self):
        """1.5.4: removing the last matching item produces an empty result"""
        a = _make_roll(self.greige, 'A', 50.0)
        b = _make_roll(self.greige, 'B', 75.0)
        self.group.add(a)
        self.group.add(b)
        gk = GroupKey(operator.eq, 50.0)
        self.assertEqual(self.group.get_group(gk), {a})
        self.group.remove(a)
        self.assertEqual(self.group.get_group(gk), set())

    def test_add_grows_result_set(self):
        """1.5.5: adding a new matching item grows the result set"""
        a = _make_roll(self.greige, 'A', 25.0)
        b = _make_roll(self.greige, 'B', 75.0)
        self.group.add(a)
        self.group.add(b)
        gk = GroupKey(operator.gt, 50.0)
        self.assertEqual(self.group.get_group(gk), {b})
        c = _make_roll(self.greige, 'C', 100.0)
        self.group.add(c)
        self.assertEqual(self.group.get_group(gk), {b, c})

    # ---- 1.5.6 / 1.5.7 remove → modify → re-add ----

    def test_remove_modify_readd_moves_item(self):
        """1.5.6: re-adding with a different attr value moves the item across predicates"""
        r = _make_roll(self.greige, 'R', 50.0)
        self.group.add(r)
        gk_lt60 = GroupKey(operator.lt, 60.0)
        gk_gt60 = GroupKey(operator.gt, 60.0)
        # Initially: in lt60, not in gt60.
        self.assertIn(r, self.group.get_group(gk_lt60))
        self.assertNotIn(r, self.group.get_group(gk_gt60))
        # Remove, mutate the live attribute, re-add — snapshot updates.
        self.group.remove(r)
        r._qty = 80.0
        self.group.add(r)
        # Now: not in lt60, in gt60.
        self.assertNotIn(r, self.group.get_group(gk_lt60))
        self.assertIn(r, self.group.get_group(gk_gt60))

    def test_noop_modification_keeps_item_in_same_predicates(self):
        """1.5.7: modification that preserves predicate truth keeps membership unchanged"""
        r = _make_roll(self.greige, 'R', 50.0)
        self.group.add(r)
        gk_lt60 = GroupKey(operator.lt, 60.0)
        gk_gt60 = GroupKey(operator.gt, 60.0)
        # Initially: in lt60, not in gt60.
        self.assertIn(r, self.group.get_group(gk_lt60))
        self.assertNotIn(r, self.group.get_group(gk_gt60))
        # Cycle with qty 50 → 55 (both satisfy lt 60, neither satisfies gt 60).
        self.group.remove(r)
        r._qty = 55.0
        self.group.add(r)
        # Membership for these predicates is unchanged.
        self.assertIn(r, self.group.get_group(gk_lt60))
        self.assertNotIn(r, self.group.get_group(gk_gt60))

    def test_get_group_raises_on_mutated_item_in_match(self):
        """1.5.8: mutation of an item in a matched bucket raises RuntimeError"""
        r = _make_roll(self.greige, 'R', 50.0)
        self.group.add(r)
        # Mutate without going through remove/add: snapshot still 50, live = 80.
        r._qty = 80.0
        with self.assertRaises(RuntimeError) as cm:
            # The bucket for key 50 matches; verify() catches the mismatch.
            self.group.get_group(GroupKey(operator.eq, 50.0))
        self.assertIn("'qty'", str(cm.exception))


# ============================================================
# Section 2: Inventory
# ============================================================


class TestInv(Inventory[GreigeRoll]):
    """Minimal concrete `Inventory` used by the Section 2 tests."""

    def new_group(self, **kwargs):
        return InvGroup[GreigeRoll](attr_name=kwargs['attr_name'])


class TestMat(RawMat):
    """`RawMat` subclass with no extra properties; used to drive the
    missing-key-attribute error path in `Inventory.add`."""
    pass


class InventoryGetTests(unittest.TestCase):
    """Covers section 2.1 of COVERAGE.md."""

    def setUp(self):
        self.greige = _make_greige()
        self.inv = TestInv(['plant', 'item_variant'])

    def test_unknown_id_returns_none(self):
        """2.1.1: returns None for an unknown id (empty and populated)"""
        self.assertIsNone(self.inv.get('NOPE'))
        r = _make_roll(self.greige, 'R1', 50.0)
        self.inv.add(r)
        self.assertIsNone(self.inv.get('STILL_NOPE'))

    def test_returns_correct_item(self):
        """2.1.2: returns the correct item for a known id, by identity"""
        r = _make_roll(self.greige, 'R1', 50.0)
        self.inv.add(r)
        self.assertIs(self.inv.get('R1'), r)

    def test_state_tracking_across_add_remove(self):
        """2.1.3: state tracking across add/remove sequences"""
        r1 = _make_roll(self.greige, 'R1', 50.0)
        r2 = _make_roll(self.greige, 'R2', 75.0)
        r3 = _make_roll(self.greige, 'R3', 100.0)
        for r in (r1, r2, r3):
            self.inv.add(r)
        self.assertIs(self.inv.get('R1'), r1)
        self.assertIs(self.inv.get('R2'), r2)
        self.assertIs(self.inv.get('R3'), r3)
        self.inv.remove('R2')
        self.assertIsNone(self.inv.get('R2'))
        self.assertIs(self.inv.get('R1'), r1)
        self.assertIs(self.inv.get('R3'), r3)


class InventoryAddTests(unittest.TestCase):
    """Covers section 2.2 of COVERAGE.md."""

    def setUp(self):
        self.greige = _make_greige()
        self.inv = TestInv(['plant', 'item_variant'])

    def test_correct_addition(self):
        """2.2.1: adds new items correctly"""
        r = _make_roll(self.greige, 'R1', 50.0, plant='FS', item_variant='V1')
        self.inv.add(r)
        # Flat map populated.
        self.assertIs(self.inv._items['R1'], r)
        # Each group bucketed and snapshotted under the correct attr value.
        plant_group = self.inv._groups['plant']
        self.assertIn(r, plant_group.mapping['FS'])
        self.assertEqual(plant_group.snapshots['R1'], 'FS')
        variant_group = self.inv._groups['item_variant']
        self.assertIn(r, variant_group.mapping['V1'])
        self.assertEqual(variant_group.snapshots['R1'], 'V1')

    def test_duplicate_id_raises(self):
        """2.2.2: raises ValueError on duplicate id; first-add state intact"""
        r = _make_roll(self.greige, 'R1', 50.0)
        self.inv.add(r)
        with self.assertRaises(ValueError) as cm:
            self.inv.add(r)
        self.assertIn('R1', str(cm.exception))
        # State from the successful first add is preserved.
        self.assertIs(self.inv._items['R1'], r)
        self.assertEqual(self.inv._groups['plant'].snapshots['R1'], 'FS')
        self.assertEqual(self.inv._groups['item_variant'].snapshots['R1'], 'V')

    def test_missing_attribute_raises(self):
        """2.2.3: raises ValueError when item is missing a key attribute"""
        inv = TestInv(['plant'])
        mat = TestMat('XX', self.greige, 50.0, None)
        with self.assertRaises(ValueError) as cm:
            inv.add(mat)
        self.assertIn('plant', str(cm.exception))
        # No partial state in _items or in the per-attribute group.
        self.assertNotIn('XX', inv._items)
        self.assertEqual(inv._groups['plant'].mapping, {})
        self.assertEqual(inv._groups['plant'].sorted_keys, [])
        self.assertEqual(inv._groups['plant'].snapshots, {})


class InventoryRemoveTests(unittest.TestCase):
    """Covers section 2.3 of COVERAGE.md."""

    def setUp(self):
        self.greige = _make_greige()
        self.inv = TestInv(['plant', 'item_variant'])

    def test_unknown_id_raises_key_error(self):
        """2.3.1: raises KeyError for an unknown id (empty and populated)"""
        with self.assertRaises(KeyError):
            self.inv.remove('NOPE')
        r = _make_roll(self.greige, 'R1', 50.0)
        self.inv.add(r)
        with self.assertRaises(KeyError):
            self.inv.remove('STILL_NOPE')

    def test_removes_and_returns(self):
        """2.3.2: removes and returns the targeted item, cleaning up groups"""
        r = _make_roll(self.greige, 'R1', 50.0, plant='FS', item_variant='V1')
        self.inv.add(r)
        removed = self.inv.remove('R1')
        self.assertIs(removed, r)
        self.assertNotIn('R1', self.inv._items)
        # Last item in each bucket → bucket and sorted-key entry are dropped.
        plant_group = self.inv._groups['plant']
        self.assertNotIn('FS', plant_group.mapping)
        self.assertEqual(plant_group.sorted_keys, [])
        self.assertNotIn('R1', plant_group.snapshots)
        variant_group = self.inv._groups['item_variant']
        self.assertNotIn('V1', variant_group.mapping)
        self.assertEqual(variant_group.sorted_keys, [])
        self.assertNotIn('R1', variant_group.snapshots)

    def test_mutation_raises_with_state_intact(self):
        """2.3.3: raises RuntimeError on mutation; inventory left untouched"""
        r = _make_roll(self.greige, 'R1', 50.0, plant='FS')
        self.inv.add(r)
        orig_items_keys = set(self.inv._items.keys())
        orig_plant_mapping = {
            k: set(v) for k, v in self.inv._groups['plant'].mapping.items()
        }
        orig_plant_keys = list(self.inv._groups['plant'].sorted_keys)
        orig_plant_snapshots = dict(self.inv._groups['plant'].snapshots)
        orig_var_mapping = {
            k: set(v)
            for k, v in self.inv._groups['item_variant'].mapping.items()
        }
        orig_var_keys = list(self.inv._groups['item_variant'].sorted_keys)
        orig_var_snapshots = dict(self.inv._groups['item_variant'].snapshots)
        r._plant = 'WF'
        with self.assertRaises(RuntimeError):
            self.inv.remove('R1')
        # _items unchanged.
        self.assertEqual(set(self.inv._items.keys()), orig_items_keys)
        self.assertIs(self.inv._items['R1'], r)
        # plant group unchanged.
        self.assertEqual(
            {k: set(v) for k, v in self.inv._groups['plant'].mapping.items()},
            orig_plant_mapping,
        )
        self.assertEqual(self.inv._groups['plant'].sorted_keys, orig_plant_keys)
        self.assertEqual(
            self.inv._groups['plant'].snapshots, orig_plant_snapshots,
        )
        # item_variant group unchanged.
        self.assertEqual(
            {
                k: set(v)
                for k, v in self.inv._groups['item_variant'].mapping.items()
            },
            orig_var_mapping,
        )
        self.assertEqual(
            self.inv._groups['item_variant'].sorted_keys, orig_var_keys,
        )
        self.assertEqual(
            self.inv._groups['item_variant'].snapshots, orig_var_snapshots,
        )


class InventoryGetGroupTests(unittest.TestCase):
    """Covers section 2.4 of COVERAGE.md."""

    def setUp(self):
        self.greige = _make_greige()
        self.inv = TestInv(['plant', 'qty', 'item_variant'])
        self.r1 = _make_roll(
            self.greige, 'R1', 25.0, plant='FS', item_variant='V1',
        )
        self.r2 = _make_roll(
            self.greige, 'R2', 50.0, plant='FS', item_variant='V2',
        )
        self.r3 = _make_roll(
            self.greige, 'R3', 75.0, plant='WF', item_variant='V1',
        )
        self.r4 = _make_roll(
            self.greige, 'R4', 100.0, plant='WF', item_variant='V2',
        )
        for r in (self.r1, self.r2, self.r3, self.r4):
            self.inv.add(r)

    # ---- 2.4.1 single-attribute equivalence ----

    def test_single_attribute_equivalence(self):
        """2.4.1: Inventory.get_group(attr=gk) == _groups[attr].get_group(gk)"""
        cases = [
            ('plant', GroupKey(operator.eq, 'FS')),
            ('plant', GroupKey(operator.ne, 'FS')),
            ('qty', GroupKey(operator.lt, 75.0)),
            ('qty', GroupKey(operator.ge, 50.0)),
            ('qty', GroupKey(in_range(), (25.0, 100.0))),
            ('item_variant', GroupKey(operator.eq, 'V1')),
        ]
        for attr, gk in cases:
            self.assertEqual(
                self.inv.get_group(**{attr: gk}),
                self.inv._groups[attr].get_group(gk),
                msg=f'mismatch for ({attr!r}, {gk!r})',
            )

    # ---- 2.4.2 empty-result cases ----

    def test_empty_inventory_returns_empty(self):
        """2.4.2: empty inventory returns empty for any kwargs"""
        empty = TestInv(['plant', 'qty', 'item_variant'])
        self.assertEqual(empty.get_group(plant='FS'), set())
        self.assertEqual(
            empty.get_group(qty=GroupKey(operator.lt, 100.0)), set(),
        )
        self.assertEqual(
            empty.get_group(plant='FS', qty=GroupKey(operator.lt, 100.0)),
            set(),
        )

    def test_single_pair_no_matches_returns_empty(self):
        """2.4.2: a single pair whose per-attribute set is empty returns empty"""
        self.assertEqual(
            self.inv.get_group(qty=GroupKey(operator.eq, 999.0)),
            set(),
        )

    def test_all_pairs_no_matches_returns_empty(self):
        """2.4.2: every per-attribute set empty → result empty"""
        self.assertEqual(
            self.inv.get_group(
                plant='ZZ',
                qty=GroupKey(operator.eq, 999.0),
            ),
            set(),
        )

    def test_single_empty_pair_in_mixed_returns_empty(self):
        """2.4.2: any one empty per-attribute set forces intersection to empty"""
        # plant='FS' matches {r1, r2}; qty == 999 matches {} → ∅.
        self.assertEqual(
            self.inv.get_group(
                plant='FS',
                qty=GroupKey(operator.eq, 999.0),
            ),
            set(),
        )

    def test_non_empty_pairs_with_empty_intersection(self):
        """2.4.2: every per-attribute set non-empty but intersection empty"""
        # plant='WF' → {r3, r4}; item_variant='V1' → {r1, r3};
        # qty == 25 → {r1}.  ({r3, r4} ∩ {r1, r3} ∩ {r1}) = ∅.
        self.assertEqual(
            self.inv.get_group(
                plant='WF',
                item_variant='V1',
                qty=GroupKey(operator.eq, 25.0),
            ),
            set(),
        )

    # ---- 2.4.3 basic non-empty cases ----

    def test_no_kwargs_returns_all_items(self):
        """2.4.3: get_group() with no kwargs returns every item"""
        self.assertEqual(
            self.inv.get_group(),
            {self.r1, self.r2, self.r3, self.r4},
        )

    def test_multiple_pairs_with_equal_per_attribute_sets(self):
        """2.4.3: when per-attribute sets are equal, intersection equals either"""
        # plant='FS' → {r1, r2}; qty < 75 → {r1, r2}; same set.
        result = self.inv.get_group(
            plant='FS',
            qty=GroupKey(operator.lt, 75.0),
        )
        self.assertEqual(result, {self.r1, self.r2})
        # Also matches the per-attribute set directly.
        self.assertEqual(
            result,
            self.inv._groups['plant'].get_group(
                GroupKey(operator.eq, 'FS'),
            ),
        )

    def test_multiple_pairs_with_differing_per_attribute_sets(self):
        """2.4.3: per-attribute sets differ; result is a proper subset of each"""
        # plant='FS' → {r1, r2}; item_variant='V1' → {r1, r3}; ∩ = {r1}.
        result = self.inv.get_group(plant='FS', item_variant='V1')
        self.assertEqual(result, {self.r1})
        # Each per-attribute set strictly contains the result.
        plant_set = self.inv._groups['plant'].get_group(
            GroupKey(operator.eq, 'FS'),
        )
        variant_set = self.inv._groups['item_variant'].get_group(
            GroupKey(operator.eq, 'V1'),
        )
        self.assertLess(result, plant_set)     # subset, not equal
        self.assertLess(result, variant_set)

    # ---- 2.4.4 modification flow ----

    def test_remove_modify_readd_moves_item_across_queries(self):
        """2.4.4: re-adding with a different plant moves item across plant queries"""
        # R2 starts at plant='FS'; queries reflect that.
        self.assertIn(self.r2, self.inv.get_group(plant='FS'))
        self.assertNotIn(self.r2, self.inv.get_group(plant='WF'))
        # Cycle: remove, mutate plant, re-add. Snapshot refreshes.
        self.inv.remove(self.r2.id)
        self.r2._plant = 'WF'
        self.inv.add(self.r2)
        # Now the queries flip for R2.
        self.assertNotIn(self.r2, self.inv.get_group(plant='FS'))
        self.assertIn(self.r2, self.inv.get_group(plant='WF'))

    def test_get_group_raises_on_mutated_item(self):
        """2.4.5: mutating a key attribute and querying that attribute raises"""
        # R2 has qty=50. Mutate directly so snapshot (50) != live (80).
        self.r2._qty = 80.0
        with self.assertRaises(RuntimeError) as cm:
            # qty == 50 still matches R2's snapshot bucket; verify fires
            # inside InvGroup.get_group, propagating up through Inventory.
            self.inv.get_group(qty=50.0)
        self.assertIn("'qty'", str(cm.exception))


if __name__ == '__main__':
    unittest.main()
