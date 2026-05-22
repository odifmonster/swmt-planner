# inventory

Generic container for raw-goods inventories. `Inventory[T]` indexes
`RawMat` instances by their physical-inventory ID and by a
configurable set of attribute keys (e.g., plant, product, item
variant). It exposes operations for inserting, removing, and looking
up individual items and groups of items matching attribute predicates.

Subclasses for specific material types add stage-specific convenience
methods on top of the generic container. Currently `GreigeInv`
(subclass of `Inventory[GreigeRoll]`) is the only one defined.

This document lays out the structures and contents of the inventory
submodule needed for phase 1 implementation of the planner, as well as
any intermediate improvements we might want to make between phases 1
and 2. As development progresses, this document will be modified to
reflect the current project phase.

## Structures

`GroupKey` — a value plus a comparison operator. Used as the keyword
payload to `Inventory.get_group` to describe a per-attribute predicate.

```python
@dataclass(frozen=True)
class GroupKey:
    op: Callable[[Any, Any], bool]
    value: Any

    def __call__(self, val: Any) -> bool: ...
```

`InvGroup[T]` — per-attribute index used by `Inventory`. Knows the
attribute name it indexes, snapshots each item's value for that
attribute at insertion, and is responsible for detecting subsequent
mutations of that attribute on items it holds. Concrete inventories
may subclass it to plug in extra behavior.

```python
class InvGroup[T: RawMat]:
    attr_name: str
    sorted_keys: list[Any]
    mapping: dict[Any, set[T]]
    snapshots: dict[str, Any]

    def __init__(self, attr_name: str) -> None: ...
    def add(self, item: T) -> None: ...
    def remove(self, item: T) -> None: ...
    def verify(self, item: T) -> None: ...
    def get_group(self, group_key: GroupKey) -> set[T]: ...
```

`Inventory[T]` — abstract generic container indexing `RawMat`
instances by physical-inventory ID and by a fixed set of attribute
keys. Concrete subclasses must implement `new_group` to choose the
`InvGroup` variant used for each per-attribute index.

```python
class Inventory[T: RawMat](ABC):
    def __init__(self, key_attrs: Iterable[str], **kwargs: Any) -> None: ...

    @abstractmethod
    def new_group(self, **kwargs: Any) -> InvGroup[T]: ...

    def get(self, id_: str) -> T | None: ...
    def add(self, x: T) -> None: ...
    def remove(self, id_: str) -> T: ...
    def get_group(self, **kwargs: GroupKey | Any) -> set[T]: ...
```

`GRollView` — immutable, frozen-dataclass view over a `GreigeRoll`,
carrying the same public attributes as its source. Returned by
`GreigeInv` query methods so callers can pass, store, and compare
inventory snapshots without risking mutation of inventory-resident
rolls.

```python
@dataclass(frozen=True)
class GRollView:
    id: str
    product: Greige
    qty: float
    avail_date: date | None
    plant: str
    item_variant: str
    yarn_merge: str
    size: RollSize
```

`DyeLot` — frozen record representing a group of compatible
`GRollView`s assigned to produce a specific `Fabric` item. The lot
references its rolls by immutable view so a single set of rolls can
appear in multiple candidate lots simultaneously without conflict;
the actual extraction from inventory happens later via
`GreigeInv.remove` when the planner commits a lot.

```python
@dataclass(frozen=True)
class DyeLot:
    fabric: Fabric
    rolls: tuple[GRollView, ...]

    @property
    def avail_date(self) -> date | None: ...
```

`GreigeInv` — `Inventory[GreigeRoll]` subclass adding the dye-stage
pre-processing, lot-pool retrieval, and lot-construction methods on
top of the generic inventory interface.

