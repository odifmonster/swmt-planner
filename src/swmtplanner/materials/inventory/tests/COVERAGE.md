# Specification of coverage of inventory submodule

These tests target the `swmtplanner.materials.inventory` submodule.

## Section 1: InvGroup

`InvGroup` indexes a set of `RawMat` instances by their value for a
single key attribute, keeps the distinct values sorted, and snapshots
each item's attribute value for mutation detection. These tests use
`qty` as the indexed attribute (since it varies easily across
`GreigeRoll`s) and `GreigeRoll` as the concrete `RawMat`.

### 1.1 Construction

1. **construction works as expected** — `InvGroup[GreigeRoll]('qty')`
   stores `attr_name = 'qty'`, an empty `sorted_keys` list, an empty
   `mapping` dict, and an empty `snapshots` dict.

### 1.2 add

1. **items with distinct attribute values land in different buckets**
   — adding rolls with `qty = 50.0`, `qty = 75.0`, `qty = 100.0`
   creates three single-element buckets in `mapping`, each keyed by
   the corresponding `qty` value. Each roll's `id` is recorded in
   `snapshots` with its `qty` value.
2. **items with the same attribute value share a bucket** — adding
   two rolls with `qty = 50.0` produces a single `mapping[50.0]`
   bucket containing both rolls, and `sorted_keys` carries `50.0`
   exactly once.
3. **`sorted_keys` stays sorted regardless of insertion order** —
   inserting rolls in `qty` order `75.0 → 25.0 → 100.0 → 50.0`
   yields `sorted_keys == [25.0, 50.0, 75.0, 100.0]`.
4. **re-adding an item with the same `id` snapshots the current
   value** — adding a roll, then constructing a new roll with the
   same `id` but a different `qty` and adding it (after removing the
   original from the group) updates the snapshot to the new value
   and places the new roll into the bucket for the new value.

### 1.3 remove

1. **basic removal** — `remove(item)` deletes the item from its
   `mapping` bucket and clears its entry from `snapshots`, without
   touching other items in the same bucket.
2. **removing the last item from a bucket drops the key** — when the
   removed item was the only occupant of `mapping[value]`, the entry
   is deleted from `mapping` and `value` is removed from
   `sorted_keys`; other keys in `sorted_keys` keep their order.
3. **removing one of several items in a bucket leaves the bucket
   intact** — when other items share the same `qty`, the key remains
   in `sorted_keys` and `mapping` still contains the bucket with the
   remaining items.

### 1.4 verify

1. **no-op when the item is not in the group** — `verify(item)` on a
   `GreigeRoll` that was never added returns without raising. (Use a
   freshly-constructed roll whose `id` is not in `snapshots`.)
2. **no-op when the item is present and unchanged** —
   `verify(item)` after `add(item)` (with no mutation in between)
   returns without raising.
3. **raises `RuntimeError` on mutation** — after `add(item)`,
   mutating `item._qty` (so `item.qty` no longer matches the
   snapshot) and calling `verify(item)` raises `RuntimeError`. The
   error message references the attribute name `'qty'` and the
   snapshot/current values.
4. **`remove` reports mutation before touching state** — after
   `add(item)` and mutating `item._qty`, calling `remove(item)`
   raises `RuntimeError`; the group's `mapping`, `sorted_keys`, and
   `snapshots` are unchanged when the error is raised.

### 1.5 get_group

1. **empty-result cases** — `get_group(gk)` returns `set()` for:
    - any `gk` when the group itself has no items.
    - `GroupKey(operator.eq, x)` when no item has `qty == x`.
    - `GroupKey(operator.lt, x)` when every item has `qty >= x`.
    - `GroupKey(in_range(), (x, y))` when every item has `qty < x`
      or `qty >= y` (i.e., nothing in `[x, y)` with the default
      `excl_hi=True`).
