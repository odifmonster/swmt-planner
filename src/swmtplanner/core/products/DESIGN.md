# `swmtplanner.core.products`

Class structures equivalent to product bills of materials (BOMs), defined for
all products produced in the supply chain and all materials consumed.

## Overview

`products` is the product hierarchy of the supply chain. Each stage of
production consumes the output of the stage before it:

```
Yarn ──► BeamSet ──► Greige ──► Fabric ──► (laminated material, out of scope)
        (warping)   (knitting)  (dyeing)
```

The structures here carry the rules for what can be made from what: which
yarn makes up a beam set, which beam set a greige style is knit from and how,
and which greige and dye formula a finished fabric is made from. They do not
track quantities; that belongs to `core.materials`. Reading product
definitions in from external sources, and building the lookup tables that
find products by id, belongs to `swmtplanner.io`; `products` holds no
registries or lookup helpers of its own.

### Variants and master items

The plant's database defines a yarn item as a specific vendor merge. In
reality, many merges that share the same set of properties are
interchangeable. Because each merge is its own item in the system, every new
combination of yarn merges requires a new variant of each greige style that
uses them, so the database contains far more greige styles than are actually
distinct products.

The planner receives and fulfills demand on **master** items: a `Yarn` that
stands for every interchangeable merge, and a `Greige` that stands for every
variant of a style. A database variant (a merge, a greige variant) must
therefore be translated to its master item when it is read in. `products`
defines the rules for that translation; the readers in `swmtplanner.io`
apply them. For yarn, the translation is a deterministic function of the
merge's properties (see `Yarn.from_db_vals`); for greige, it is driven by a
list of master style names and their representative variants (see the
master style map).

### Capabilities

`products` introduces the following capabilities:

- **Yarn definitions** – master yarns identified by their interchangeable
  properties, the attributes that distinguish them, and vendor-specific
  merges of each.
- **Beam set definitions** – the yarn, beam count, and ends per beam that
  make up a beam set.
- **Greige definitions** – knitted greige styles and the bar and beam
  configuration used to knit them, plus the mapping from database variants
  to master styles.
- **Fabric definitions** – finished (dyed and finished) fabric, the dye
  formula used to produce it, and its shade.

All product classes are immutable value objects (frozen dataclasses) and
subclass the `HasID[T]` base class from `swmtplanner.support`. `HasID` uses
an object's `id` for equality and hashing, so two product objects of the
same class with the same id are the same product. As `HasID` requires, the
product dataclasses are declared with `eq=False` so the id-based equality is
not overridden. (`YarnAttrs`, `BarConfig`, and `BeamConfig` have no id and
use ordinary field-wise dataclass equality.)

## Core objects

`products` has no top-level constants, classes, or functions of its own. It
is composed of three submodules, described in this document:

| Submodule | Core objects                                                  |
|-----------|---------------------------------------------------------------|
| `beamset` | `YarnAttrs`, `Yarn`, `Merge`, `BeamSetDesc`                   |
| `greige`  | `BarConfig`, `BeamConfig`, `Greige`                           |
| `fabric`  | `Shade`, `DyeFormula`, `Fabric`                               |

### `beamset`

```python
@dataclass(frozen=True)
class YarnAttrs:
    textured: bool
    cationic: bool
    recycled: bool

    @classmethod
    def from_int(cls, code: int) -> YarnAttrs: ...
    @classmethod
    def from_desc(cls, desc: str) -> YarnAttrs: ...
    def __int__(self) -> int: ...

@dataclass(frozen=True)
class Yarn(HasID[str]):
    denier: int
    material: str      # "polyester" | "nylon" | "lycra" | "spandex" | "acetate" | "eptfe"
    color: str         # "white" | "black" | "grey"
    attrs: YarnAttrs

    @property
    def id(self) -> str: ...   # "<denier><material code><W/G/B><2-digit attribute code>"

    @classmethod
    def from_db_vals(cls, denier: int, luster: str, desc: str) -> Yarn: ...

@dataclass(frozen=True)
class Merge(HasID[str]):
    id: str            # vendor item code; no specific format
    yarn: Yarn
    vendor: str

@dataclass(frozen=True)
class BeamSetDesc(HasID[str]):
    id: str            # "<yarn id>-<end count>-<beam count>"
    yarn: Yarn
    beam_count: int
    end_count: int

    def split(self, n: int) -> list[BeamSetDesc]: ...
    @classmethod
    def merge(cls, *bsets: BeamSetDesc) -> BeamSetDesc: ...
```

