# product — Design

`core.product` owns the static product-style definitions used throughout
planning. It has three submodules:

- `yarn` — yarns and the beam sets they are wound onto.
- `greige` — greige (knitted, undyed) fabric styles.
- `fabric` — finished fabric styles.

## Overview

A product style is a static description of a product the mill can make: its
identity, target weights, and the bill-of-materials needed to produce it. Styles
are referenced by demand, inventory, and the planners; they do not themselves
hold any mutable planning state.

`yarn` sits below `greige`: a `Greige` style is knitted from one to four
**bars**, and each bar is a beam set of a single yarn. `yarn` defines that yarn
and beam set; `greige` composes them into a style. `fabric` sits above both,
naming the greige style it is dyed from.

All three submodules are documented here (none has its own `DESIGN.md`).

The package also defines `Product`, a union type alias over the concrete style
classes, used as the generic bound for product-agnostic classes elsewhere (e.g.
in `core.demand`).

## Core objects

### Package level

Defined in the package `__init__` (it spans both submodules):

- Type aliases:
  ```python
  type Product = Fabric | Greige | BeamSetItem
  ```
  A union of the concrete product-style classes. `core.demand` uses it as the
  bound for its generic classes (`RlsItem[T: Product]`, etc.). The classes share
  no common interface, so this is a plain union alias rather than a base class —
  a conceptual constraint on what a product style can be.

  `BeamSetItem` is a member because the warping plant plans against it the same
  way the knitting plant plans against a `Greige`: beam sets are demanded,
  produced, and stocked. `Yarn` is deliberately **not** a member — it is an
  ingredient of a beam set, not something any plant plans production of.

### `yarn` submodule

No dedicated `DESIGN.md`; documented here. `Yarn` lives in `yarn.py`,
`BeamSetItem` in `beamsetitem.py`.

- Constants:
  ```python
  LUSTER_CODES: dict[str, str]     # luster name    -> id code
  MATERIAL_CODES: dict[str, str]   # material name  -> id code
  ATTR_CODES: dict[str, str]       # attribute name -> id code
  ```
- Functions: none.
- Classes:
  ```python
  class Yarn(HasID[str]):
      def __init__(self, denier: int, fill_ct: int, luster: str, material: str,
                   attributes: list[str]): ...
      @property
      def id(self) -> str: ...
      @property
      def denier(self) -> int: ...
      @property
      def fill_ct(self) -> int: ...
      @property
      def luster(self) -> str: ...
      @property
      def material(self) -> str: ...
      @property
      def attributes(self) -> tuple[str, ...]: ...

  class BeamSetItem(HasID[str]):
      def __init__(self, beams: int, ends: int, yarn: Yarn,
                   is_split: bool): ...
      @property
      def id(self) -> str: ...
      @property
      def beams(self) -> int: ...
      @property
      def ends(self) -> int: ...
      @property
      def yarn(self) -> Yarn: ...
      @property
      def is_split(self) -> bool: ...
  ```

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
  class BarConfig:
      bset: BeamSetItem   # the beam set mounted on this bar
      pct: float          # percent of the bar used per pound of knitted greige
      stitch: str         # the bar's stitch (lapping) notation
      thread: str         # the bar's threading notation

  class Greige(HasID[str]):
      def __init__(self, id: str, tgt_wt: float, safety: float, pattern: str,
                   bars: list[BarConfig], alt_names: list[str]): ...
      @property
      def id(self) -> str: ...
      @property
      def tgt_wt(self) -> float: ...
      @property
      def safety(self) -> float: ...
      @property
      def pattern(self) -> str: ...
      @property
      def n_bars(self) -> int: ...
      def bar(self, i: int) -> BarConfig: ...
      @property
      def alt_names(self) -> tuple[str, ...]: ...
  ```

### `fabric` submodule

No dedicated `DESIGN.md`; documented here.

- Constants — shade ratings (integer constants; the values are arbitrary
  identifiers):
  ```python
  EXTRA_LIGHT = 0
  LIGHT = 1
  MEDIUM = 2
  BLACK = 3
  SD_BLACK = 4
  ```
- Constants — jet activities (string constants naming the preparation cycles
  `Color.get_needed_strip` returns):
  ```python
  STRIP = 'STRIP'   # a cleaning / strip cycle
  EMPTY = 'EMPTY'   # an empty light cycle
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
      def get_needed_strip(self, state: 'JetState') -> list[str]: ...   # JetState defined later, in core/schedule

  class Fabric(HasID[str]):
      def __init__(self, id: str, ply1_parts: tuple[str, ...], greige: str,
                   style: str, width: float, oz_sq_yd: float, yld_pct: float,
                   name: str, number: int, shade_rating: int,
                   jets: dict[str, tuple[float, float]]): ...
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
      def load_range_on_jet(self, jet: str) -> tuple[float, float]: ...
  ```

## `yarn` submodule

Defines the yarns the mill knits with and the beam sets they are wound onto.
Both are static reference data: they carry no planning state.

### Code maps

Every component of a `Yarn.id` is a short code. The properties themselves hold
the readable long form; these module-level maps convert to the codes the id is
built from.

```python
LUSTER_CODES = {
    'Semi-Dull':           'SDL',
    'Solution Dyed Black': 'DBK',
    'Solution Dyed Grey':  'DGY',
}