2. **basic non-empty cases** — populate the group once with items
   spanning `qty ∈ {25, 50, 75, 100}` and nothing added/removed
   afterward; verify:
    - `GroupKey(operator.eq, 50)` → `{r50}`
    - `GroupKey(operator.gt, 50)` → `{r75, r100}`
    - `GroupKey(operator.le, 50)` → `{r25, r50}`
    - `GroupKey(in_range(), (50, 100))` (default `[lo, hi)`) →
      `{r50, r75}`
3. **shrinks but stays non-empty after a remove** — populate with
   two rolls sharing `qty = 50` plus one with `qty = 75`. The eq-50
   result is the pair initially; removing one of them yields a
   size-1 set containing only the remaining one.
4. **becomes empty after removing the last matching item** —
   populate with one `qty = 50` roll and one `qty = 75` roll. The
   eq-50 result has one item initially; removing it yields the
   empty set.
5. **add grows the result set** — populate with two rolls at
   `qty = 25, 75`. The `gt 50` result is `{r75}`. Add a new roll
   with `qty = 100`; the same query now returns `{r75, r100}`.
6. **remove → modify → re-add moves an item across predicates** —
   add a roll with `qty = 50` (so it appears in `lt 60` results but
   not `gt 60`). Remove it, mutate its backing `_qty` to `80`, and
   re-add it. Now the `lt 60` result no longer contains it, and the
   `gt 60` result does.
7. **no-op modification keeps the item in the same predicates** —
   same flow but mutate `_qty` from `50` to `55`. Both the `lt 60`
   and `gt 60` results have the same membership for this item as
   they did before the cycle (still in `lt 60`, still out of
   `gt 60`).
8. **raises `RuntimeError` on a mutated item in a matched bucket** —
   add a roll with `qty = 50`, then mutate its `_qty` to `80`
   without going through remove/add. Calling
   `get_group(GroupKey(operator.eq, 50.0))` raises rather than
   returning the stale item, because the verification check runs
   on each item the result would include.

## Section 2: Inventory

`Inventory` is abstract; these tests exercise it through a minimal
concrete subclass:

```python
class TestInv(Inventory[GreigeRoll]):
    def new_group(self, **kwargs):
        return InvGroup[GreigeRoll](attr_name=kwargs['attr_name'])
```

The "missing attribute" error path additionally uses a bare `RawMat`
subclass with no extra fields:

```python
class TestMat(RawMat):
    pass  # inherits only id/product/qty/avail_date
```

Used to attempt insertion into a `TestInv` whose `key_attrs` include
something `TestMat` does not carry (e.g., `'plant'`).

### 2.1 get

1. **returns `None` for an unknown id** — `get('NOPE')` on an empty
   inventory and on a populated one (where `'NOPE'` is not among
   the inserted ids) both return `None`.
2. **returns the correct item for a known id** — after
   `add(r)`, `get(r.id)` returns the same instance (identity, not
   just equality).
3. **state tracking across add/remove sequences** — add three
   rolls; `get` returns each of them. Remove one; `get` for that
   id now returns `None`; `get` for the other two still returns
   the right instance.

### 2.2 add

1. **adds new items correctly** — after `add(r)`, `r.id` appears
   in `_items`, every per-attribute group has `r` in the bucket
   keyed by `getattr(r, attr)`, and every group's `snapshots`
   carries `r.id`.
2. **raises `ValueError` on duplicate `id`** — calling `add(r)`
   twice for the same instance raises `ValueError`; the error
   message references the duplicate id. The inventory's state
   from the first successful add is left untouched.
3. **raises `ValueError` when the item is missing a key
   attribute** — a `TestInv(['plant'])` rejects `add(TestMat(...))`
   because `TestMat` has no `plant` attribute; the error message
   references the missing attribute name. No partial state remains
   in `_items` or any group.

### 2.3 remove

1. **raises `KeyError` for an unknown id** — `remove('NOPE')` on
   both an empty inventory and a populated inventory (where the
   id is not present) raises `KeyError`.