```python
class GreigeInv(Inventory[GreigeRoll]):
    def transform_odd_rolls(self) -> None: ...
    def prepare_dye_pools(self) -> None: ...
    def lot_groups(self, item_id: str) -> list[tuple[GRollView, ...]]: ...

    def get_dye_lot(
        self,
        item: Fabric,
        jet_id: str,
        n: int,
        pool: tuple[GRollView, ...],
        max_avail_date: date | None = None,
    ) -> DyeLot | None: ...

    def get_dye_lots(
        self,
        item1: Fabric,
        item2: Fabric,
        jet_id: str,
        n1: int,
        n2: int,
        pool: tuple[GRollView, ...],
        max_avail_date: date | None = None,
    ) -> tuple[DyeLot, DyeLot] | None: ...
```

## GroupKey

A `GroupKey` packages the right-hand side of an attribute comparison:
the operator to apply and the value to compare against. `op` is a
two-argument callable returning `bool` (e.g., the functions from the
`operator` module: `operator.lt`, `operator.le`, `operator.eq`,
`operator.ne`, `operator.ge`, `operator.gt`).

Constructor order is `GroupKey(op, value)`, chosen so callers can
write predicates that read naturally left-to-right: for example,
`GroupKey(operator.lt, 50)` reads as "less than 50", and
`GroupKey(in_range(), (25, 75))` reads as "in the range [25, 75)".

Semantics. For an item `x` with attribute value `x.attr`, the
predicate represented by `GroupKey(op, value)` is `op(x.attr, value)`
— that is, the inventory item's attribute is the **left** operand and
the `GroupKey.value` is the **right** operand. Predicates are
evaluated by **calling** the `GroupKey` directly: if `g` is a
`GroupKey` representing predicate $G$ (defined on some attribute
`attr`) and `x.attr` has the value $a$, then `g(x.attr)` is
equivalent to $G(a)$. For example, `equals_5 = GroupKey(operator.eq,
5)` is then used as `equals_5(x.attr)`.

## InvGroup

`InvGroup` is the per-attribute index `Inventory` keeps for each
declared key attribute. It owns three concerns:

1. Bucketing items by their value for `attr_name`.
2. Keeping the distinct attribute values sorted so range queries
   can use `bisect`.
3. Detecting mutations of `attr_name` on items it holds.

State:

- `attr_name: str` — the name of the attribute this group indexes.
  Set at construction; the group reads `getattr(item, attr_name)`
  on every `add`.
- `sorted_keys: list[Any]` — the distinct attribute values seen so
  far, kept in ascending order so range queries can be answered via
  `bisect`.
- `mapping: dict[Any, set[T]]` — for each attribute value present
  in `sorted_keys`, the set of items whose value for `attr_name`
  equals that value.
- `snapshots: dict[str, Any]` — for every item currently in the
  group, the value of `attr_name` captured at the moment the item
  was added. Used for mutation detection.

Operations:

- `add(item) -> None` — read `val = getattr(item, attr_name)`,
  insert `item` into `mapping[val]` (creating the bucket and
  inserting `val` into `sorted_keys` via `bisect.insort` on first
  sight), and record `snapshots[item.id] = val`.
