# inventory — Design

`core.materials.inventory` holds and groups `RawMat` objects so that subsets can
be selected for consumption. It provides the `Inventory[T]` base class (and the
planner-specific `GreigeInv`) plus a `group` sub-submodule holding the abstract
`Group[T]` and its `ValGroup[T]` / `SortedGroup[T]` / `GreigeGroup`
implementations.

## Overview

An `Inventory` holds a set of `RawMat` objects (`T` is bound to `RawMat`),
grouped according to the values of certain attributes. Using `select_where(...)`,
callers extract the `RawMat` objects that meet all the provided conditions — each
condition being either equality with a specific value or membership in a range of
values. The conditions are of type `Condition`, a union of the `Exactly`,
`Greater`, `Less`, and `InRange` dataclasses (see Conditions below).

The `group` sub-submodule holds the group types that back an `Inventory`.

## Core objects

### Module level

- Constants: none.
- Type aliases:
  ```python
  Condition = Exactly | Greater | Less | InRange
  ```
- Classes:
  ```python
  @dataclass(frozen=True)
  class Exactly:
      val: Any
      def to_func(self) -> Callable[[Any], bool]: ...

  @dataclass(frozen=True)
  class Greater:
      lo: Any
      incl: bool = False
      def to_func(self) -> Callable[[Any], bool]: ...

  @dataclass(frozen=True)
  class Less:
      hi: Any
      incl: bool = False
      def to_func(self) -> Callable[[Any], bool]: ...

  @dataclass(frozen=True)
  class InRange:
      lo: Any
      hi: Any
      incl_lo: bool = True
      incl_hi: bool = False
      def to_func(self) -> Callable[[Any], bool]: ...

  class Inventory[T: RawMat]:
      def __init__(self, grouped: list[str], sorted: list[str]): ...
      def add(self, mat: T) -> None: ...
      def remove(self, id: str | int) -> T: ...
      def select_where(self, **conditions) -> list[T]: ...

  class GreigeInv(Inventory[GreigeRoll]):
      # grouped: size/plant/variant/yarn_merge; sorted: qty/avail_date;
      # sku handled by a GreigeGroup
      def __init__(self): ...
      def transform_rolls(self) -> None: ...
      def prepare_dye_pool(self) -> None: ...
      def dye_lots(self, style: str) -> list[set[GreigeRoll]]: ...
      def has_cached_lots(self, style: str) -> bool: ...
      def create_roll(self, sku: str, avail_date: date, qty: float, plant: str,
                      greige: Greige | None) -> GreigeRoll: ...
  ```

### `group` sub-submodule

No dedicated `DESIGN.md`; documented here.

Constants — dye-lot / jet-port loading limits (may change if the jets are
replaced with machines that have different restrictions):

```python
MIN_PORT_LBS = 300    # minimum lbs a jet port may be loaded with
MAX_PORT_LBS = 400    # maximum lbs a jet port may be loaded with
PORT_EVEN_TOL = 10    # max lbs difference between ports in a lot
MAX_TRIM_LBS = 30     # max lbs discarded from a roll when combining to reach standard
```

```python
class Group[T: RawMat](ABC):
    def __init__(self, attr: str): ...
    @property
    def attr(self) -> str: ...
    @abstractmethod
    def add(self, mat: T) -> None: ...
    @abstractmethod
    def remove(self, id: str | int, val: Any) -> None: ...
    @abstractmethod
    def get_group(self, cond: Condition) -> set[T]: ...

class ValGroup[T: RawMat](Group[T]): ...      # maps attribute values -> sets of T
class SortedGroup[T: RawMat](Group[T]): ...   # keeps a list sorted by attr

class GreigeGroup(ValGroup[GreigeRoll]):      # keyed on the roll's sku (greige style)
    def transform_rolls(self) -> None: ...
    def prepare_dye_pool(self) -> None: ...
    def dye_lots(self, style: str) -> list[set[GreigeRoll]]: ...
    def has_cached_lots(self, style: str) -> bool: ...
```

`GreigeGroup` is a planner-specific `Group` implementation; per convention it
lives alongside its parent `ValGroup` in this sub-submodule.

## `Inventory[T]`

