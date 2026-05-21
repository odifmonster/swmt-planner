# Specification of coverage of product submodule

These tests target the `swmtplanner.product` submodule.

## Section 1: Product subclasses

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
   `bottom_bar_pct`, `port_load_tgt`, `standard_size`) matches its
   constructor input
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
   `yld`, `color_shade`, `omits_port`, `jets`). Also verify the
   `omits_port=True` path stores the flag correctly.
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
4. **`can_run_on_jet` reflects the `jets` set**, and the `jets`
   property exposes a `frozenset` of the supplied IDs (duplicates
   collapsed)
5. **input `jets` iterable is isolated at construction** — mutating
   the caller's iterable after construction does not affect the
   `Fabric`
