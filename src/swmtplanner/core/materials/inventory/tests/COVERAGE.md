# inventory — Test Coverage

Test coverage for the `core/materials/inventory/` submodule (`unittest`).

## Section 1 — `Condition`s

Construction stores the fields, and `to_func()` returns a predicate that behaves
as expected. Values under test are integers for simplicity. For the comparison /
range conditions, both the inclusive and exclusive variants are checked.

1. **`Exactly`** — construction; `to_func()` returns `True` for the equal value
   and `False` otherwise.
2. **`NotExactly`** — construction; `to_func()` returns `False` for the equal
   value and `True` otherwise.
3. **`Greater`** — construction; `to_func()` exclusive (`incl=False`) is `True`
   only strictly above `lo`; inclusive (`incl=True`) is also `True` at `lo`.
4. **`Less`** — construction; `to_func()` exclusive (`incl=False`) is `True` only
   strictly below `hi`; inclusive (`incl=True`) is also `True` at `hi`.
5. **`InRange`** — construction; `to_func()` with the default bounds
   (`incl_lo=True`, `incl_hi=False`) and with the inclusivity flipped, confirming
   the boundary behavior at both `lo` and `hi`.

## Section 2 — `ValGroup` and `SortedGroup`

Every test performs the same operations on both a `ValGroup` and a `SortedGroup`
(keyed / sorted on `avail_date`) and verifies the results are identical.

1. **Single object** — after adding one object, `get_group(Exactly(its
   avail_date))` returns a set containing only that object, and `get_group` on any
   other `avail_date` returns an empty set.
2. **Multiple values** — after adding several objects across multiple
   `avail_date`s, `get_group` returns the expected set for each added value.
3. **`remove` updates the group** — after `remove`, a subsequent `get_group`
   reflects the removal.
4. **`remove` unknown id** — calling `remove` with an id not in the group raises
   `KeyError`.
5. **`remove` wrong value** — calling `remove` with the wrong `avail_date` value
   for that object raises `KeyError`.
6. **`Greater` matches `Exactly` (single group)** — a `Greater` condition that
   includes exactly one `avail_date` in the group returns the same set as the
   `Exactly` version of that value.
7. **`Less` matches `Exactly` (single group)** — the same, using `Less`.
8. **Ranges over multiple groups** — `Greater`, `Less`, and `InRange` return the
   correct sets when they span multiple `avail_date`s.
9. **Empty ranges** — `Greater`, `Less`, and `InRange` return the empty set when
   their bounds exclude every `avail_date` in the group.

## Section 3 — `Inventory`

Tests use a `RawMat` subclass with a mutable `consumed_date: datetime` attribute.
The `Inventory` under test groups (value-based) on `sku` and `unit`, and sorts on
`qty`, `avail_date`, and `consumed_date`.

### 3.1 Empty inventory

1. Immediately after construction, `select_where` returns an empty result for any
   combination of conditions.

### 3.2 `add` / `remove`

1. `add` and `remove` correctly add and remove objects — verified by
   `select_where()` with no conditions reflecting the current contents.
2. `add` raises `ValueError` when adding an object whose `id` is already present.
3. `remove` raises `KeyError` when removing a non-existent `id`.
4. `remove` raises `KeyError` when the object's `consumed_date` is mutated after
   it was added and removal is then attempted (the broken-grouping guard).

### 3.3 `select_where` with conditions

The setup adds enough objects with the right property values to produce the
desired results.

1. For each condition type (`Exactly`, `NotExactly`, `Greater`, `Less`,
   `InRange`), a single condition returns the expected set — checked on one
   sorted attribute and one value-grouped attribute.
2. Two conditions with no overlapping matching objects return an empty result.
3. Multiple conditions return the correct intersection of objects:
   1. when each individual condition returns the same set of objects;
   2. when the conditions return different sets with a non-empty overlap.
4. Removing an object that is in a multi-condition result set and repeating the
   call excludes that object (confirming it was removed from all groups).
5. Adding an object that meets multiple conditions and repeating the call
   includes the new object in the result set.

## Section 4 — `GreigeGroup` and `GreigeInv`

### 4.1 `GreigeGroup`

`prepare_dye_pool` on a single style (all rolls share a `sku`), across several
configurations. A dye lot's ports must be within 10 lbs of one another and within
`[MIN_PORT_LBS, MAX_PORT_LBS]`, and (per the plant-split behavior) a lot cannot
mix plants.

1. **One dye lot** — rolls that share a `sku` and `plant`, are all eligible, and
   are within 10 lbs of one another all land in a single dye lot.
2. **Split by plant** — rolls that share a `sku` and are within 10 lbs of one
   another but belong to different plants are split into separate lots per plant.
3. **Split by weight** — rolls in the same plant whose `avg_port_wt` values spread
   beyond the 10-lb window are separated into multiple lots.
4. **Split by plant and weight** — rolls differing in both plant and weight are
   partitioned by both.
5. **Too-small excluded** — rolls whose `avg_port_wt` is below `MIN_PORT_LBS` are
   excluded from every lot.
6. **Cache invalidation** — `add` / `remove` on a style invalidates that style's
   cache: `has_cached_lots` returns `False` and `dye_lots` on that style raises.
7. **Shift after change** — removing the smallest standard-size roll of a style
   and then adding a new standard roll larger than the rest shifts the dye lots as
   expected (after calling `prepare_dye_pool` again).

### 4.2 `GreigeInv`

#### 4.2.1 `transform_rolls`

1. **Direct combinations (2 / 3 / 4 ports)** — an inventory of small and large
   rolls that combine (with no trimming) into standard 2-, 3-, and 4-port rolls;
   `transform_rolls` identifies and performs those combinations (the resulting
   standard rolls appear in the inventory).
2. **Exact-target trim** — combinations that need a small excess
   (`<= MAX_TRIM_LBS`) removed to hit the exact standard target weight;
   `transform_rolls` trims to target and combines.
3. **Full 30-lb trim** — combinations that need a full `MAX_TRIM_LBS` (30) lbs
   removed to land within the standard range (short of the exact target);
   `transform_rolls` trims 30 and combines.
4. **All results standard** — after a `transform_rolls` call, every roll produced
   by a combination is standard size.

#### 4.2.2 `create_roll`

1. **Properties** — the created roll's properties are what was passed in (`sku`,
   `avail_date`, `qty`, `plant`, `greige`), with `variant` equal to `sku`,
   `yarn_merge` of `-1`, and `unit` of `'lbs'`.
2. **Id built correctly** — the `id` is the plant prefix + `NEW-` + the counter
   value (e.g. `FSNEW-0`, `WVNEW-1`).
3. **Counter increments** — successive calls produce distinct ids via the
   incrementing counter.