Holds a set of `RawMat` objects grouped according to the values of certain
attributes. `T` is bound to `RawMat`.

- **Initialization** — takes a list of `grouped` attributes and a list of
  `sorted` attributes. *(How these drive the internal grouping/sorting is TBD.)*
- `add(mat)` — add a `RawMat` to the inventory.
- `remove(id)` — remove and return the `RawMat` with the given `id`.
- `select_where(attr1=val_or_cond1, attr2=val_or_cond2, ...)` — return the list
  of `RawMat` objects meeting all the provided conditions. Each keyword value is
  either a `Condition` or a plain value; a plain value is treated as
  `Exactly(value)`, inferred and constructed internally. (See Conditions below.)

## `GreigeInv`

A planner-specific `Inventory[GreigeRoll]`, living alongside its parent
`Inventory` per convention. It fixes the grouping/sorting configuration for
greige rolls and surfaces the dye-lot operations at the inventory level.

- **Grouped attributes** (value-based): `size`, `plant`, `variant`, `yarn_merge`.
  The `sku` is a special case, handled by a `GreigeGroup` rather than a plain
  `ValGroup`.
- **Sorted attributes**: `qty`, `avail_date`.
- `transform_rolls()`, `prepare_dye_pool()`, `dye_lots(style)`,
  `has_cached_lots(style)` — delegate to the `sku`-keyed `GreigeGroup`, so all the
  dye-lot operations are reachable from the inventory level.
- `create_roll(sku, avail_date, qty, plant, greige)` — construct and return a
  `GreigeRoll` for a roll that is needed but not currently in inventory (created
  the moment it is needed and discarded if unnecessary). The caller supplies every
  `GreigeRoll` constructor argument except:
  - `id` — generated from a single auto-incrementing counter: a plant-based prefix
    (`FS` for Fairystone, `WV` for Whiteville), followed by `NEW`, followed by `-`
    and the counter value (e.g. `FSNEW-0`, `WVNEW-1`).
  - `yarn_merge` — defaults to `-1` for rolls not in inventory.
  - `variant` — set to the same string as `sku`.

  This constructs the roll only; it does not add it to the inventory.

## Conditions

`Condition` is not a real class but a type alias for the union of four
dataclasses, each describing a constraint on an attribute value. The types of
`val`, `lo`, and `hi` are left as `Any`, since they depend on the attribute being
matched. Each dataclass provides `to_func()`, which returns a function that
returns `True` iff the passed value meets the condition the dataclass describes.

- `Exactly(val)` — the value equals `val`. `Exactly` can be passed directly to
  `select_where`, and is also what `select_where` infers/constructs internally
  when it receives a plain `attr=val` keyword pair.
- `Greater(lo, incl=False)` — the value is greater than `lo`, or `>= lo` when
  `incl` is `True`.
- `Less(hi, incl=False)` — the value is less than `hi`, or `<= hi` when `incl` is
  `True`.
- `InRange(lo, hi, incl_lo=True, incl_hi=False)` — the value is between `lo` and
  `hi`, including `lo` iff `incl_lo` and including `hi` iff `incl_hi`.

## `group` sub-submodule

The group types back an `Inventory`: each tracks the `RawMat` objects for one
attribute so that subsets can be pulled efficiently. Both implementations expose
the same interface but store their elements differently; the user chooses which
group type to use for each attribute based on how its elements are most likely to
be selected.

### `Group[T]` (abstract base)

The abstract base for the group types. `T` is bound to `RawMat`. Stores the
attribute it groups on; subclasses share this interface but implement the storage
differently.

- `attr` — the attribute this group is keyed on (read-only).
- `add(mat)` — add a `RawMat` to the group.
- `remove(id, val)` — remove the `RawMat` with the given `id`, where `val` is the
  value that object has for `attr`. It takes both arguments because it is only
  ever called from `Inventory.remove` — the `Inventory` maintains its own
  id → `RawMat` map for efficient removal, so it already knows the object's `attr`
  value and the group can locate the entry via `val` without scanning.
- `get_group(cond)` — return the set of `RawMat` objects matching the given
  `Condition`. The plain-value → `Exactly` inference happens upstream in
  `Inventory`, so a group always receives a `Condition`.

### `ValGroup[T]`