MATERIAL_CODES = {
    'Polyester': 'POL',
}

ATTR_CODES = {
    'Cationic': 'CAT',
    'Repreve':  'REP',
    'Textured': 'TX',
}
```

Each map covers only what the mill currently knits; they are the extension point
as new yarns appear (nylon being the obvious next `MATERIAL_CODES` entry).

`LUSTER_CODES` conflates two things that are, for now, the same thing: how dull
the yarn is, and whether it was dyed before knitting. Every yarn the mill
currently knits is semi-dull, and the only alternative luster in use elsewhere is
bright — which comes in white only, so a future `'Bright': 'BRT'` entry would
slot in beside `'Semi-Dull'` without disturbing the dyed-colour entries. Should
a bright dyed yarn ever appear, luster and colour would have to split into two
properties; nothing in the current data forces that.

### `Yarn`

A single yarn. Implements the `HasID` protocol (keyed by its `id`). All
attributes are exposed as read-only properties; every one except `id` is
supplied at construction.

- `denier` — the yarn's denier as the vendor names it, **not** a measured value.
  Vendors disagree on this (the same yarn is sold as 70 or 75 denier), so the
  loader normalises before constructing: 70 becomes 75.
- `fill_ct` — the filament count. Also vendor-dependent and normalised by the
  loader: a 40-denier yarn is 24 filaments, a 75-denier yarn is 36.
- `luster` — the luster, long form, and where the yarn is dyed before knitting
  rather than left white, its colour comes with it: `'Semi-Dull'`,
  `'Solution Dyed Black'`, `'Solution Dyed Grey'`. Dull and semi-dim are folded
  into semi-dull by the loader; the dyed-colour distinction is preserved,
  because whether the yarn was dyed before knitting genuinely changes the style.
  See the note under Code maps on why luster and colour share one property.
- `material` — the fibre, long form, e.g. `'Polyester'`.
- `attributes` — the yarn's remaining attributes as a **sorted** tuple of long
  form names, e.g. `('Repreve', 'Textured')`. Empty when the yarn has none.
  Sorting makes the id deterministic regardless of the order the loader supplies
  them in.
- `id` — derived, not supplied. Structure:

  ```
  <denier>D<fill_ct>F-<luster code>-<material code>[-<attr codes, dash-joined>]
  ```

  Examples:

  ```
  75D36F-SDL-POL-TX        semi-dull textured polyester
  40D24F-SDL-POL-CAT       semi-dull cationic polyester
  75D36F-DBK-POL-TX        dyed-black textured polyester
  50D34F-SDL-POL-REP-TX    semi-dull textured Repreve polyester
  40D24F-SDL-POL           semi-dull polyester, no further attributes
  ```

  The attribute segment is omitted entirely — along with its leading dash — when
  `attributes` is empty, so an id never ends in a dash.

### `BeamSetItem`

The set of beams one bar of the knitting machine draws from. Implements the
`HasID` protocol (keyed by its `id`), and is one of the `Product` types: the
warping plant plans its production the way the knitting plant plans a `Greige`.

- `beams` — the number of beams in the set.
- `ends` — the total number of ends across the set.
- `yarn` — the `Yarn` wound on those beams.
- `is_split` — whether the set runs split lease. A split-lease set feeds **two**
  adjacent bars rather than one, each taking half the ends; both bars therefore
  reference the same set. This is what makes a style's bar count exceed the
  number of distinct beam sets.
- `id` — derived, not supplied. Structure:

  ```
  <yarn id> <ends>X<beams>[ S/L]
  ```

  The trailing ` S/L` appears only when `is_split`. Examples:

  ```
  75D36F-SDL-POL-TX 1172X4         the textured bar of a typical style
  40D24F-SDL-POL 1172X4 S/L        its split-lease pair, feeding two bars
  40D24F-DBK-POL 1172X4 S/L        the same, in dyed-black yarn
  ```

## `greige` submodule

Defines a greige (knitted, undyed) fabric style and the per-bar configuration it
knits from.

### `BarConfig`

A frozen dataclass describing one bar of the knitting machine. Replaces the old
`BeamConfig`, which could only express a two-bar (top/bottom) style with the
beam set held as an opaque SKU string.

- `bset` — the `BeamSetItem` mounted on this bar.
- `pct` — the float percent of the bar used per pound of knitted greige fabric.
- `stitch` — the bar's stitch (lapping) notation, e.g. `'1/0,2/3'`. Styles
  sharing a stitch set run the same pattern wheels.
- `thread` — the bar's threading notation, e.g. `'SOLID'` or `'1 IN, 1 OUT'`.

### `Greige`

A greige fabric style. Implements the `HasID` protocol (keyed by its `id`). All
attributes are exposed as read-only properties.

- `id` — the style's unique identifier.
- `tgt_wt` — the expected weight, in pounds, of every roll of this greige style.
- `safety` — the target safety stock level, in pounds.
- `pattern` — a one-letter code representing the style's pattern "family". It is
  a function of the style's stitch notations — two styles share a pattern letter
  exactly when their bars' stitches match — but it is stored rather than derived,
  for ease of reference.
- `n_bars` — the number of bars the style knits on, between 1 and 4.
- `bar(i)` — the `BarConfig` for bar `i`, numbered from 1 as the mill numbers
  them, so valid `i` runs `1..n_bars`. Raises `IndexError` otherwise. Bars are
  ordered as the machine mounts them, top to bottom; where a split-lease set
  feeds two bars, those two are adjacent and share one `BeamSetItem`.
- `alt_names` — the alternate (product-BOM) greige style names that condense into
  this knitting-plant style (see Translations below).

**Initialization.** `Greige` takes its bars as a `list[BarConfig]` in bar order;
`n_bars` and `bar(i)` read from it. The list is copied to a tuple internally, as
`alt_names` already is.

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

Integer constants naming the shade-rating levels: `EXTRA_LIGHT = 0`,
`LIGHT = 1`, `MEDIUM = 2`, `BLACK = 3`, `SD_BLACK = 4`. The numeric values are
arbitrary identifiers, **not** a darkness ordering — for darkness comparisons
the scale is `BLACK` > `SD_BLACK` > `MEDIUM` > `LIGHT` = `EXTRA_LIGHT` (see
`JetState` in `src/swmtplanner/core/schedule/DESIGN.md`). A `Color`'s
`shade_rating` is one of these.

### `Color`

A frozen dataclass describing a finished-fabric color.

- `name` — the color's name.
- `number` — the color's number.
- `shade_rating` — one of the shade-rating constants above.
- `get_needed_strip(state)` — given the current state of a jet, returns the list
  of preparation activities (the `STRIP` / `EMPTY` string constants, in run
  order) that must happen on that jet before this color can be dyed on it.
  Returns an empty list when the color can run next with no preparation. Detailed
  below.

#### The `JetState` it consumes

`get_needed_strip` takes a `JetState`, which is **not defined in this module** —
it comes later, alongside the `Jet` class in `core/schedule`. It is documented
here only as the interface this method relies on. For this method, a `JetState`
is guaranteed to expose at least:

- `cycles_since_strip: int` — the number of dye jobs run on the jet since its
  last strip/cleaning cycle. `0` means the last activity was a strip.
- `max_prev_shade: int | None` — the darkest shade still "present" on the jet,
  given as one of the shade-rating constants, or `None` when the jet is fully
  clean. The caller does **not** have to reconstruct any of the following; the
  jet maintains this state as activities are added to its schedule:
  - If a regular `BLACK` was dyed at any point in the current run, this is
    `BLACK` even if `SD_BLACK`s ran afterward; it is `SD_BLACK` only when
    solution-dyed black is the darkest shade and no regular black ran.
  - A single strip clears the jet to `None` for every shade **except** regular
    `BLACK`: clearing black takes a *double* strip. So after one strip following
    a black, `max_prev_shade` stays `BLACK` while `cycles_since_strip` is `0`
    (and it stays `BLACK` even if an `SD_BLACK` is then run on that single
    strip); only the second strip sets it to `None`. Consequently
    `max_prev_shade == BLACK` with `cycles_since_strip == 0` means exactly one of
    the two required strips has already run.

#### Shade tiers

For run-ordering purposes the five shade ratings collapse into three tiers,
lightest → darkest (this is the `tier(...)` used in the algorithm below):

- **light** — `EXTRA_LIGHT`, `LIGHT`
- **medium** — `MEDIUM`
- **black** — `BLACK`, `SD_BLACK`

#### Rules

Dyeing on a jet is constrained by:

1. **Cycle limit.** A jet runs at most 9 dye jobs between cleaning cycles, so a
   strip is required once `cycles_since_strip` reaches 9.
2. **Light-after-dark.** Colors run lightest → darkest within a cleaning cycle;
   running a color in a *lighter* tier than what has already run requires a strip
   first. (Within a tier — e.g. `BLACK` then `SD_BLACK`, or either order — no
   strip is needed.)
3. **Black double-strip.** Running any non-black color after a regular `BLACK`
   (`max_prev_shade == BLACK`) requires a *double* strip. A single strip suffices
   when the darkest prior shade was solution-dyed black (`max_prev_shade ==
   SD_BLACK`). Because the jet keeps `max_prev_shade == BLACK` after just one
   strip (with `cycles_since_strip == 0`), that first strip may already be done —
   in which case only the second strip is still outstanding.
4. **Extra-light priming.** An `EXTRA_LIGHT` color cannot run immediately after a
   strip; it may run only when the immediately preceding color was in the
   **light** tier. So if the jet is not already in that state — its
   `max_prev_shade` is not `LIGHT`/`EXTRA_LIGHT`, or any strip is being inserted
   ahead of it — an empty light cycle (`EMPTY`) must run immediately before it.

#### Algorithm

```python
def get_needed_strip(self, state):
    prev, nxt = state.max_prev_shade, self.shade_rating
    activities = []

    # (2)/(3) strips forced by running a lighter tier after a darker one
    n_strips = 0
    if prev is not None and tier(nxt) < tier(prev):
        if prev == BLACK:
            # (3) double strip after regular black, but one strip may already
            # have run (cycles_since_strip == 0) — then only the second remains
            n_strips = 1 if state.cycles_since_strip == 0 else 2
        else:
            n_strips = 1

    # (1) cycle limit forces at least one strip
    if state.cycles_since_strip >= 9:
        n_strips = max(n_strips, 1)

    activities += [STRIP] * n_strips

    # (4) extra light must be primed by a light cycle
    if nxt == EXTRA_LIGHT:
        already_light = n_strips == 0 and prev in (EXTRA_LIGHT, LIGHT)
        if not already_light:
            activities.append(EMPTY)

    return activities