### `greige`

```python
@dataclass(frozen=True)
class BarConfig:
    num: int           # bar number
    runlen: float      # runner length
    pct: float         # percent of the style's weight from this bar
    stitch: str        # stitch notation, e.g. "1/0,1/2"

@dataclass(frozen=True)
class BeamConfig:
    beamset: BeamSetDesc
    bars: tuple[BarConfig, ...]

    def can_use(self, bsets: list[BeamSetDesc]) -> bool: ...

@dataclass(frozen=True)
class Greige(HasID[str]):
    id: str            # master style name
    gauge: int         # needles per inch
    width: int         # inches
    rack_wt: float     # pounds per 100 racks
    std_wt: float      # standard roll weight, pounds
    beam_cfgs: tuple[BeamConfig, ...]
    _rates: dict[str, float]   # machine id -> lb/hr at 100% efficiency; private, not part of the public API

    @property
    def pattern(self) -> list[tuple[str, ...]]: ...
    @property
    def beamsets(self) -> list[tuple[str, tuple[int, ...]]]: ...

    def can_run_on_machine(self, mchn: str) -> bool: ...
    def get_rate_on_machine(self, mchn: str) -> float: ...
```

### `fabric`

```python
class Shade(Enum):
    LIGHT0 = ...
    LIGHT1 = ...
    MEDIUM = ...
    SD_BLACK = ...
    BLACK = ...

@dataclass(frozen=True)
class DyeFormula(HasID[int]):
    id: int            # dye formula number
    name: str
    shade: Shade

@dataclass(frozen=True)
class Fabric(HasID[str]):
    id: str            # item code: "FF <style name>-<dye formula number>-<finished width>"
    greige_style: Greige
    master_style: str
    color: DyeFormula
    width: float
    yld: float         # yards per pound
    jets: tuple[str, ...]   # ids of the jets that can run this fabric

    def can_run_on_jet(self, j_id: str) -> bool: ...
```

## `beamset`

### `YarnAttrs`

The additional attributes that distinguish otherwise-similar yarns. Yarns
that differ in any of these are not interchangeable.

| Field      | Type   | Description                                       |
|------------|--------|---------------------------------------------------|
| `textured` | `bool` | Whether the yarn is textured                      |
| `cationic` | `bool` | Whether the yarn is cationic                      |
| `recycled` | `bool` | Whether the yarn is recycled (also called Repreve) |

The initializer accepts a value for each field directly.

**Integer encoding.** The three fields are read as the bits of a binary
number in field order (`textured` is the most significant bit, `recycled`
the least), and the equivalent decimal number is the attribute code. The
order itself is arbitrary; it only needs to be consistent. Examples:

| `textured` | `cationic` | `recycled` | binary | code |
|------------|------------|------------|--------|------|
| False      | False      | False      | 000    | 0    |
| False      | False      | True       | 001    | 1    |
| True       | False      | False      | 100    | 4    |
| True       | False      | True       | 101    | 5    |

| Method                                  | Description                                   |
|-----------------------------------------|-----------------------------------------------|
| `__int__(self) -> int`                  | The attribute code for this set of attributes |
| `from_int(cls, code: int) -> YarnAttrs` | Inverse of `__int__`                          |
| `from_desc(cls, desc: str) -> YarnAttrs` | Parses the attributes from a database yarn description (the `desc` column) |

`from_desc` recognizes the following markers in the description
(case-insensitive, whole tokens):