Maintains an internal mapping of attribute values to sets of `RawMat` objects.
This makes `Exactly` selections efficient (direct keyed lookup).

### `SortedGroup[T]`

Maintains a list of `RawMat` objects sorted according to the selected attribute.
This makes the range conditions (`Greater`, `Less`, `InRange`) efficient, at the
cost of `Exactly` selections.

### `GreigeGroup`

A planner-specific `ValGroup[GreigeRoll]` keyed on the roll's `sku` (the greige
style). It brings off-size rolls to a standard size and assembles the rolls of
each style into dye lots.

A **dye lot** loads several rolls across the ports of a dye jet. There is a hard
global limit: no jet port may be loaded with less than `MIN_PORT_LBS` (300) or
more than `MAX_PORT_LBS` (400) lbs of fabric. The ports must also be loaded
evenly — all within `PORT_EVEN_TOL` (10) lbs of one another. A set of
**compatible** rolls is therefore one where every roll's `avg_port_wt` is between
`MIN_PORT_LBS` and `MAX_PORT_LBS`, and all their `avg_port_wt` values are within
`PORT_EVEN_TOL` of one another (so that, once divided across their ports, every
port carries a legal and roughly equal weight).

- `transform_rolls()` — perform the `split` / `combine` operations that bring
  off-size rolls to a standard size, getting as many rolls as possible to
  `STANDARD`. This may be inefficient: it only runs once (rolls expected to arrive
  at a future date are assumed to already be standard size). For each `sku`:
  1. Test every pairing of the sku's off-size (non-`STANDARD`) rolls; whenever
     `combine`-ing a pair yields a standard-size roll, combine them.
  2. On the rolls still off-size, test every pairing again, this time allowing up
     to `MAX_TRIM_LBS` (30) lbs to be removed (split off) from one roll before
     combining, to land the result at a standard size. The removed portion
     (<= `MAX_TRIM_LBS`) is discarded as waste.
- `prepare_dye_pool()` — group each style's (post-`transform_rolls`) rolls into
  valid dye lots and cache the lots per greige style. Does not itself split or
  combine.
- `dye_lots(style)` — return the cached list of the largest disjoint sets of
  compatible greige rolls for `style`.
- `has_cached_lots(style)` — whether valid cached lots exist for `style`. Callers
  use this to decide when a fresh `prepare_dye_pool()` is needed, so the lots are
  not recomputed on every `add` / `remove`.

Adding or removing a `GreigeRoll` (via the inherited `add` / `remove`) invalidates
the cached dye lots for the affected style.

**Grouping algorithm (`prepare_dye_pool`).** Within a style, a valid dye lot is a
set of rolls whose `avg_port_wt` values all lie in `[MIN_PORT_LBS, MAX_PORT_LBS]`
and within a `PORT_EVEN_TOL`-lb window of one another (`max - min <=
PORT_EVEN_TOL`). Since both constraints depend only on `avg_port_wt`, optimal lots
are contiguous runs once the rolls are sorted by `avg_port_wt`. Two options:

- *Greedy sweep (proposed default).* First discard any roll whose `avg_port_wt`
  is outside `[MIN_PORT_LBS, MAX_PORT_LBS]` — it cannot be legally loaded into any
  lot. Sort the rest by `avg_port_wt` (`O(n log n)`), then sweep left to right,
  adding each roll to the current lot while it stays within `PORT_EVEN_TOL` lbs of
  that lot's smallest roll, otherwise closing the lot and opening a new one at
  that roll (`O(n)` after the sort). This minimizes the number of lots for the fixed 10-lb window and so
  yields the largest lots — matching "largest disjoint sets."
- *1-D DP (if constraints/objectives grow).* If lots later gain a jet
  port-capacity cap, or we want to optimize a specific objective (maximize full
  lots, balance lot sizes, etc.), run a DP over the sorted rolls:
  `dp[i]` = best grouping of the first `i` rolls, transitioning over contiguous
  runs `[j, i)` whose span is `<= 10` (and size `<=` capacity). `O(n^2)`, or
  `O(n * window)` with the span/capacity bound.

The greedy sweep is the recommended default; the DP is the fallback once a
port-capacity limit or richer objective enters the picture.
