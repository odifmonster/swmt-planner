# materials

Defines data structures for physical materials being consumed
throughout the supply chain, the logic for identifying which raw
materials are available and when, and the rules for converting raw
materials into finished goods at each production stage.

The product BOMs themselves (item types, attributes, BOM relationships)
live in [`product/`](../product/DESIGN.md) at the top level. The
`materials/` submodule consumes those types to describe physical
inventory and how it is selected, combined, and consumed.

This document lays out the structures and contents of the materials
submodule needed for phase 1 implementation of the planner, as well as
any intermediate improvements we might want to make between phases 1
and 2. As development progresses, this document will be modified to
reflect the current project phase.

## Structures

`RawMat` (under `rawmat/`) — abstract class for a consumable
quantity/unit of raw material. Implements
[`HasID[str]`](../support/hasid.pyi); the string ID is the
physical-inventory ID (distinct from `product.id`, the SKU).

```python
class RawMat(HasID[str]):
    product: Product
    qty: float
    avail_date: date | None  # None if already in inventory

    @property
    def id(self) -> str: ...
```

`GreigeRoll` (under `rawmat/`) — `RawMat` subclass for an individual
roll of greige fabric, adding the metadata needed by the dyeing-stage
lot grouping.

```python
RollSize = Literal['partial', 'half', 'small', 'full', 'large']

NEW_ROLL_PLACEHOLDER: str  # placeholder used by GreigeRoll.new_arrival

class GreigeRoll(RawMat):
    plant: str
    item_variant: str
    yarn_merge: str

    @property
    def size(self) -> RollSize: ...  # computed from qty / (2 * product.port_load_tgt)

    @classmethod
    def new_arrival(
        cls, plant: str, product: Greige, receive_date: date,
    ) -> GreigeRoll: ...

    def split(self, lbs1: float, lbs2: float) -> tuple[GreigeRoll, GreigeRoll]: ...
    def combine(self, roll: GreigeRoll) -> GreigeRoll: ...
```

`Inventory[T]` (under `inventory/`) and its subclasses — generic
container classes indexing `RawMat` instances by physical-inventory ID
and by a configurable set of key attributes. `GreigeInv` (subclass of
`Inventory[GreigeRoll]`) is the only concrete inventory currently
defined; it layers additional dye-stage methods — including
`get_dye_lot` and `get_dye_lots`, which assemble `DyeLot` records
from the cached compatibility pools — on top of the generic
interface. The `DyeLot` record itself is also defined under
`inventory/`. See [inventory/DESIGN.md](inventory/DESIGN.md) for the
full signatures and behavior spec.

## `rawmat/` - raw-material types

The `rawmat/` submodule defines `RawMat` (the abstract base for a
consumable quantity of raw material) and its concrete subclasses. The
classes here describe a physical unit of inventory — its ID, the
product it is an instance of, how much of it there is, when it
becomes available, and any stage-specific metadata needed to consume
it. They are passive data containers; selection, consumption, and
dye-cycle lot grouping logic all live in
[`inventory/`](#inventory---raw-goods-selection-and-consumption).

Layout. `RawMat` and each concrete subclass live in their own file
inside the submodule. The package re-exports every class (and the
public constants / type aliases tied to a given subclass) through
`rawmat/__init__.py`, so callers continue to write `from
swmtplanner.materials.rawmat import RawMat, GreigeRoll, ...`. Current
files:

- `rawmat/rawmat.py` — the abstract `RawMat` base class.
- `rawmat/greigeroll.py` — `GreigeRoll`, along with the
  `RollSize` literal alias, the `NEW_ROLL_PLACEHOLDER` constant, the
  size-bucket thresholds, and the per-plant ID counter and helper
  functions that are specific to greige rolls.

### RawMat

`RawMat` is an abstract base class that represents a consumable
quantity (or unit) of raw material available to the planner.

It exists as its own class — rather than being modeled as a simple
`(Product, float)` pair — because scheduling against physical inventory
introduces constraints and data that a bare quantity cannot express.
The key example: material that is not currently in physical inventory
but is expected to arrive on a known future date. Such material is
consumable, but only by jobs scheduled at or after its arrival date.
Modeling availability as a first-class attribute of the raw-material
object lets the planner reason about these constraints uniformly
without threading parallel data structures.

Subclasses extend `RawMat` with whatever additional metadata is needed
to enforce the constraints specific to consuming that material at its
downstream production stage.

Attributes:

- `id: str` — the physical-inventory ID of this material unit,
  supplied via the [`HasID[str]`](../support/hasid.pyi) protocol.
  Distinct from `product.id` (the SKU): inventory items of the same
  product carry different `RawMat` IDs.
- `product: Product` — the product this quantity is an instance of.
- `qty: float` — the consumable quantity (units depend on the
  product).
- `avail_date: date | None` — the date this material first becomes
  available. `None` means it is already in physical inventory and can
  be consumed immediately; a non-`None` value means the material is
  expected to arrive on that date and may only be assigned to jobs
  scheduled at or after it.

### GreigeRoll

`GreigeRoll` is a `RawMat` subclass representing a single roll of
greige fabric available for use as input to a dye cycle.

**ID prefix convention.** A `GreigeRoll`'s `id` (inherited from
`RawMat`) begins with a two-letter plant code: `"FS"` for rolls from
Fairystone, `"WF"` for rolls from Whiteville Fabrics.

