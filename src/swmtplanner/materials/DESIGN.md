# materials

Defines the data structures for all the products in the supply chain, the
logic for identifying which raw materials are available and when, and the
rules for converting raw materials into finished goods at each production
stage. Also defines the abstract `Product` class used to generalize the
shared "what a job consumes or produces / what an order is asking for"
concept across `schedule/` and `demand/`, so those modules can reason about
goods without knowing the specifics of any one production stage.

This document lays out the structures and contents of the materials submodule
needed for phase 1 implementation of the planner, as well as any intermediate
improvements we might want to make between phases 1 and 2. As development
progresses, this document will be modified to reflect the current project
phase.

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
output of the warping, knitting, and dyeing stages respectively. `Laminate`
(output of the lamination stage) is out of scope for phase 1 and is not
modeled yet.

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
    roll_tgt_wt: float    # target lb/roll

    def can_run_on_machine(self, mchn_id: str) -> bool: ...
    def rate_on_machine(self, mchn_id: str) -> float: ...  # lb/hr

class Fabric(Product):
    style: str
    dye_formula: str
    width: float
    greige_style: str
    yld: float            # yards produced per pound consumed
    color_shade: int      # 0-3

    def can_run_on_jet(self, jet_id: str) -> bool: ...
    def load_max_on_jet(self, jet_id: str) -> float: ...  # lb
```

`RawMat` — module-level abstract class for a consumable quantity/unit of raw
material. Distinct from a `(Product, float)` pair because it carries the
availability metadata needed when actually consuming material to build a
schedule. Implements [`HasID[str]`](../support/hasid.pyi) — physical
inventory items are indexed by their own string ID, distinct from the
product SKU.

```python
class RawMat(HasID[str]):
    product: Product
    qty: float
    avail_date: date | None  # None if already in inventory

    @property
    def id(self) -> str: ...  # physical-inventory ID
```

`GreigeRoll` — `RawMat` subclass representing an individual roll of greige
fabric. Adds the metadata needed to decide which rolls may be combined into a
single dye cycle.

```python
RollSize = Literal['partial', 'half', 'small', 'full', 'large']

class GreigeRoll(RawMat):
    plant: str
    item_variant: str
    yarn_merge: str

    @property
    def size(self) -> RollSize: ...  # computed from qty / product.roll_tgt_wt

    def split(self, lbs1: float, lbs2: float) -> tuple[GreigeRoll, GreigeRoll]: ...
    def combine(self, roll: GreigeRoll) -> GreigeRoll: ...
```

`DyeLot` (under `dyelot/`) — a grouping of compatible `GreigeRoll`s
assigned to produce a particular `Fabric` item. Lives in its own submodule
because it is specific to the dyeing process; it exists so that two fabric
items sharing a greige style and color (but differing in width) can be
dyed together in one cycle.

```python
class DyeLot:
    fabric: Fabric
    rolls: tuple[GreigeRoll, ...]

    @property
    def avail_date(self) -> date | None: ...

def get_dye_lot(
    item: Fabric,
    rolls: list[GreigeRoll],
    n: int,
    max_avail_date: date | None = None,
) -> DyeLot | None: ...