| Attribute  | Markers                                 | Example descriptions                  |
|------------|-----------------------------------------|---------------------------------------|
| `textured` | `TEXT`, `TEX`, `TX`                     | `TEXT POLY`, `STR TEX POLY`, `RECYCLE TX P` |
| `cationic` | `CAT`                                   | `CAT POLY`, `CAT TX POLY`             |
| `recycled` | `REPREVE`, `REPR`, `RECYCLE`, `RECYCLED` | `REPREVE POLY`, `RECYCLED P`, `FR REPR TX P` |

### `Yarn`

`Yarn(HasID[str])` – an immutable master yarn. A `Yarn` stands for every
vendor merge that shares its properties; two merges that resolve to the same
`Yarn` are interchangeable.

| Field      | Type        | Description                                                  |
|------------|-------------|--------------------------------------------------------------|
| `denier`   | `int`       | Nominal denier as prescribed by the vendor (not a measurement); see normalization below |
| `material` | `str`       | One of `"polyester"`, `"nylon"`, `"lycra"`, `"spandex"`, `"acetate"`, `"eptfe"` |
| `color`    | `str`       | `"white"`, `"black"`, or `"grey"`                            |
| `attrs`    | `YarnAttrs` | Additional distinguishing attributes                         |

The initializer accepts a value for each field directly.

**Id.** `id` is derived from the fields as

```
<denier><material code><W/G/B><2-digit attribute code>
```

where the material code is a single letter from the table below, `W`/`G`/`B`
is the color (white/grey/black), and the attribute code is `int(attrs)`
zero-padded to two digits (two digits leaves room for more attributes
later). For example, a 75 denier textured white polyester is `75PW04`.

| Material      | Code |
|---------------|------|
| `"polyester"` | `P`  |
| `"nylon"`     | `N`  |
| `"lycra"`     | `L`  |
| `"spandex"`   | `S`  |
| `"acetate"`   | `A`  |
| `"eptfe"`     | `E`  |

**`from_db_vals(cls, denier: int, luster: str, desc: str) -> Yarn`** builds
a `Yarn` from the values stored on a database yarn item:

- **Denier.** Deniers of 70 and 75 are both treated as 75; all other deniers
  are kept as-is.
- **Color** is determined only by the `luster` column. The description
  column sometimes contains what looks like a color and must be ignored. For
  white yarn the luster is some version of dull, dim, semidull, or semidim
  (also abbreviated `D`, `SD`, `SD/D`, etc.). For non-white yarn the luster
  also contains a color abbreviation such as `BK` (black) or `GY` (grey).
  Anything without a color abbreviation maps to `"white"`; anything with one
  maps to the corresponding color. For now the only non-white colors are
  black and grey. Recognized abbreviations (case-insensitive substrings):

  | Color     | Abbreviations              | Example lusters                        |
  |-----------|----------------------------|----------------------------------------|
  | `"black"` | `BK`, `BLK`                | `SDBK`, `BLK`, `DBK`, `BKSD`, `OBBK`   |
  | `"grey"`  | `GY`, `GRY`, `GRAY`        | `SDGY`, `GRY`, `GRAY`, `DGY`, `BRGY`   |

- **Material** is determined by the `desc` column, by the first matching
  marker below. Markers are matched case-insensitively against the
  whitespace-separated tokens of the description, so that `POLY` does not
  match `POLYPRO` and a trailing `P` token is recognized as an abbreviation
  of polyester.

  | Material      | Markers (tokens)             | Example descriptions                       |
  |---------------|------------------------------|--------------------------------------------|
  | `"nylon"`     | starts with `NYL`            | `NYLON`, `TYPE 6 NYL`, `NYL TRI 6.6`, `NYLON/POLY` |
  | `"lycra"`     | `LYCRA`                      | `LYCRA`, `LYCRA T162B`                     |
  | `"spandex"`   | `SPANDEX`                    | `SPANDEX`                                  |
  | `"acetate"`   | `ACETATE`                    | `ACETATE`                                  |
  | `"eptfe"`     | `EPTFE`                      | `EPTFE`, `TWIST EPTFE`                     |
  | `"polyester"` | `POLY`, `POLYESTER`, `P`     | `POLY`, `POLYESTER`, `TEXT POLY`, `RECYCLE TX P`, `LOW MELT P` |

  A description that matches none of these (e.g. `POLYPRO`, `PTFE`,
  `FIBERGLASS`, `ELASTANE`, `DO NOT USE`) has no recognized material.
  `from_db_vals` raises `ValueError` in that case; it is the caller's
  responsibility (the readers in `swmtplanner.io`) to catch it, skip the
  item, and emit a warning naming the item and its description so the data
  can be checked. `from_db_vals` never guesses a material.

  Demand is currently only handled on polyester styles, but the material is
  tracked because one material cannot be used in place of another (e.g.
  nylon yarn cannot substitute for polyester). The non-polyester,
  non-nylon materials are accommodated for completeness and are not
  currently relevant.
