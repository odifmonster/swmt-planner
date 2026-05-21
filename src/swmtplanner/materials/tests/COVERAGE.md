# Specification of coverage of materials submodule

These tests target the `swmtplanner.materials` submodule.

## Section 1: rawmat

`RawMat` itself is conceptually abstract; tests target `GreigeRoll` as its
only currently-defined subclass.

### 1.1 GreigeRoll instantiation

1. **construction works as expected** — every attribute (`id`, `product`,
   `qty`, `plant`, `item_variant`, `yarn_merge`) matches its constructor
   input, for both `avail_date=None` (already in inventory) and a
   non-`None` future date
2. **`size` is computed from `qty / (2 * product.port_load_tgt)`** — for
   a Greige with `2 * port_load_tgt = 100` (i.e., `port_load_tgt = 50`,
   `standard_size = 2`), verify each `RollSize` bucket:
    - `qty = 30` → `'partial'`
    - `qty = 50` → `'half'`
    - `qty = 80` → `'small'`
    - `qty = 100` → `'full'`
    - `qty = 120` → `'large'`
3. **`size` bucket boundaries** — verify the strict/inclusive cutoffs in
   `_compute_roll_size` (for `2 * port_load_tgt = 100`):
    - `qty = 47.99` → `'partial'`, `qty = 48` → `'half'`
    - `qty = 51.99` → `'half'`, `qty = 52` → `'small'`
    - `qty = 97.99` → `'small'`, `qty = 98` → `'full'`
    - `qty = 102` → `'full'`, `qty = 102.01` → `'large'`

### 1.2 split

1. **invalid split weights raise `ValueError`**
    - `lbs1 + lbs2 < self.qty`
    - `lbs1 + lbs2 > self.qty`
2. **new rolls' IDs follow the `A`/`B` suffix scheme** — given a roll
   with `id = "FS001"`, splitting produces rolls with `id = "FS001A"` and
   `id = "FS001B"`
3. **computed sizes of the resulting rolls** — for a `Greige` with
   `2 * port_load_tgt = 100`, verify every listed split scenario:
    - split half (`qty = 50`) into `25 + 25`: both rolls are `'partial'`
    - split small (`qty = 70`) into `35 + 35`: both rolls are `'partial'`
    - split small (`qty = 90`) into `50 + 40`: one `'half'` and one
      `'partial'`
    - split full (`qty = 100`) into `50 + 50`: both rolls are `'half'`
    - split full (`qty = 100`) into `30 + 70`: one `'partial'` and one
      `'small'`
    - split large (`qty = 150`) into `75 + 75`: both rolls are `'small'`
    - split large (`qty = 140`) into `50 + 90`: one `'half'` and one
      `'small'`
    - split large (`qty = 130`) into `30 + 100`: one `'partial'` and one
      `'full'`

### 1.3 combine

1. **invalid combinations raise `ValueError`**
    - rolls from different plants
    - rolls of different greige items
2. **combined `id`, `item_variant`, and `yarn_merge`**
    - `id` is always the concatenation of the two source IDs (this roll
      first)
    - when both source `item_variant`s match (and likewise for
      `yarn_merge`), the combined roll keeps the single value
    - when the two source `item_variant`s differ (and likewise for
      `yarn_merge`), the combined roll concatenates them (this roll
      first)
3. **computed size of the combined roll** — for a `Greige` with
   `2 * port_load_tgt = 100`, verify every listed combine scenario:
    - partial (`qty = 30`) + partial (`qty = 20`) → `'half'` (50)
    - partial (`qty = 35`) + partial (`qty = 35`) → `'small'` (70)
    - partial (`qty = 30`) + half (`qty = 50`) → `'small'` (80)
    - half (`qty = 50`) + half (`qty = 50`) → `'full'` (100)
    - half (`qty = 50`) + small (`qty = 80`) → `'large'` (130)
    - small (`qty = 70`) + partial (`qty = 30`) → `'full'` (100)
    - small (`qty = 70`) + small (`qty = 80`) → `'large'` (150)

### 1.4 new_arrival (class method)

1. **attributes are populated correctly** — given plant `'FS'`, a Greige
   with `port_load_tgt = 50, standard_size = 2`, and a `receive_date`,
   the returned `GreigeRoll` has `product` set as supplied, `qty == 100`
   (knitting target = `port_load_tgt * standard_size`, so
   `size == 'full'`), `avail_date == receive_date`, `plant == 'FS'`,
   and `item_variant == yarn_merge == NEW_ROLL_PLACEHOLDER`
2. **`id` begins with the plant prefix** — calls with plant `'FS'`
   produce ids starting with `'FS'`; calls with `'WF'` produce ids
   starting with `'WF'`
3. **successive calls return distinct ids** — two consecutive calls with
   the same plant return different ids
4. **counters are independent across plants** — interleaving `'FS'` and
   `'WF'` calls does not cause id collisions between the two plants