def get_dye_lots(
    item1: Fabric,
    item2: Fabric,
    rolls: list[GreigeRoll],
    n1: int,
    n2: int,
    max_avail_date: date | None = None,
) -> tuple[DyeLot, DyeLot] | None: ...
```

## `product/` - item BOMs

The `product/` submodule houses the `Product` hierarchy: the abstract base
plus one concrete subclass per stage's output. The classes here describe
*what* a unit of product is and *how* it is built from upstream goods (its
BOM). They do not track physical inventory — that responsibility lives with
`RawMat` and its subclasses.

A note on SKU conventions: each subclass's SKU follows a fixed format, and
the constructor parses the SKU to populate the derived attributes listed
below.

### Product

Abstract base class for every item the planner can reason about. Used by
`schedule/` (what a job produces or consumes) and `demand/` (what an order
is asking for) so neither module has to special-case each manufacturing
stage's output type.

`Product` carries only two shared attributes:

- `id: str` — the product SKU, supplied via the
  [`HasID[str]`](../support/hasid.pyi) protocol. Used for equality and
  hashing.
- `safety_tgt: float` — the safety-stock target for this product. For
  items whose production process is not modeled by the planner, this is
  ignored.

Beyond these, `Product` does not prescribe any shared structure; it exists
mainly to generalize other data structures (notably `schedule/` and
`demand/`) over arbitrary items.

### BeamSet

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
- `is_split: bool` — whether the beam set runs split lease (`True` iff the
  SKU ends in `" S/L"`).

### Greige

`Product` subclass for the output of the knitting stage: undyed ("greige")
fabric.

Attributes:

- `family: str` — indicates which pattern wheels the style uses.
- `gauge: int` — knitting gauge.
- `top_bar: BeamSet` — beam set fed onto the top bar of the knitting machine.
- `top_bar_pct: float` — percent of the top-bar beam set consumed per
  pound of greige produced.
- `bottom_bar: BeamSet` — beam set fed onto the bottom bar.
- `bottom_bar_pct: float` — percent of the bottom-bar beam set consumed
  per pound of greige produced.
- `roll_tgt_wt: float` — target weight per roll of this greige item, in
  pounds.

Operations:

- `can_run_on_machine(mchn_id: str) -> bool` — whether the knitting machine
  with the given ID can run this style.
- `rate_on_machine(mchn_id: str) -> float` — production rate of this style
  on the given machine, in pounds per hour.

### Fabric

`Product` subclass for the output of the dyeing stage: dyed and finished
fabric meeting a particular set of specifications. (The lamination stage's
output, `Laminate`, is a separate `Product` subclass not yet in scope.)

**SKU format:** `"FF <style>-<dye formula>-<width>"`. Example:
`"FF 1234-AB-12345-58.0"`. The parser anchors on the last two
hyphen-separated fields: `dye_formula` is a 5-digit color number, and
`width` is the final numeric field (parsed as a float). Everything
between `"FF "` and the trailing `-<5 digits>-<width>` is taken as
`style`, which therefore may itself contain hyphens.

The color shade rating is **not** encoded in the SKU and must be supplied
to the constructor separately.

Attributes derived from the SKU:

- `style: str`
- `dye_formula: str`
- `width: float`

Additional attributes:

- `greige_style: str` — the greige style that this fabric is dyed from.
- `yld: float` — yield, in yards of fabric produced per pound of greige
  consumed.
- `color_shade: int` — color shade rating, an integer in `[0, 3]`.

Operations:

- `can_run_on_jet(jet_id: str) -> bool` — whether the dye jet with the
  given ID can run this item.
- `load_max_on_jet(jet_id: str) -> float` — the maximum number of pounds
  that can be loaded into the named jet's ports to produce this item.

## RawMat

`RawMat` is an abstract, module-level class that represents a consumable
quantity (or unit) of raw material available to the planner.

It exists as its own class — rather than being modeled as a simple
`(Product, float)` pair — because scheduling against physical inventory
introduces constraints and data that a bare quantity cannot express. The
key example: material that is not currently in physical inventory but is
expected to arrive on a known future date. Such material is consumable, but
only by jobs scheduled at or after its arrival date. Modeling availability
as a first-class attribute of the raw-material object lets the planner
reason about these constraints uniformly without threading parallel
data structures.

Subclasses extend `RawMat` with whatever additional metadata is needed to
enforce the constraints specific to consuming that material at its
downstream production stage.

Attributes:

- `id: str` — the physical-inventory ID of this material unit, supplied via
  the [`HasID[str]`](../support/hasid.pyi) protocol. Distinct from
  `product.id` (the SKU): inventory items of the same product carry
  different `RawMat` IDs.
- `product: Product` — the product this quantity is an instance of.
- `qty: float` — the consumable quantity (units depend on the product).
- `avail_date: date | None` — the date this material first becomes
  available. `None` means it is already in physical inventory and can be
  consumed immediately; a non-`None` value means the material is expected
  to arrive on that date and may only be assigned to jobs scheduled at or
  after it.

### GreigeRoll

`GreigeRoll` is a `RawMat` subclass representing a single roll of greige
fabric available for use as input to a dye cycle.

**ID prefix convention.** A `GreigeRoll`'s `id` (inherited from `RawMat`)
begins with a two-letter plant code: `"FS"` for rolls from Fairystone,
`"WF"` for rolls from Whiteville Fabrics.

Dye-cycle compatibility imposes constraints on which rolls may be grouped
together into a single cycle. The planner enforces two of these constraints
directly: rolls in one cycle must be of compatible sizes and must come from
the same knitting plant. Additional per-roll metadata (item variant, yarn
merge) is carried on the roll and reported to the end user so they can make
manual changes to the resulting schedule if they wish, but the planner does
not use it as a matching criterion.

`GreigeRoll`'s fields, layered on top of the availability/quantity
information inherited from `RawMat`:

- `plant: str` — the knitting plant the roll came from. Used by the planner
  for dye-cycle matching.
- `item_variant: str` — the specific item variant of the roll. Reported to
  the end user only; not used by the planner for matching.
- `yarn_merge: str` — identifier of the yarn merge the roll was knit from.
  Reported to the end user only; not used by the planner for matching.
- `size: RollSize` — computed at construction from
  `qty / product.roll_tgt_wt`. Discrete size bucket, one of
  `'partial' | 'half' | 'small' | 'full' | 'large'`. Used by the planner
  for dye-cycle matching. (Not a constructor parameter — see the
  implementation for current threshold values.)

Operations:

- `split(lbs1: float, lbs2: float) -> tuple[GreigeRoll, GreigeRoll]` —
  splits a non-standard roll into two rolls of the given pound weights.
  Both new rolls inherit `product`, `avail_date`, `plant`,
  `item_variant`, and `yarn_merge` from this roll; their IDs are this
  roll's ID suffixed with `'A'` and `'B'` respectively. Raises
  `ValueError` if `lbs1 + lbs2` is not approximately equal to this
  roll's `qty`.
- `combine(roll: GreigeRoll) -> GreigeRoll` — combines this roll with
  another non-standard roll into a single combined roll. The combined
  roll's `id` is always the concatenation of the two source rolls' IDs
  (this roll first). `item_variant` and `yarn_merge` are concatenated
  only when the two source values differ; if both rolls share the same
  `item_variant` (or `yarn_merge`), that single value is kept on the
  combined roll. `qty` is the sum. `avail_date` is the later of the two
  (with `None` treated as already-available). Raises `ValueError` if
  the two rolls come from different plants or are instances of
  different greige items.

## `dyelot/` - dye-cycle lot grouping

The `dyelot/` submodule is specific to the dyeing process. It contains:

- The `DyeLot` class, which represents a group of greige rolls assigned to
  produce a specific `Fabric` item. Two fabric items that share a greige
  style and color but differ in width can be combined into a single dye
  lot, allowing them to be dyed together in one cycle.
- Utilities for combining compatible `GreigeRoll`s into lots, applying the
  matching constraints owned by `GreigeRoll` (plant and size).
- A function that attempts to assemble a single `DyeLot` of a requested
  size for a given `Fabric` item from a list of available rolls.
- A function that attempts to assemble two `DyeLot`s for different `Fabric`
  items that will share a single dye cycle.

### DyeLot

A `DyeLot` represents a group of greige rolls assigned to produce a
specific `Fabric` item.

- `fabric: Fabric` — the fabric item this lot will produce.
- `rolls: tuple[GreigeRoll, ...]` — the greige rolls assigned to this lot.
  All rolls in the tuple must satisfy the dye-cycle matching constraints
  defined by `GreigeRoll`.
- `avail_date: date | None` — computed property; the earliest date at
  which every roll in the lot is available. Equal to the latest
  `avail_date` among `rolls`, with `None` (already in inventory) treated
  as "available immediately." If every roll in the lot has
  `avail_date is None`, the lot's `avail_date` is also `None`.

_Additional fields/methods: TBD._

### Module-level functions

`get_dye_lot(item, rolls, n, max_avail_date=None) -> DyeLot | None` —
attempts to build a single `DyeLot` of size `n` that produces `item` from
the supplied `rolls`, applying the dye-cycle matching constraints owned
by `GreigeRoll` (plant and size) and using `GreigeRoll.split` /
`GreigeRoll.combine` as needed to assemble non-standard pieces into the
equivalent of `n` rolls.

Parameters:

- `item: Fabric` — the fabric item the assembled lot will produce. Becomes
  the `fabric` attribute of the returned `DyeLot`.
- `rolls: list[GreigeRoll]` — the pool of greige rolls available to draw
  from.
- `n: int` — the target lot size (number of full-roll equivalents).
- `max_avail_date: date | None = None` — optional upper bound on the
  lot's `avail_date`. If supplied, only rolls whose availability allows
  the resulting lot's `avail_date` to be at or before `max_avail_date`
  may be included. The default `None` imposes no upper bound.

Returns the assembled `DyeLot` on success, or `None` if no lot meeting
the requested constraints can be built from the input rolls.

`get_dye_lots(item1, item2, rolls, n1, n2, max_avail_date=None) ->
tuple[DyeLot, DyeLot] | None` — attempts to build two `DyeLot`s that will
share a single dye cycle but produce different `Fabric` items. The two
returned lots draw from the same `rolls` pool, share a knitting plant
(and compatible roll sizes) as required for a single cycle, and have
sizes `n1` and `n2` respectively.

Parameters:

- `item1: Fabric`, `item2: Fabric` — the two fabric items to be produced.
  Each becomes the `fabric` attribute of the corresponding returned lot.
- `rolls: list[GreigeRoll]` — the shared pool of greige rolls available
  to draw from. The two lots together consume from this one pool; no
  roll appears in both.
- `n1: int`, `n2: int` — target lot sizes for the first and second lots.
- `max_avail_date: date | None = None` — optional upper bound on each
  lot's `avail_date`, applied to both lots. The default `None` imposes
  no upper bound.

Returns the pair `(lot1, lot2)` on success, or `None` if no pair meeting
the requested constraints can be built from the input rolls.