2. **removes and returns the targeted item** — after `add(r)`,
   `remove(r.id)` returns the same instance, drops `r.id` from
   `_items`, and removes the item from every per-attribute group
   (including dropping the bucket and sorted-key entry when the
   group's bucket for that attribute value becomes empty).
3. **raises `RuntimeError` on mutation, leaving state untouched**
   — after `add(r)`, mutating one of `r`'s key attributes (e.g.,
   `r._plant = 'WF'` when the original was `'FS'`) and then
   calling `remove(r.id)` raises `RuntimeError`. The inventory's
   `_items` still contains `r.id`, and every group's `mapping`,
   `sorted_keys`, and `snapshots` are unchanged from before the
   failed `remove` call.

### 2.4 get_group

Throughout this subsection, set up the inventory with
`TestInv(['plant', 'qty', 'item_variant'])` populated with four
rolls covering the cross product:

| id   | plant | qty   | item_variant |
|------|-------|-------|--------------|
| `R1` | `FS`  | `25`  | `V1`         |
| `R2` | `FS`  | `50`  | `V2`         |
| `R3` | `WF`  | `75`  | `V1`         |
| `R4` | `WF`  | `100` | `V2`         |

1. **single-attribute equivalence** — for every `(attr, gk)` pair
   the high-level `inv.get_group(**{attr: gk})` equals the direct
   `inv._groups[attr].get_group(gk)`. Verify with at least three
   `GroupKey` shapes per attribute (e.g., `eq`, `lt`, `in_range`).
2. **empty-result cases** — `get_group(...)` returns the empty set
   in each of these scenarios:
    - empty inventory, any kwargs
    - single pair with no per-attribute matches
      (e.g., `qty=GroupKey(operator.eq, 999.0)`)
    - multiple pairs where *no* per-attribute set has matches
      (e.g., `plant='ZZ', qty=GroupKey(operator.eq, 999.0)`)
    - multiple pairs where one pair has no matches and the others
      do (`plant='FS', qty=GroupKey(operator.eq, 999.0)`) — the
      single empty per-attribute set forces the intersection to be
      empty
    - multiple pairs where every per-attribute set is non-empty but
      they fail to intersect
      (e.g., `plant='WF', item_variant='V2'` matches `{R4}` and
      `{R2, R4}` respectively → intersection `{R4}`; flip one to
      a non-intersecting combo like
      `plant='WF', item_variant='V1'` matching `{R3, R4}` and
      `{R1, R3}` → intersection `{R3}`; pick a triplet where the
      intersection is empty, e.g.,
      `plant='WF', item_variant='V1', qty=GroupKey(operator.eq, 25.0)`
      → `{R3, R4} ∩ {R1, R3} ∩ {R1}` = `∅`)
3. **basic non-empty cases**
    - `get_group()` (no kwargs) returns every item currently in the
      inventory.
    - multiple pairs with exactly equal per-attribute sets — the
      intersection equals either per-attribute set.
    - multiple pairs whose per-attribute sets differ — the
      intersection is a non-empty proper subset of each.
4. **modification flow** — pick a roll (`R2`), confirm it shows up
   in some queries and not others (e.g., `plant='FS'` includes it,
   `plant='WF'` does not). Remove it, mutate the backing
   `_plant` to `'WF'`, and re-add it. Now `plant='FS'` no longer
   includes it and `plant='WF'` does — verifying that re-adding
   refreshes the snapshot used by `get_group`.
5. **raises `RuntimeError` on a mutated item in a matched bucket**
   — mutate a key attribute of an in-inventory item directly
   (e.g., `r2._qty = 80.0`) without going through remove/add, then
   query that same attribute (`qty=50.0`). `Inventory.get_group`
   delegates to the per-attribute `InvGroup.get_group`, which runs
   the mutation-detection check and raises `RuntimeError`.