- **Attributes** are parsed from `desc` with `YarnAttrs.from_desc`.

### `Merge`

`Merge(HasID[str])` – an immutable, vendor-specific merge of a yarn. A merge
is what the database calls a yarn item. Where `Yarn` identifies
interchangeable yarn regardless of source, `Merge` identifies a particular
vendor's version of it. Its `id` is the vendor's item code and has no
specific format.

| Field    | Type   | Description                     |
|----------|--------|---------------------------------|
| `yarn`   | `Yarn` | The master yarn this merge is of |
| `vendor` | `str`  | The vendor supplying this merge |

### `BeamSetDesc`

`BeamSetDesc(HasID[str])` – an immutable description of a beam set. Its
`id` is of the form

```
<yarn id>-<end count>-<beam count>
```

| Field        | Type   | Description                              |
|--------------|--------|------------------------------------------|
| `yarn`       | `Yarn` | The master yarn the beam set is warped from |
| `beam_count` | `int`  | The number of beams in the set           |
| `end_count`  | `int`  | The number of ends per beam              |

| Method                                            | Description |
|---------------------------------------------------|-------------|
| `split(self, n: int) -> list[BeamSetDesc]`        | Returns `n` new descriptions identical to this one except that `end_count` is divided evenly by `n`. Returns a single-element list for `n == 1`. Raises `ValueError` if `n < 1` or `end_count` is not divisible by `n`. |
| `merge(cls, *bsets: BeamSetDesc) -> BeamSetDesc`  | Combines the given descriptions into a single one by summing their `end_count`s. All inputs must be identical across the board (share an `id`); otherwise raises `ValueError`. Also raises `ValueError` when called with no arguments. |

`split` and `merge` are inverses: `BeamSetDesc.merge(*b.split(n)) == b`.
They exist so that a bar's total ends can be expressed either as one beam
set description or as several equal ones, as the knitting configuration
requires.

## `greige`

### What defines a style

A greige style is defined by:

- its gauge,
- its width,
- the beam sets it uses (yarn, beam count, and end count per bar),
- the stitch on each bar, and
- the runner length on each bar.

Two styles in the master list that differ only in their last letter (e.g.
`AU2958A` and `AU2958G`) generally differ only in runner length.

### Mapping variants to master styles

The system records many variants of what is really a single greige item.
The master style map (`greige-master-styles.json`) lists each master style
name together with one representative variant chosen for it. A database
variant is mapped to a master style by comparing its defining properties
against each master's representative variant:

1. **Exact match.** Prefer a master whose representative variant matches
   the variant exactly, including runner lengths.
2. **Near match on runner length.** Some variants within the same master
   style have slightly different runner lengths, usually to accommodate
   vendors whose actual denier tends to run over or under spec. If there is
   no exact match, accept a master whose representative variant matches on
   everything else and whose runner length on every bar is within 2 of the
   variant's runner length on that bar. If more than one master qualifies,
   pick the one with the smallest total runner length difference summed
   across all bars.
3. **No match.** Variants that match no master are assumed to be
   constructions no longer in use and are left unmapped.

When a variant maps to a master by a near match, the master's runner
lengths (those of its representative variant) are used, not the variant's.

