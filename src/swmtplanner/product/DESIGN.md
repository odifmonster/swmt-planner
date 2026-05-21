# product

Defines the abstract `Product` class used to generalize the shared
"what a job consumes or produces / what an order is asking for" concept
across [`materials/`](../materials/DESIGN.md),
[`schedule/`](../schedule/DESIGN.md), and
[`demand/`](../demand/DESIGN.md), so those modules can reason about
goods without knowing the specifics of any one production stage. The
`Product` subclasses describe what a unit of product is and how it is
built from upstream goods (its BOM); they do not track physical
inventory — that responsibility lives with `materials/`.

This document lays out the structures and contents of the product
submodule needed for phase 1 implementation of the planner, as well as
any intermediate improvements we might want to make between phases 1
and 2. As development progresses, this document will be modified to
reflect the current project phase.

## Structures

`Product` — abstract base for any item in the supply chain. Implements
[`HasID[str]`](../support/hasid.pyi); the string ID is the product SKU.

```python
class Product(HasID[str]):
    safety_tgt: float

    @property
    def id(self) -> str: ...  # SKU
```

`BeamSet`, `Greige`, `Fabric` — `Product` subclasses representing the
output of the warping, knitting, and dyeing stages respectively.
`Laminate` (output of the lamination stage) is out of scope for phase 1
and is not modeled yet.

```python
class BeamSet(Product):
    denier: int
    yarn_desc: str
    beam_count: int
    end_count: int
    is_split: bool

    def __init__(self, sku: str, safety_tgt: float) -> None: ...

class Greige(Product):
    family: str
    gauge: int
    top_bar: BeamSet
    top_bar_pct: float
    bottom_bar: BeamSet
    bottom_bar_pct: float
    port_load_tgt: float                    # target lb/port at dyeing
    standard_size: int                      # ports filled by a newly-knit roll (typically 1 or 2)

    def can_run_on_machine(self, mchn_id: str) -> bool: ...
    def rate_on_machine(self, mchn_id: str) -> float: ...  # lb/hr

class Fabric(Product):
    style: str
    dye_formula: str
    width: float
    greige_style: str
    yld: float               # yards produced per pound consumed
    color_shade: int         # 0-3
    omits_port: bool         # if True, lots use 2n-1 ports instead of 2n

    def can_run_on_jet(self, jet_id: str) -> bool: ...
```

A note on SKU conventions: each subclass's SKU follows a fixed format,
and the constructor parses the SKU to populate the derived attributes
listed below.

## Product

Abstract base class for every item the planner can reason about. Used
by [`materials/`](../materials/DESIGN.md) (raw-material consumption
rules), [`schedule/`](../schedule/DESIGN.md) (what a job produces or
consumes), and [`demand/`](../demand/DESIGN.md) (what an order is
asking for) so none of those modules has to special-case each
manufacturing stage's output type.

`Product` carries only two shared attributes:

- `id: str` — the product SKU, supplied via the
  [`HasID[str]`](../support/hasid.pyi) protocol. Used for equality and
  hashing.
- `safety_tgt: float` — the safety-stock target for this product. For
  items whose production process is not modeled by the planner, this is
  ignored.

Beyond these, `Product` does not prescribe any shared structure; it
exists mainly to generalize other data structures over arbitrary items.

## BeamSet

`Product` subclass for the output of the warping stage: a set of beams
intended to feed a knitting machine.

A `BeamSet` is initialized with its SKU and `safety_tgt`. All other
attributes are parsed from the SKU.

**SKU format:** `"<denier>D <yarn desc> <end count>X<beam count>"`,
optionally suffixed with `" S/L"` if the beam set runs split lease.
Examples: `"150D MICRO 50X4"`, `"100D POLY 60X8 S/L"`.

Derived attributes:

- `denier: int` — yarn denier.
- `yarn_desc: str` — yarn description.
- `end_count: int` — number of ends per beam.
- `beam_count: int` — number of beams in the set.
- `is_split: bool` — whether the beam set runs split lease (`True` iff
  the SKU ends in `" S/L"`).

## Greige

`Product` subclass for the output of the knitting stage: undyed
("greige") fabric.

Attributes:

- `family: str` — indicates which pattern wheels the style uses.
- `gauge: int` — knitting gauge.
- `top_bar: BeamSet` — beam set fed onto the top bar of the knitting
  machine.
- `top_bar_pct: float` — percent of the top-bar beam set consumed per
  pound of greige produced.
- `bottom_bar: BeamSet` — beam set fed onto the bottom bar.
- `bottom_bar_pct: float` — percent of the bottom-bar beam set consumed
  per pound of greige produced.
- `port_load_tgt: float` — target weight per port when loading this
  greige into a dye jet, in pounds. The per-port load target is a
  property of the greige style (not the fabric or the jet), so every
  dye-cycle constraint involving this greige reads the target here.
- `standard_size: int` — the number of dye-jet ports a single
  newly-knit roll of this style is sized to fill. Typically `1` or
  `2`: some styles are knit to 1-port size and dyed as-is; others
  are knit to 2-port size and split at the dyeing facility. The
  knitting-stage target weight is straightforwardly
  `port_load_tgt * standard_size`.

Operations:

- `can_run_on_machine(mchn_id: str) -> bool` — whether the knitting
  machine with the given ID can run this style.
- `rate_on_machine(mchn_id: str) -> float` — production rate of this
  style on the given machine, in pounds per hour.

## Fabric

`Product` subclass for the output of the dyeing stage: dyed and
finished fabric meeting a particular set of specifications. (The
lamination stage's output, `Laminate`, is a separate `Product` subclass
not yet in scope.)

**SKU format:** `"FF <style>-<dye formula>-<width>"`. Example:
`"FF 1234-AB-12345-58.0"`. The parser anchors on the last two
hyphen-separated fields: `dye_formula` is a 5-digit color number, and
`width` is the final numeric field (parsed as a float). Everything
between `"FF "` and the trailing `-<5 digits>-<width>` is taken as
`style`, which therefore may itself contain hyphens.

The color shade rating is **not** encoded in the SKU and must be
supplied to the constructor separately.

Attributes derived from the SKU:

- `style: str`
- `dye_formula: str`
- `width: float`

Additional attributes:

- `greige_style: str` — the greige style that this fabric is dyed from.
  Determines the per-port dye load target via `Greige.port_load_tgt`.
- `yld: float` — yield, in yards of fabric produced per pound of greige
  consumed.
- `color_shade: int` — color shade rating, an integer in `[0, 3]`.
- `omits_port: bool` — `True` for the small set of fabric items that
  intentionally leave one port on the dye jet empty during a cycle. A
  lot of size `n` for an `omits_port` item occupies `2n - 1` ports
  rather than the usual `2n`.

Operations:

- `can_run_on_jet(jet_id: str) -> bool` — whether the dye jet with the
  given ID can run this item. The fabric no longer carries a per-jet
  load target — the per-port target lives on the greige
  (`Greige.port_load_tgt`) — so the constructor takes a plain
  `Iterable[str]` of compatible jet IDs rather than a mapping.