```

where `tier(shade)` maps `EXTRA_LIGHT`/`LIGHT` → `0`, `MEDIUM` → `1`,
`BLACK`/`SD_BLACK` → `2`. Note that once we are in the lighter-tier branch,
`prev == BLACK` already implies `nxt` is a non-black color (any black `nxt` would
be the same tier, not lighter), so rule 3's condition collapses to the simple
`prev == BLACK` check shown.

#### Examples

- clean jet (`max_prev_shade is None`), run `MEDIUM` → `[]`
- `max_prev_shade == LIGHT`, run `MEDIUM` (darker) → `[]`
- `max_prev_shade == MEDIUM`, run `LIGHT` (lighter) → `[STRIP]`
- `max_prev_shade == SD_BLACK`, run `MEDIUM` → `[STRIP]`
- `max_prev_shade == BLACK` (`cycles_since_strip > 0`), run any non-black color →
  `[STRIP, STRIP]`
- `max_prev_shade == BLACK` with `cycles_since_strip == 0` (one strip already
  run), run any non-black color → `[STRIP]`
- `max_prev_shade == BLACK`, run `SD_BLACK` (same tier) → `[]`
- run `EXTRA_LIGHT` after a strip (`max_prev_shade is None`) → `[EMPTY]`
- `max_prev_shade == LIGHT`, run `EXTRA_LIGHT` → `[]`
- `max_prev_shade == MEDIUM`, run `EXTRA_LIGHT` → `[STRIP, EMPTY]`
- `max_prev_shade == BLACK` (`cycles_since_strip > 0`), run `EXTRA_LIGHT` →
  `[STRIP, STRIP, EMPTY]`
- `max_prev_shade == BLACK` with `cycles_since_strip == 0`, run `EXTRA_LIGHT` →
  `[STRIP, EMPTY]`
- any of the above additionally forces at least one `STRIP` when
  `cycles_since_strip >= 9`

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
- `load_range_on_jet(jet)` — the `(min, max)` load per port the given jet will
  accept for this fabric. Raises a `ValueError` if the jet cannot run this
  fabric.

**Initialization.** `Fabric` is constructed with a value for each attribute
above, with two substitutions:

- Instead of `yds_per_lb`, it takes `oz_sq_yd` and `yld_pct`, which (with
  `width`, in inches) give the yards per pound:
  `yds_per_lb = 36 * 16 / (oz_sq_yd * width) * yld_pct`.
- Instead of a `color`, it takes all of `Color`'s attributes (`name`, `number`,
  `shade_rating`) and builds the `Color` internally.

It also takes a `jets` dictionary mapping each jet ID the product can run on to
the `(min, max)` load per port that jet will accept for this fabric. This backs
both `can_run_on_jet` (a jet is runnable iff it is a key) and `load_range_on_jet`
(returns the mapped range, raising if the jet is not a key).

### Translations

The ply1 part number is the name for a finished fabric style in the lamination
plant's system; some fabric styles have more than one associated ply1 part (held
in `Fabric.ply1_parts`). The module provides a module-level translation table
(populated by `load_ply1_translation` and queried by `ply1_to_fabric`).

- `load_ply1_translation(fabrics)` — builds the ply1-part→`Fabric` mapping from
  the `ply1_parts` of each `Fabric`.
- `ply1_to_fabric(ply1)` — returns the `Fabric` associated with a ply1 part, or
  `None` if the ply1 part is not in the table.