`BarConfig` itself does no translating; it is simply passed its values. The
translation, along with the grouping of bars into `BeamConfig`s described
below, happens when styles are read in from the database by the readers in
`swmtplanner.io`.

### `BarConfig`

`BarConfig` – an immutable configuration of a single guide bar. Its values
are pulled largely directly from the database, with some formatting and
translation done by whatever constructs it (see above).

| Field    | Type    | Description                                              |
|----------|---------|----------------------------------------------------------|
| `num`    | `int`   | The bar number                                           |
| `runlen` | `float` | Runner length                                            |
| `pct`    | `float` | Percent of the style's weight contributed by this bar    |
| `stitch` | `str`   | Stitch notation for the bar, e.g. `"1/0,1/2"`            |

### `BeamConfig`

`BeamConfig` – an immutable description of how a style is beamed and
knit: the beam set it consumes and the configuration of each guide bar fed
from it.

| Field     | Type                       | Description                                     |
|-----------|----------------------------|-------------------------------------------------|
| `beamset` | `BeamSetDesc`              | The beam set description this configuration consumes, expressed as a single description covering all bars |
| `bars`    | `tuple[BarConfig, ...]`    | The configuration of each guide bar             |

| Method                                          | Description |
|-------------------------------------------------|-------------|
| `can_use(self, bsets: list[BeamSetDesc]) -> bool` | Whether beam sets matching the given descriptions can be used to knit this configuration |

`can_use` returns `True` if and only if one of the following holds:

1. `bsets` has exactly one element, and that element equals `self.beamset`;
   or
2. `bsets` has the same length as `self.bars`, and
   `BeamSetDesc.merge(*bsets)` equals `self.beamset`.

In every other case, including when `merge` would raise because the
descriptions are not identical, `can_use` returns `False`.

### How bars are grouped into `BeamConfig`s

The styles we deal with share a general construction. Multiplying the gauge
by the width gives approximately the number of needles per "row" of the
machine (usually a little more than the actual total). A style threads a
consistent number of needles in each row, but several guide bars are often
combined and fed into a single row. The bars in such a group share the same
yarn and the same number of ends, and the group's combined ends equal the
combined ends of every other bar group on the style.

Each `BeamConfig` in a `Greige` represents one of these bar groups, so it
may cover one or more guide bars on the machine. Its `beamset` is the
group's combined beam set description (the per-bar descriptions merged, so
`end_count` is the group's total ends per beam) and its `bars` are the
group's `BarConfig`s. Consequently:

- **Beam set placement.** `BeamConfig.can_use` accepts either one combined
  beam set split across all the bars in the group, or one separate beam set
  per bar.
- **Pattern wheels.** A "flipped" or "reversed" pattern uses the same
  pattern wheels, but the order of stitches *within* a group is not
  reversed. So two styles share pattern wheels when their `pattern`
  properties are equal, or equal after reversing the order of the groups.
- **Shared yarn.** Two styles share yarn when their `beamsets` properties
  are equal.

For example, a 28 gauge, 168 inch style with 4 beams has about 4,704
needles per row. If bars 1 and 2 each carry 586 ends of the same yarn and
bar 3 carries 1,172 ends, then bars 1 and 2 form one group (1,172 combined
ends) and bar 3 forms another, and both groups match the 1,172 ends per
beam × 4 beams ≈ 4,688 threaded needles per row.

### `Greige`

`Greige(HasID[str])` – an immutable greige style. Its `id` is a master
style name, drawn from the master style map.

| Field       | Type                       | Description                                  |
|-------------|----------------------------|----------------------------------------------|
| `gauge`     | `int`                      | Machine gauge, in needles per inch           |
| `width`     | `int`                      | Width, in inches                             |
| `rack_wt`   | `float`                    | Weight in pounds per 100 racks               |
| `std_wt`    | `float`                    | Standard weight of one roll of this style, in pounds |
| `beam_cfgs` | `tuple[BeamConfig, ...]`   | One `BeamConfig` per bar group (see above)   |