Dye-cycle compatibility imposes constraints on which rolls may be
grouped together into a single cycle. The planner enforces two of
these constraints directly: rolls in one cycle must be of compatible
sizes and must come from the same knitting plant. Additional per-roll
metadata (item variant, yarn merge) is carried on the roll and
reported to the end user so they can make manual changes to the
resulting schedule if they wish, but the planner does not use it as a
matching criterion.

`GreigeRoll`'s fields, layered on top of the availability/quantity
information inherited from `RawMat`:

- `plant: str` — the knitting plant the roll came from. Used by the
  planner for dye-cycle matching.
- `item_variant: str` — the specific item variant of the roll.
  Reported to the end user only; not used by the planner for matching.
- `yarn_merge: str` — identifier of the yarn merge the roll was knit
  from. Reported to the end user only; not used by the planner for
  matching.
- `size: RollSize` — computed at construction from
  `qty / (2 * product.port_load_tgt)`. Discrete size bucket, one of
  `'partial' | 'half' | 'small' | 'full' | 'large'`. The reference
  denominator is `2 * port_load_tgt` (the two-port load) so that the
  `'half'` bucket corresponds to a 1-port load and `'full'`
  corresponds to a 2-port load. Reported for informational purposes;
  lot-building no longer uses this bucket directly — it works off the
  dye-standard ranges enforced by
  [`GreigeInv.transform_odd_rolls`](inventory/DESIGN.md#transform_odd_rolls).
  (Not a constructor parameter — see the implementation for current
  threshold values.)

Class methods:

- `new_arrival(plant, product, receive_date) -> GreigeRoll` — factory
  for a roll whose receipt has been scheduled but whose finer-grained
  metadata is not yet known. Used by the planner to model future
  arrivals. The returned roll has:
    - `id` auto-generated via the support module's
      `get_str_id_counter`, scoped per-plant so that each plant gets
      its own sequential numbering (e.g., `"FS00001"`, `"FS00002"`,
      `"WF00001"`);
    - `product` set to the supplied greige item;
    - `qty` set to `product.port_load_tgt * product.standard_size`
      (new rolls are assumed to arrive at the knitting target for the
      style). For the typical `standard_size` values of `1` and `2`,
      the computed `size` bucket lands in `'half'` and `'full'`
      respectively;
    - `avail_date` set to `receive_date`;
    - `plant` set as supplied;
    - `item_variant` and `yarn_merge` both set to the module-level
      placeholder constant `NEW_ROLL_PLACEHOLDER` (currently `'TBD'`),
      since neither is predictable in advance.

Operations:

- `split(lbs1: float, lbs2: float) -> tuple[GreigeRoll, GreigeRoll]` —
  splits a non-standard roll into two rolls of the given pound
  weights. Both new rolls inherit `product`, `avail_date`, `plant`,
  `item_variant`, and `yarn_merge` from this roll; their IDs are this
  roll's ID suffixed with `'A'` and `'B'` respectively. Raises
  `ValueError` if `lbs1 + lbs2` is not approximately equal to this
  roll's `qty`.
- `combine(roll: GreigeRoll) -> GreigeRoll` — combines this roll with
  another non-standard roll into a single combined roll. The combined
  roll's `id` is always the concatenation of the two source rolls'
  IDs (this roll first). `item_variant` and `yarn_merge` are
  concatenated only when the two source values differ; if both rolls
  share the same `item_variant` (or `yarn_merge`), that single value
  is kept on the combined roll. `qty` is the sum. `avail_date` is the
  later of the two (with `None` treated as already-available). Raises
  `ValueError` if the two rolls come from different plants or are
  instances of different greige items.

## `inventory/` - raw goods selection and consumption

The `inventory/` submodule houses the planning-side logic for tracking
and querying physical raw-goods inventory. Its core export is
`Inventory[T]`, a generic container parameterized by a `RawMat`
subclass. Each concrete inventory type for a given material is a
subclass of `Inventory[T]` that layers stage-specific convenience
methods on top of the generic container. Currently `GreigeInv`
(subclass of `Inventory[GreigeRoll]`) is the only concrete inventory
defined.

Motivation. As the planner builds schedules it needs to repeatedly
look up specific raw-material units by ID and pull groups of units
matching shared attributes (e.g., "all in-inventory rolls of greige
style X from plant FS"). A linear scan over the full pool on every
lookup is too slow, and threading parallel indices through the
planning code is error-prone. The `Inventory` class encapsulates the
indexing so callers can:

- Look up a specific unit by its physical-inventory ID in constant
  time during lot building.
- Retrieve groups of units matching attribute predicates efficiently,
  via a fixed set of attribute indices declared at construction.
- Insert and remove units as the schedule consumes inventory and new
  arrivals are added, with all indices kept in sync.

Contract on key attributes. The attributes used as grouping keys
(declared at construction) must be sortable and must not be mutated on
a `RawMat` instance after the instance has been added to the
inventory. This is a contract on the caller, not strictly enforced by
the type system; the implementation detects violations as early as
possible and raises rather than silently returning stale results.

See [inventory/DESIGN.md](inventory/DESIGN.md) for the full behavior
spec.

