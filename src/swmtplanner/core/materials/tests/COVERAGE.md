# materials — Test Coverage

Test coverage for the `core/materials/` submodules (`unittest`).

## Section 1 — `rawmat`

### 1.1 `RawMat`

1. **Construction** — build a `RawMat` and verify all attributes are stored and
   exposed as read-only properties (`id`, `sku`, `avail_date`, `qty`, `unit`).
   (Trivial, included for completeness.)

## Section 2 — `GreigeRoll`

### 2.1 Construction and computed properties

1. **Basic construction** — build a `GreigeRoll` and confirm the non-computed
   properties are correct: `id`, `sku`, `avail_date`, `qty`, `unit` (always
   `'lbs'`), `plant`, `variant`, `yarn_merge`, `greige`.
2. **`single_target`** — confirm it is correct for:
   1. a `Greige` whose target is over 400 lbs (double-port → `target / 2`),
   2. a `Greige` whose target is 400 lbs or under (single-port → `target`),
   3. `greige is None` → the default (`DEFAULT_ROLL_WT`-based).
3. **Computed properties across the size/port matrix** — build rolls covering 1,
   2, 3, and 4 ports for each of the three sizes (`SMALL`, `STANDARD`, `LARGE`),
   and confirm `n_ports`, `avg_port_wt`, and `size` are all correct
   (`n_ports = max(1, round(qty / single_target))`, `avg_port_wt = qty /
   n_ports`).

### 2.2 `split`

1. **Invalid weights** — `split` raises when `lbs1 + lbs2` does not equal `qty`.
2. **New rolls** — `split` produces the correct `id` (parent id + `'A'` / `'B'`)
   and `qty` for the two new rolls, and all other properties are inherited from
   the parent.
3. **Recompute scenarios** — confirm `id`, `qty`, and the recomputed `n_ports` /
   `avg_port_wt` / `size` for:
   1. an unbalanced split that produces one roll with the same `n_ports` but a
      different `size`, plus one partial roll (less than one port's worth of
      fabric);
   2. a balanced split of a 2-port roll into two new rolls of the same size;
   3. an unbalanced split of a `LARGE` 2-port roll into one `LARGE` 1-port roll
      and one `STANDARD` 1-port roll.

### 2.3 `combine`

1. **Mismatched rolls** — `combine` raises when the two rolls differ in `sku` or
   `plant`.
2. **Variant** — the combined `variant` is correct: kept as-is when the two
   variants match, joined with `'/'` when they differ.
3. **Yarn merge** — the combined `yarn_merge` is kept when the two merges match
   and is `-1` when they differ.
4. **Result scenarios** — confirm the combined `id` (ids joined with `'/'`),
   `qty` (summed), and the recomputed `n_ports` / `avg_port_wt` / `size` for:
   1. two partials combining into one `STANDARD` 1-port roll;
   2. one `SMALL` and one `LARGE` roll combining into a `STANDARD` 4-port roll;
   3. two `LARGE` 1-port rolls combining into one `STANDARD` 3-port roll.

## Section 3 — `DyeLot`

### 3.1 Construction

1. **Empty list** — an empty list produces a `DyeLot` with the default values
   (`sku`/`plant`/`avail_date` `None`; `total_lbs`/`n_ports`/`avg_port_wt` `0`).
2. **Single element** — a single-roll list produces a `DyeLot` that shares all its
   attributes with that `GreigeRoll`.
3. **Mismatched rolls** — a multi-roll list with mismatched `plant`s or `sku`s
   raises.
4. **Identical rolls** — a multi-roll list of identical rolls produces a `DyeLot`
   whose properties match the individual rolls except for the aggregated
   `total_lbs` and `n_ports` (summed); `avg_port_wt` stays the rolls' value.
5. **Differing rolls** — a multi-roll list of differing (but compatible) rolls
   correctly computes the aggregate properties (`avail_date` = max, `total_lbs` =
   sum, `n_ports` = sum, `avg_port_wt` = `total_lbs / n_ports`).

### 3.2 `add` / `remove` / iteration

1. **Add to empty** — adding to an empty `DyeLot` sets its properties to the added
   roll's values.
2. **Add mismatched** — adding a roll with a mismatched `sku`/`plant` to a
   non-empty `DyeLot` raises.
3. **Add valid** — adding a valid roll to a non-empty `DyeLot` correctly updates
   the aggregate properties.
4. **Remove last** — removing the last roll returns all properties to their
   default values.
5. **Remove last then add different** — removing the last roll and then adding a
   roll with a different `plant`/`sku` changes the lot's `plant`/`sku`.
6. **Remove from many** — removing a roll from a `DyeLot` with at least 2 rolls
   correctly updates the aggregate properties.
7. **Removed roll returned** — the correct roll is returned on removal.
8. **Iteration** — a few scenarios confirming `add` / `remove` have the desired
   effect on `__iter__`.