`Greige` is also initialized with a map of machine ids (`str`) to rates
(`float`). A rate is in pounds per hour at 100% running efficiency; actual
output is lower because machines stop for defects and errors, and the
planners must not assume full efficiency. This map is stored in a private
field and is not part of the public API; it is reached only through
`can_run_on_machine` and `get_rate_on_machine`.

| Property   | Type                                   | Description |
|------------|----------------------------------------|-------------|
| `pattern`  | `list[tuple[str, ...]]`                | One entry per `BeamConfig`, in order: the tuple of `stitch` strings of its bars |
| `beamsets` | `list[tuple[str, tuple[int, ...]]]`    | One entry per `BeamConfig`, in order: its `beamset.id` and the tuple of its bars' `num`s |

| Method                                           | Description |
|--------------------------------------------------|-------------|
| `can_run_on_machine(self, mchn: str) -> bool`    | Whether this style can be knit on the machine with id `mchn` (i.e. the machine has a rate in the private map) |
| `get_rate_on_machine(self, mchn: str) -> float`  | The rate for this style on machine `mchn`. Raises `KeyError` if the style cannot run on that machine |

### Master style map

The master style map is not an object in `products`; it is a data source
consumed by the readers in `swmtplanner.io` when building `Greige` objects.
Its source is `greige-master-styles.json`: a list of objects, one per
master style, each with

| Key          | Description                                                   |
|--------------|---------------------------------------------------------------|
| `master`     | The master style name (the `Greige.id`)                       |
| `variant`    | The representative variant chosen for this master             |
| `safety_tgt` | The master style's safety stock target. Not used when loading product data; it belongs to demand and inventory planning |

See "Mapping variants to master styles" above for how the map is used.

## `fabric`

### `Fabric`

`Fabric(HasID[str])` – an immutable finished fabric product.

Its `id` is the fabric's item code, of the form

```
FF <style name>-<dye formula number>-<finished width>
```

The relationship from greige style to fabric style name is one to many: a
single greige style is dyed and finished into many fabric styles.

| Field          | Type         | Description                                      |
|----------------|--------------|--------------------------------------------------|
| `greige_style` | `Greige`     | The greige style this fabric is made from        |
| `master_style` | `str`        | The master style name for this fabric            |
| `color`        | `DyeFormula` | The dye formula this fabric is dyed with         |
| `width`        | `float`      | Finished width                                   |
| `yld`          | `float`      | Yield, in yards per pound                        |
| `jets`         | `tuple[str, ...]` | The ids of all the jets that can run this fabric |

| Method                            | Description                                   |
|-----------------------------------|-----------------------------------------------|
| `can_run_on_jet(j_id: str) -> bool` | Whether this fabric can be dyed on the jet with id `j_id`, i.e. whether `j_id` is in `jets` |

### `DyeFormula`

`DyeFormula(HasID[int])` – an immutable dye formula.

Its `id` is the dye formula number (the same number that appears in the
fabric item code).

| Field   | Type    | Description                     |
|---------|---------|---------------------------------|
| `name`  | `str`   | The formula's name              |
| `shade` | `Shade` | The shade category of the formula |

### `Shade`

An enum of shade categories:

| Member     | Description                      |
|------------|----------------------------------|
| `LIGHT0`   | Light shades that cannot run immediately after a strip cycle |
| `LIGHT1`   | Light shades that can run immediately after a strip cycle |
| `MEDIUM`   | Medium shades                    |
| `SD_BLACK` | Solution-dyed black              |
| `BLACK`    | Black                            |

Shade categories exist to sequence dye lots on a jet. A lighter shade cannot
run after a darker shade without a strip cycle between them. Under that
rule, `LIGHT0` and `LIGHT1` are "the same" shade, as are `SD_BLACK` and
`BLACK`; the categories are split further because the number of strips
required differs within each pair. `LIGHT0` cannot run immediately after a
strip, and `BLACK` stains the jet more than solution-dyed black, so it
requires more strips after it. The exact sequencing and strip rules will be
detailed later, in the design for dye scheduling.