- `verify(item) -> None` — raise `RuntimeError` if
  `getattr(item, attr_name)` no longer matches
  `snapshots[item.id]`. No-op if `item.id` is not currently in
  `snapshots` (the item isn't in this group).
- `remove(item) -> None` — call `verify(item)` first (so a mutation
  is reported before any state changes), then remove `item` from
  the bucket identified by its snapshot value, dropping the bucket
  and the key from `sorted_keys` if the bucket becomes empty, and
  clear `snapshots[item.id]`.
- `get_group(group_key) -> set[T]` — return the set of items whose
  value for `attr_name` satisfies the predicate represented by
  `group_key`. Walks `sorted_keys` and unions the buckets whose
  key satisfies `group_key(...)` (calling the `GroupKey` directly);
  the membership test runs once per distinct attribute value, not
  once per item. Each item that would join the result is passed
  through `verify` first — a mutated item in a matched bucket
  raises `RuntimeError` rather than being returned with stale data.

`InvGroup` is exposed publicly so concrete `Inventory` subclasses
can construct their per-attribute indices from custom `InvGroup`
subclasses — for example, a greige inventory that wants to attach
extra per-bucket metadata, override how `add` / `remove` behave for
a particular attribute, or extend the mutation-detection check
itself.

## Inventory

### Construction

`Inventory(key_attrs: Iterable[str], **kwargs)`. The `key_attrs`
argument names the attributes that will be available for grouping
via `get_group`. The set of key attributes is fixed at construction;
the container builds and maintains a per-attribute index for each
name supplied. Any additional keyword arguments are forwarded
unchanged to every `new_group` invocation (see below), so concrete
inventories can accept and pass through construction-time
configuration without overriding `__init__`.

`Inventory` is abstract: `new_group` is an abstract method that a
concrete subclass must define to choose which `InvGroup` (or
`InvGroup` subclass) backs each per-attribute index. The
constructor walks `key_attrs` and stores one `InvGroup` per
attribute by calling `self.new_group(attr_name=<name>, **kwargs)`,
injecting `attr_name` so subclasses can dispatch on attribute name
if they need different behavior per attribute.

The constructor also initializes the inventory's flat
`id -> item` map (`_items`), where every added `RawMat` is
registered for constant-time lookup by `Inventory.get` and
`Inventory.remove`. The per-id key-attribute snapshots used by the
mutation-detection check live on the individual `InvGroup`s
(each group keeps the snapshot for its own `attr_name`), not on
`Inventory` itself.

Requirements on key attributes:

- The attribute must exist on every `RawMat` instance later passed to
  `add`. The check is performed at insertion time; missing attributes
  raise an error.
- The attribute's values must be **sortable** (i.e., comparable via
  the standard `<`, `<=`, `==`, `>=`, `>` operators). This is needed
  so the implementation can support range queries through `GroupKey`
  with order-based operators.
