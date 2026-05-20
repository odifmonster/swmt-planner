# Specification of coverage of materials submodule

These tests target the `swmtplanner.materials` submodule.

## Section 1: product/

Since `Product` carries no stage-specific data on its own, these tests focus
on its concrete subclasses `BeamSet`, `Greige`, and `Fabric`.

### 1.1 BeamSet

A `BeamSet` is built from its SKU plus a safety target; all other attributes
are parsed from the SKU.

1. **construction works as expected** — basic SKU with no split-lease
   suffix (e.g., `"150D MICRO 50X4"`); verify `id`, `safety_tgt`, and every
   derived attribute
2. **SKU parsing covers every form**
    - basic `<denier>D <yarn> <ends>X<beams>` (no `S/L`): `is_split` is
      `False`
    - with `" S/L"` suffix: `is_split` is `True` and the other fields are
      unaffected
    - multi-word yarn description (e.g., `"100D FOO BAR 60X8"`):
      `yarn_desc` captures `"FOO BAR"` and the trailing dimensions still
      parse correctly
3. **invalid SKU raises `ValueError`** — e.g., `"not a valid sku"`

### 1.2 Greige

`Greige` takes all of its attributes as constructor inputs; there is no
SKU parsing.

1. **construction works as expected** — every attribute (`id`,
   `safety_tgt`, `family`, `gauge`, `top_bar`, `top_bar_pct`, `bottom_bar`,
   `bottom_bar_pct`, `roll_tgt_wt`) matches its constructor input
2. **`can_run_on_machine` reflects the `machine_rates` mapping**
    - returns `True` for IDs present in `machine_rates`
    - returns `False` for IDs not in `machine_rates`
3. **`rate_on_machine` returns the rate for compatible machines** —
   matches the value supplied in `machine_rates`
4. **`machine_rates` is copied at construction** — mutating the caller's
   mapping after construction does not affect `can_run_on_machine` or
   `rate_on_machine`

### 1.3 Fabric

`Fabric`'s `style`, `dye_formula`, and `width` are parsed from the SKU; the
remaining attributes are passed in.

1. **construction works as expected** — basic SKU
   `"FF <style>-<5-digit color>-<width>"`; verify every attribute
   (`id`, `safety_tgt`, `style`, `dye_formula`, `width`, `greige_style`,
   `yld`, `color_shade`)
2. **SKU parsing handles styles with dashes**
    - single-token style (e.g., `"FF 1234-12345-58.0"`)
    - style containing one dash (e.g., `"FF 1234-AB-12345-58.0"`)
    - style containing multiple dashes (e.g., `"FF A-B-C-99999-57"`)
    - `dye_formula` is always the 5-digit field; `width` is always the
      final field
3. **invalid SKU raises `ValueError`**
    - malformed prefix (missing `"FF "`)
    - color field that is not exactly 5 digits (e.g.,
      `"FF 1234-NAVY-58.0"`, `"FF 1234-9999-58.0"`)
    - missing width
4. **`can_run_on_jet` and `load_max_on_jet` reflect the `jet_load_max`
   mapping**
    - `can_run_on_jet` returns `True` for IDs in the mapping, `False`
      otherwise
    - `load_max_on_jet` returns the value supplied in `jet_load_max`
5. **`jet_load_max` is copied at construction** — mutating the caller's
   mapping after construction does not affect the `Fabric`

## Section 2: rawmat

`RawMat` itself is conceptually abstract; tests target `GreigeRoll` as its
only currently-defined subclass.

### 2.1 GreigeRoll instantiation

1. **construction works as expected** — every attribute (`id`, `product`,
   `qty`, `plant`, `item_variant`, `yarn_merge`) matches its constructor
   input, for both `avail_date=None` (already in inventory) and a
   non-`None` future date
2. **`size` is computed from `qty / product.roll_tgt_wt`** — for a Greige
   with `roll_tgt_wt = 100`, verify each `RollSize` bucket:
    - `qty = 30` → `'partial'`
    - `qty = 50` → `'half'`
    - `qty = 80` → `'small'`
    - `qty = 100` → `'full'`
    - `qty = 120` → `'large'`
3. **`size` bucket boundaries** — verify the strict/inclusive cutoffs in
   `_compute_roll_size` (for `roll_tgt_wt = 100`):
    - `qty = 39.99` → `'partial'`, `qty = 40` → `'half'`
    - `qty = 59.99` → `'half'`, `qty = 60` → `'small'`
    - `qty = 94.99` → `'small'`, `qty = 95` → `'full'`
    - `qty = 105` → `'full'`, `qty = 105.01` → `'large'`

### 2.2 split

1. **invalid split weights raise `ValueError`**
    - `lbs1 + lbs2 < self.qty`
    - `lbs1 + lbs2 > self.qty`
2. **new rolls' IDs follow the `A`/`B` suffix scheme** — given a roll
   with `id = "FS001"`, splitting produces rolls with `id = "FS001A"` and
   `id = "FS001B"`
3. **computed sizes of the resulting rolls** — for a `Greige` with
   `roll_tgt_wt = 100`, verify every listed split scenario:
    - split half (`qty = 50`) into `25 + 25`: both rolls are `'partial'`
    - split small (`qty = 70`) into `35 + 35`: both rolls are `'partial'`
    - split small (`qty = 90`) into `55 + 35`: one `'half'` and one
      `'partial'`
    - split full (`qty = 100`) into `50 + 50`: both rolls are `'half'`
    - split full (`qty = 100`) into `30 + 70`: one `'partial'` and one
      `'small'`
    - split large (`qty = 150`) into `75 + 75`: both rolls are `'small'`
    - split large (`qty = 140`) into `50 + 90`: one `'half'` and one
      `'small'`
    - split large (`qty = 130`) into `30 + 100`: one `'partial'` and one
      `'full'`

### 2.3 combine

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
   `roll_tgt_wt = 100`, verify every listed combine scenario:
    - partial (`qty = 30`) + partial (`qty = 20`) → `'half'` (50)
    - partial (`qty = 35`) + partial (`qty = 35`) → `'small'` (70)
    - partial (`qty = 30`) + half (`qty = 50`) → `'small'` (80)
    - half (`qty = 50`) + half (`qty = 50`) → `'full'` (100)
    - half (`qty = 50`) + small (`qty = 80`) → `'large'` (130)
    - small (`qty = 70`) + partial (`qty = 30`) → `'full'` (100)
    - small (`qty = 70`) + small (`qty = 80`) → `'large'` (150)
