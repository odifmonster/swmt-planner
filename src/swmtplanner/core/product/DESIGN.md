# product — Design

`core.product` owns the static product-style definitions used throughout
planning. It has two submodules:

- `greige` — greige (knitted, undyed) fabric styles.
- `fabric` — finished fabric styles.

## Overview

A product style is a static description of a product the mill can make: its
identity, target weights, and the bill-of-materials needed to produce it. Styles
are referenced by demand, inventory, and the planners; they do not themselves
hold any mutable planning state.

Both submodules are documented here (neither has its own `DESIGN.md`).

## Core objects

### `greige` submodule

No dedicated `DESIGN.md`; documented here.

- Constants: none.
- Functions:
  ```python
  def load_variant_translation(contents: str) -> None: ...
  def load_alt_translation(greiges: list[Greige]) -> None: ...
  def variant_to_master(variant: str) -> str | None: ...
  def alt_greige_to_greige(alt_greige: str) -> Greige | None: ...
  ```
- Classes:
  ```python
  @dataclass(frozen=True)
  class BeamConfig:
      beamset: str   # product SKU string of the beam set on this bar
      pct: float     # percent of the bar used per pound of knitted greige

  class Greige(HasID[str]):
      def __init__(self, id: str, tgt_wt: float, safety: float, pattern: str,
                   top: BeamConfig, bottom: BeamConfig,
                   alt_names: list[str]): ...
      @property
      def id(self) -> str: ...
      @property
      def tgt_wt(self) -> float: ...
      @property
      def safety(self) -> float: ...
      @property
      def pattern(self) -> str: ...
      @property
      def top(self) -> BeamConfig: ...
      @property
      def bottom(self) -> BeamConfig: ...
      @property
      def alt_names(self) -> tuple[str, ...]: ...
  ```

### `fabric` submodule

No dedicated `DESIGN.md`; documented here.

- Constants — shade ratings (integer constants, ordered lightest → darkest):
  ```python
  EXTRA_LIGHT: int
  LIGHT: int
  MEDIUM: int
  BLACK: int
  SD_BLACK: int
  ```
- Functions:
  ```python
  def load_ply1_translation(fabrics: list[Fabric]) -> None: ...
  def ply1_to_fabric(ply1: str) -> Fabric | None: ...
  ```
- Classes:
  ```python
  @dataclass(frozen=True)
  class Color:
      name: str
      number: int
      shade_rating: int
      def get_needed_strip(self, jet_state: 'JetState'): ...   # JetState + return TBD

  class Fabric(HasID[str]):
      def __init__(self, id: str, ply1_parts: tuple[str, ...], greige: str,
                   style: str, width: float, oz_sq_yd: float, yld_pct: float,
                   name: str, number: int, shade_rating: int,
                   jets: list[str]): ...
      @property
      def id(self) -> str: ...
      @property
      def ply1_parts(self) -> tuple[str, ...]: ...
      @property
      def greige(self) -> str: ...
      @property
      def style(self) -> str: ...
      @property
      def width(self) -> float: ...
      @property
      def color(self) -> Color: ...
      @property
      def yds_per_lb(self) -> float: ...
      def can_run_on_jet(self, jet: str) -> bool: ...
  ```

## `greige` submodule

Defines a greige (knitted, undyed) fabric style and the per-bar beam-set
configuration it knits from.

### `BeamConfig`

A frozen dataclass describing the beam set mounted on one bar (top or bottom) of
the knitting machine.

- `beamset` — the product SKU string for the beam set that goes on the given bar.
- `pct` — the float percent of the bar used per pound of knitted greige fabric.

### `Greige`

A greige fabric style. Implements the `HasID` protocol (keyed by its `id`). All
attributes are exposed as read-only properties.