- The attribute's value must be **immutable** on a given `RawMat`
  instance for the lifetime of that instance inside the inventory.
  This is a contract on the caller (see "Key-attribute immutability
  contract" below).

The physical-inventory ID (i.e., `x.id` inherited from `RawMat`'s
`HasID[str]`) is always indexed in addition to the configured key
attributes; it is not necessary (or permitted) to include `'id'` in
`key_attrs`.

### new_group

`new_group(**kwargs) -> InvGroup[T]`. Abstract method called once
per `key_attrs` entry during `__init__` to build that attribute's
`InvGroup`. Concrete subclasses must define it; the implementation
typically constructs an `InvGroup` (or a custom subclass of it) and
returns the new instance.

The constructor of `Inventory` always injects `attr_name=<name>`
into `kwargs` alongside any extra kwargs the caller supplied, so a
concrete `new_group` can:

- Dispatch on `attr_name` and choose a different `InvGroup`
  subclass for some attributes (e.g., a custom variant for `plant`,
  the default for everything else).
- Forward `kwargs` straight to the chosen `InvGroup`'s constructor
  to seed per-bucket state.
- Ignore the kwargs entirely and return a vanilla
  `InvGroup(attr_name)`.

### Key-attribute immutability contract

The grouping indices the `Inventory` maintains presume that the key
attributes of an item do not change while the item is in the
container. Mutating a key attribute after `add` breaks the indexing
silently in the worst case.

To detect this as early as possible, each `InvGroup` snapshots its
own attribute's value for every item at insertion time and exposes
a `verify(item)` method that re-reads the live value and compares
it against the snapshot. `Inventory` calls `group.verify(item)`
across every group whenever the item surfaces through an operation
(`get`, `remove`, or a `get_group` result); if any group's
attribute has changed, the operation raises before returning the
stale item — and, for `remove`, before any of the per-group state
is modified, so an inventory whose item failed verification is left
untouched.

This contract is documented behavior, not a typing-level guarantee.
Callers should treat key attributes as immutable on inventory-resident
`RawMat` instances; if a value really needs to change, the caller
should `remove` the item, update it, and `add` it back.

### get

`get(id_: str) -> T | None`. Returns the inventory item whose
physical-inventory ID equals `id_`, or `None` if no such item is
present. Constant-time lookup via the ID index.

### add

`add(x: T) -> None`. Inserts `x` into the inventory and updates every
configured index. Errors:

- Raises `ValueError` (or equivalent) if an item with the same `id`
  is already present.
- Raises (with a clear message) if `x` is missing any of the
  configured key attributes.

Side effects: the snapshot of `x`'s key-attribute values is recorded
for the mutation-detection check.

### remove

`remove(id_: str) -> T`. Removes and returns the inventory item whose
physical-inventory ID equals `id_`. Raises `KeyError` (or equivalent)
if no such item is present. All indices are updated to drop the
removed item.

If the removed item's current key-attribute values do not match the
snapshot taken at insertion (i.e., the immutability contract was
violated), the implementation raises before returning the item.

### get_group

`get_group(**kwargs: GroupKey | Any) -> set[T]`. Returns the set of
items matching every supplied attribute predicate. Each keyword name
is the name of a key attribute (one of those declared at
construction); each value is either a `GroupKey` describing the
predicate to apply to that attribute, or a non-`GroupKey` value `x`
that is taken as shorthand for `GroupKey(operator.eq, x)` — i.e.,
"attribute equals `x`".

Implementation: for each `(attr, gk)` pair, normalize `gk` to a
`GroupKey` (wrapping it in `GroupKey(operator.eq, gk)` if it isn't
one already), delegate to `self._groups[attr].get_group(...)` to get
the set of items satisfying that single predicate, then return the
intersection across those per-attribute sets.

Semantics:

- Predicates across multiple keyword arguments are combined with
  **logical AND** — an item must satisfy every predicate (via every
  per-attribute set) to appear in the result.
- Calling `get_group()` with no keyword arguments returns every item
  currently in the inventory.
- Passing a keyword that is not one of the configured `key_attrs`
  raises `KeyError` (the inventory has no index for it).
- The shorthand `attr_name=x` (for any non-`GroupKey` `x`) is
  equivalent to `attr_name=GroupKey(operator.eq, x)`, so the common
  "equal to this value" case can be written as `get_group(plant='FS')`
  rather than `get_group(plant=GroupKey(operator.eq, 'FS'))`.

The return type is a `set`, so iteration order is not part of the
contract; callers that need a deterministic order should sort the
result themselves.

## GreigeInv

`GreigeInv` is the concrete `Inventory[GreigeRoll]` subclass for
greige-roll inventories at the dyeing stage. It carries the same
`get` / `add` / `remove` / `get_group` interface as the base class,
plus five additional methods that own the entire dye-stage workflow:
reshaping odd-size rolls into dye-standard pieces
(`transform_odd_rolls`), partitioning the resulting inventory into
mutually compatible groups (`prepare_dye_pools`), exposing those
groups as immutable views (`lot_groups`), and assembling concrete
`DyeLot` records from a chosen group (`get_dye_lot`, `get_dye_lots`).

The intended caller flow is:

1. Populate the inventory by calling `add` for every known
   in-inventory roll and every scheduled future arrival.
2. Call `transform_odd_rolls()` once to bring every in-inventory roll
   to a dye-standard weight.
3. Call `prepare_dye_pools()` once to compute the maximal
   compatibility groups.
4. For each item the planner is trying to produce, retrieve the
   relevant compatibility groups via `lot_groups(item.id)` and call
   `get_dye_lot` (or `get_dye_lots` for a two-item shared cycle) on
   each candidate group until one yields a valid lot.

### transform_odd_rolls

`transform_odd_rolls() -> None` — splits and combines the in-inventory
rolls whose `qty` does not already lie in a dye-standard range for
their greige's `port_load_tgt`, so that after the call every
in-inventory roll either feeds a single dye port (1-port roll,
`qty in [port_load_tgt - 10, port_load_tgt + 10]`) or feeds two
ports at `qty / 2` each (2-port roll,
`qty in [2 * port_load_tgt - 20, 2 * port_load_tgt + 20]`).

The method mutates the inventory in place and returns nothing:

- Same-plant odd rolls (within a single greige style) may be
  combined into a dye-standard piece, discarding up to 30 lbs from
  one source per combine when needed. The two source rolls are
  removed from the inventory and the combined piece is inserted.
- Odd rolls large enough to yield a dye-standard piece via
  `GreigeRoll.split` are split; the dye-standard piece is inserted
  and the leftover re-enters the odd pool for further combining.
- Odd rolls that cannot be combined or split into a dye-standard
  piece are removed from the inventory.
- Future-arrival rolls (`avail_date is not None`) are not touched.
  Per the `GreigeRoll.new_arrival` contract they always arrive at
  the greige's standard port size and are dye-standard by
  construction.

### prepare_dye_pools

`prepare_dye_pools() -> None` — partitions the current in-inventory
rolls into the largest distinct groups of mutually compatible rolls
and caches the partition on the inventory for subsequent
`lot_groups` calls. Two rolls are mutually compatible iff they could
appear in the same dye cycle:

- they share the same greige product;
- they share the same knitting plant;
- their per-port loads are pairwise within 10 lbs of one another
  (each port load is `qty` for a 1-port roll or `qty / 2` for a
  2-port roll).

Partitions are cached **per greige style**: the inventory holds a
mapping from greige product to its tuple of compatibility groups.
`prepare_dye_pools` walks the current in-inventory rolls and, for
each greige style that has in-inventory rolls but no cached
partition, computes and caches that style's partition. Greige
styles whose partition is already cached are left alone — this makes
the method idempotent and cheap to call when only some caches were
invalidated. It should be called once after `transform_odd_rolls()`
and after all relevant in-inventory rolls have been added, and again
any time the caller has performed an invalidating mutation (see
"Cache invalidation" below).

Future-arrival rolls (`avail_date is not None`) are deliberately
excluded from every partition: they enter the planning pipeline
through a different path. Only the in-inventory rolls participate in
the cached pools.

**Cache invalidation.** Adding or removing an in-inventory roll
invalidates the cached partition **for that roll's greige style
only**; other styles' caches are unaffected. Because pools are kept
per greige, a change to one style's inventory can never make
another style's pool stale.

Specifically:

- `remove(id_)` where the removed roll has `avail_date is None`
  clears the cached partition for `removed_roll.product`. The
  partition is removed outright (not just marked stale), so a
  subsequent `lot_groups` call for that style raises until the
  cache is rebuilt.
- `add(x)` where `x.avail_date is None` likewise clears the cached
  partition for `x.product`, since the largest possible compatibility
  groups for that style may change with the new roll.
- Adds and removes of future-arrival rolls (`avail_date is not None`)
  do not touch any cached partition.
- Removes of an in-inventory roll for a greige style that does not
  currently have a cached partition are no-ops with respect to the
  cache.

Once invalidated for a given style, that style's partition is
rebuilt only by a subsequent `prepare_dye_pools` call (which will
recompute just the styles whose caches are missing).

### lot_groups

`lot_groups(item_id: str) -> list[tuple[GRollView, ...]]` — returns
the cached compatibility groups (from `prepare_dye_pools`) that
could be used to assemble a dye lot producing the `Fabric` item with
ID `item_id`. Only groups whose greige matches the item's
`greige_style` are returned. Each group is an immutable tuple of
`GRollView` snapshots — never the underlying `GreigeRoll`
instances — so the caller cannot inadvertently mutate
inventory-resident state through the result.

Calling `lot_groups` raises if no cached partition is currently
held for the item's greige style — either because
`prepare_dye_pools` has not yet been run for that style, or because
a subsequent in-inventory add/remove for that style invalidated
the cache (see "Cache invalidation" above). The check is
style-local: other styles' caches remain queryable. Callers that
encounter this error must re-run `prepare_dye_pools` before trying
again; the rerun will only recompute the missing styles' partitions.

### get_dye_lot

`get_dye_lot(item, jet_id, n, pool, max_avail_date=None) -> DyeLot | None`
— attempts to build a single `DyeLot` of size `n` that produces
`item` on the dye jet identified by `jet_id`, selecting from `pool`
(one compatibility group returned by `lot_groups`). Does not perform
split/combine; every entry in `pool` is expected to be a dye-standard
`GRollView` for `item.greige_style`.

This method does **not** mutate the inventory. The returned `DyeLot`
is a proposal: it references its rolls via `GRollView` snapshots
drawn from `pool` and the underlying `GreigeRoll`s stay in the
inventory. The planner can build many competing lots over
overlapping rolls and compare them before committing one. When a lot
is finally chosen, the caller removes its rolls explicitly via
`GreigeInv.remove(view.id)` for each view in `lot.rolls`; those
removals trigger the cache invalidation described under
`prepare_dye_pools`.

The method targets a single specific jet (rather than searching over
all jets that can run `item`) because the calling planning logic
will already have selected a jet. In the eventual production code,
`jet_id` and `n` will be supplied by a single `Jet` object; they are
accepted as separate primitive parameters here so the inventory can
be tested in isolation.

Parameters:

- `item: Fabric` — the fabric item the assembled lot will produce.
  Becomes the `fabric` attribute of the returned `DyeLot`.
- `jet_id: str` — the dye jet on which the resulting lot will run.
  Must satisfy `item.can_run_on_jet(jet_id)`.
- `n: int` — the target lot size. A lot occupies `2n - 1` ports if
  `item.omits_port` is `True`, otherwise `2n`.
- `pool: tuple[GRollView, ...]` — a single compatibility group of
  dye-standard `GRollView` snapshots, typically one element of the
  list returned by `lot_groups(item.id)`. Every entry is a 1-port or
  2-port roll for the greige associated with `item`, and all entries
  share the same plant (compatibility is enforced upstream by
  `prepare_dye_pools`).
- `max_avail_date: date | None = None` — optional upper bound on the
  lot's `avail_date`. If supplied, only rolls whose availability
  allows the resulting lot's `avail_date` to be at or before
  `max_avail_date` may be included. The default `None` imposes no
  upper bound.

**Port-loading model.** Let the greige associated with `item` have
per-port target `tgt = greige.port_load_tgt`. The lot occupies `P`
ports, where `P = 2n - 1` if `item.omits_port` else `P = 2n`. Each
view in the pool contributes to ports as follows:

- a 2-port view contributes two ports, each at `view.qty / 2`;
- a 1-port view contributes one port at `view.qty`.

The total port count contributed by the selected views must equal
`P`. When `item.omits_port` is `True`, an odd number of ports is
required, so the lot must contain at least one 1-port view. The
returned `DyeLot.rolls` is the tuple of `GRollView`s chosen during
selection.

**Port-load constraints.** The lot's port loads `p_1, ..., p_P` must
satisfy:

1. each `|p_i - tgt| <= 10` (every port within 10 lbs of the
   greige's target), and
2. `max(p_i) - min(p_i) <= 10` (every port within 10 lbs of every
   other port).

Both constraints are satisfied automatically when `pool` came from
`lot_groups` — `transform_odd_rolls` ensures each port load is
within 10 lbs of the greige target, and `prepare_dye_pools` ensures
pairwise compatibility within the group. The method nevertheless
verifies the constraints during selection so it can be called
against arbitrary `tuple[GRollView, ...]` inputs.

Returns the assembled `DyeLot` on success, or `None` if no lot
meeting the requested constraints can be built from `pool`
(including the case where `item.can_run_on_jet(jet_id)` is `False`).

### get_dye_lots

`get_dye_lots(item1, item2, jet_id, n1, n2, pool, max_avail_date=None) -> tuple[DyeLot, DyeLot] | None`
— attempts to build two `DyeLot`s that will share a single dye
cycle on the named jet but produce different `Fabric` items. Both
items must share a `greige_style` (and therefore the same
`port_load_tgt`), since the two lots co-load the same jet at the
same per-port target. The two returned lots draw from the same
`pool`, share a knitting plant, and have sizes `n1` and `n2`
respectively.

As with `get_dye_lot`, this method does not mutate the inventory:
each returned `DyeLot` is a proposal referencing its rolls via
`GRollView`. The two lots together select non-overlapping views
from `pool` (no view appears in both), but other candidate lots
built later from the same `pool` may still cover the same rolls.
Inventory removal happens explicitly via `GreigeInv.remove` when the
planner commits.

Parameters:

- `item1: Fabric`, `item2: Fabric` — the two fabric items to be
  produced. Each becomes the `fabric` attribute of the corresponding
  returned lot. Both must have the same `greige_style`.
- `jet_id: str` — the dye jet on which both lots will run. Must
  satisfy `item1.can_run_on_jet(jet_id)` and
  `item2.can_run_on_jet(jet_id)`.
- `n1: int`, `n2: int` — target lot sizes for the first and second
  lots. The shared cycle occupies
  `(2n1 - (1 if item1.omits_port else 0)) +
  (2n2 - (1 if item2.omits_port else 0))` ports on the jet.
- `pool: tuple[GRollView, ...]` — a single compatibility group of
  dye-standard `GRollView` snapshots, drawn from
  `lot_groups(item1.id)` (which equals `lot_groups(item2.id)` since
  the two items share a greige style). The two lots together consume
  from this one group; no view appears in both.
- `max_avail_date: date | None = None` — optional upper bound on each
  lot's `avail_date`, applied to both lots.

Returns the pair `(lot1, lot2)` on success, or `None` if no pair
meeting the requested constraints can be built from `pool`.

## DyeLot

`DyeLot` is a frozen dataclass representing a group of compatible
`GRollView`s assigned to produce a specific `Fabric` item. Two
fabric items sharing a greige style and color (but differing in
width) can be combined into a single dye cycle via
[`get_dye_lots`](#get_dye_lots).

`DyeLot` is itself passive: lots are constructed by `get_dye_lot` /
`get_dye_lots` and are not modified afterward. The class performs no
validation; enforcement of dye-cycle compatibility lives in the
factory methods.

A `DyeLot` is a **proposal**, not an extraction. It references its
rolls through immutable `GRollView` snapshots, leaving the underlying
`GreigeRoll`s in the source `GreigeInv`. This lets the planner build
and compare multiple candidate lots over the same rolls (e.g., two
competing jobs that could each consume the same inventory) without
committing the inventory state to any one of them. When the planner
finally picks a lot to commit, it explicitly removes the chosen
lot's rolls via `GreigeInv.remove` (looked up by `view.id`).

Fields and computed properties:

- `fabric: Fabric` — the fabric item this lot will produce.
- `rolls: tuple[GRollView, ...]` — the immutable views over the
  greige rolls assigned to this lot. All views in the tuple satisfy
  the dye-cycle matching constraints enforced by the factory
  methods.
- `avail_date: date | None` — computed property; the earliest date
  at which every view in the lot is available. Equal to the latest
  `avail_date` among `rolls`, with `None` (already in inventory)
  treated as "available immediately." If every view in the lot has
  `avail_date is None`, the lot's `avail_date` is also `None`.

## GRollView

`GRollView` is an immutable, frozen-dataclass view over a single
`GreigeRoll`. It exposes the same public attributes as its source
roll — `id`, `product`, `qty`, `avail_date`, `plant`, `item_variant`,
`yarn_merge`, `size` — captured at the moment the view was created.

Views are constructed by the `GreigeInv` query methods when they
need to expose roll data to callers. Returning views (rather than
the underlying rolls) preserves the inventory's immutability
contract: a caller that holds a view cannot mutate the live
inventory through it, and the view's attribute values are guaranteed
to be the values the inventory saw at the time the view was
produced.

`GRollView` carries no methods beyond those of a frozen dataclass
(equality, hashing, repr). It does not provide `split` or `combine`;
reshaping is a live-inventory operation and lives on `GreigeRoll`
inside `GreigeInv`.