- `id` — the style's unique identifier.
- `tgt_wt` — the expected weight, in pounds, of every roll of this greige style.
- `safety` — the target safety stock level, in pounds.
- `pattern` — a one-letter code representing the style's pattern "family".
- `top` — the `BeamConfig` for the top bar.
- `bottom` — the `BeamConfig` for the bottom bar.
- `alt_names` — the alternate (product-BOM) greige style names that condense into
  this knitting-plant style (see Translations below).

### Translations

The dyeing/finishing side and the knitting side name greige differently, and
inventory classifies it differently again. The module provides module-level
translation tables (populated by the `load_*` functions and queried by the
lookups). The two stages chain: an inventory **variant** maps to a **master**
(product-BOM) greige string, which in turn maps to a knitting-plant `Greige`.

- **Variant → master.** A greige "variant" is how greige rolls are classified in
  inventory; this differs from how the product BOMs name the greige fabric used
  to produce finished styles.
  - `load_variant_translation(contents)` — loads the variant→master mapping from
    the file contents, passed as a string (file opening is handled at the `app`
    layer). The contents are a list of JSON objects, each with the fields
    `variant` and `master`.
  - `variant_to_master(variant)` — returns the master (BOM) greige string for an
    inventory variant, or `None` if the variant is not in the table.
- **Alt greige → `Greige`.** A couple of the greige styles listed in the product
  BOMs can be condensed into one greige style defined in the knitting plant's
  system. Each `Greige` lists the BOM style names that condense into it in its
  `alt_names`.
  - `load_alt_translation(greiges)` — builds the alt-greige→`Greige` mapping from
    the `alt_names` of each `Greige`.
  - `alt_greige_to_greige(alt_greige)` — returns the knitting-plant `Greige` a
    product-BOM greige style maps to, or `None` if the style is not in the table.

## `fabric` submodule

Defines finished fabric styles and the colors they are dyed to.

### Shade rating constants

Integer constants naming the shade-rating levels, ordered from lightest to
darkest: `EXTRA_LIGHT`, `LIGHT`, `MEDIUM`, `BLACK`, `SD_BLACK`. A `Color`'s
`shade_rating` is one of these. Their specific integer values are intentionally
left undefined for now (they may change in the future).

### `Color`

A frozen dataclass describing a finished-fabric color.

- `name` — the color's name.
- `number` — the color's number.
- `shade_rating` — one of the shade-rating constants above.
- `get_needed_strip(jet_state)` — eventually accepts a `JetState`. *(The meaning
  of `JetState`, the full signature, and the return value are TBD.)*

### `Fabric`

A finished fabric product. Implements the `HasID` protocol (keyed by its `id`).
All attributes are exposed as read-only properties.

- `id` — the product's unique identifier.
- `ply1_parts` — a tuple of strings.
- `greige` — the greige style string.
- `style` — the style string.
- `width` — the fabric width.
- `color` — the `Color` this fabric is dyed to.
- `yds_per_lb` — the yards per pound.
- `can_run_on_jet(jet)` — whether the product can run on the given jet ID.

**Initialization.** `Fabric` is constructed with a value for each attribute
above, with two substitutions:

- Instead of `yds_per_lb`, it takes `oz_sq_yd` and `yld_pct`, which (with
  `width`, in inches) give the yards per pound:
  `yds_per_lb = 36 * 16 / (oz_sq_yd * width) * yld_pct`.
- Instead of a `color`, it takes all of `Color`'s attributes (`name`, `number`,
  `shade_rating`) and builds the `Color` internally.

It also takes a list of jet IDs the product can run on, which backs
`can_run_on_jet`.

### Translations

The ply1 part number is the name for a finished fabric style in the lamination
plant's system; some fabric styles have more than one associated ply1 part (held
in `Fabric.ply1_parts`). The module provides a module-level translation table
(populated by `load_ply1_translation` and queried by `ply1_to_fabric`).

- `load_ply1_translation(fabrics)` — builds the ply1-part→`Fabric` mapping from
  the `ply1_parts` of each `Fabric`.
- `ply1_to_fabric(ply1)` — returns the `Fabric` associated with a ply1 part, or
  `None` if the ply1 part is not in the table.
