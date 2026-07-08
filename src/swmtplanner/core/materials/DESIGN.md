# materials — Design

`core.materials` deals with the tracking and consumption of raw materials. It has
two submodules:

- `rawmat` — the `RawMat` base class (a unit of physical raw materials) and its
  concrete implementations, starting with `GreigeRoll`. Both `RawMat` and its
  concrete subclasses are surfaced at the top level of `materials`. It also holds
  `DyeLot`, which groups `GreigeRoll`s and tracks their aggregate qualities.
- `inventory` — the `Inventory[T]` base class plus a `group` sub-submodule
  holding the abstract `Group[T]` and its `ValGroup[T]` / `SortedGroup[T]`
  implementations. Has its own `DESIGN.md`.

## Overview

An `Inventory` holds a set of `RawMat` objects, grouped according to the values
of certain attributes, and supports extracting the subset that meets a given set
of conditions. The grouping/selection machinery is documented in the `inventory`
submodule's own `DESIGN.md`.

## Core objects

### `rawmat` submodule

No dedicated `DESIGN.md`; documented here.

- Constants — greige roll sizes (ordered smallest → largest):
  ```python
  SMALL = 0
  STANDARD = 1
  LARGE = 2
  ```
- Constants — size-classification parameters (may change in the future):
  ```python
  DEFAULT_ROLL_WT = 700   # assumed target roll weight when the greige style is unknown
  SINGLE_PORT_MAX = 400   # target <= this -> single-port style; above -> double-port
  STD_SIZE_TOL = 25       # avg_port_wt within this of single_target counts as STANDARD
  ```
- Classes:
  ```python
  class RawMat(HasID[str | int]):
      def __init__(self, id: str | int, sku: str, avail_date: datetime,
                   qty: float, unit: str): ...
      @property
      def id(self) -> str | int: ...
      @property
      def sku(self) -> str: ...
      @property
      def avail_date(self) -> datetime: ...
      @property
      def qty(self) -> float: ...
      @property
      def unit(self) -> str: ...

  class GreigeRoll(RawMat):
      def __init__(self, id: str, sku: str, avail_date: datetime, qty: float,
                   plant: str, variant: str, yarn_merge: int,
                   greige: Greige | None): ...
      # unit is always 'lbs'
      @property
      def id(self) -> str: ...
      @property
      def plant(self) -> str: ...
      @property
      def variant(self) -> str: ...
      @property
      def yarn_merge(self) -> int: ...
      @property
      def greige(self) -> Greige | None: ...
      @property
      def single_target(self) -> float: ...  # per-port target weight for the style
      @property
      def size(self) -> int: ...          # SMALL / STANDARD / LARGE, from avg_port_wt
      @property
      def n_ports(self) -> int: ...        # nearest whole number of ports qty spans
      @property
      def avg_port_wt(self) -> float: ...   # qty / n_ports
      def split(self, lbs1: float, lbs2: float) -> tuple[GreigeRoll, GreigeRoll]: ...
      def combine(self, roll: GreigeRoll) -> GreigeRoll: ...

  class DyeLot:
      def __init__(self, rolls: list[GreigeRoll]): ...   # all rolls share sku and plant
      @property
      def sku(self) -> str | None: ...      # None when the lot is empty
      @property
      def plant(self) -> str | None: ...    # None when the lot is empty
      @property
      def avail_date(self) -> datetime | None: ...   # max avail_date; None when empty
      @property
      def total_lbs(self) -> float: ...     # 0 when empty
      @property
      def n_ports(self) -> int: ...         # 0 when empty
      @property
      def avg_port_wt(self) -> float: ...   # 0 when empty
      def add(self, roll: GreigeRoll) -> None: ...
      def remove(self, id: str) -> GreigeRoll: ...
      def __iter__(self) -> Iterator[GreigeRoll]: ...
  ```

## `rawmat` submodule

Defines the base unit of physical raw materials and (later) its concrete
implementations.

### `RawMat`

The base class representing a unit of physical raw materials. It is "abstract" in
the sense that it represents an abstract concept and is not intended to be
instantiated directly; concrete subclasses (TBD) extend it. Implements the
`HasID` protocol. All attributes are guaranteed to be passed to the initializer
and are concretely stored, exposed as read-only properties:

- `id` — the `HasID` identifier. Most materials are identified by a string, but
  some are given a unique integer, hence `str | int`.
- `sku` — the material's SKU.
- `avail_date` — when the material becomes available.
- `qty` — the quantity on hand.
- `unit` — the unit of measure for `qty`.

### `GreigeRoll`

The first concrete `RawMat`: a physical roll of greige fabric available to be
dyed. It uses a `str` `id`, and its `unit` is always `'lbs'`. On top of `RawMat`
it adds these read-only properties:

- `plant` — the plant the roll belongs to.
- `variant` — the greige variant (how the roll is classified in inventory).
- `yarn_merge` — the yarn merge.
- `greige` — the `Greige` style this roll is, or `None` for styles we don't knit
  / don't have the data for.
- `single_target` — the per-port target weight for the roll's style (see the
  size classification below): `greige.tgt_wt` (or `DEFAULT_ROLL_WT` if `greige`
  is `None`) for single-port styles, or half that for double-port styles.
- `size` — the roll size, one of `SMALL` (0), `STANDARD` (1), `LARGE` (2).
  Computed from `avg_port_wt` (see below).
- `n_ports` — the number of ports the roll spans: `max(1, round(qty /
  single_target))`, where `single_target` is the per-port target weight from the
  size classification below. (Combining a small and a large roll, say, can yield
  ~4 ports' worth of greige.)
- `avg_port_wt` — the approximate pounds loaded into each port when the roll is
  divided evenly across its ports: `qty / n_ports`.

**Size classification.** `size` is derived from the roll's `avg_port_wt` and the
style's per-port target weight:

- Let `target = greige.tgt_wt`, or `DEFAULT_ROLL_WT` (700 lbs) if `greige` is
  `None`.
- The per-port target is `single_target = target` for single-port styles
  (`target <= SINGLE_PORT_MAX`), or `single_target = target / 2` for double-port
  styles (`target > SINGLE_PORT_MAX`).
- `n_ports = max(1, round(qty / single_target))` and
  `avg_port_wt = qty / n_ports`.
- Classify by `avg_port_wt` (with `t = STD_SIZE_TOL`):
  - `SMALL` — `avg_port_wt < single_target - t`
  - `STANDARD` — `single_target - t <= avg_port_wt <= single_target + t`
  - `LARGE` — `avg_port_wt > single_target + t`

**split / combine.** Dye jet ports must be loaded evenly (the same number of
pounds on each), so `split` / `combine` let the planner use off-size rolls to
build reasonably even dye lots:

- `split(lbs1, lbs2)` — split this roll into two `GreigeRoll`s of `lbs1` and
  `lbs2` pounds. Validates that `lbs1 + lbs2 == qty` and raises otherwise. The two
  rolls inherit all other attributes from the parent, with `'A'` and `'B'`
  appended to the parent `id` for their ids (their `size` is recomputed from the
  new `qty`).
- `combine(roll)` — combine this roll with `roll` into a single `GreigeRoll`,
  summing their pounds. Validates that `roll` has the same `sku` and `plant`
  (raises otherwise). In the result: `id` is the two ids joined with `'/'`; `qty`
  is the sum; `avail_date` is the later of the two; `variant` is the two variants
  joined with `'/'` (or kept as-is if identical); `yarn_merge` is kept if the two
  are identical, else `-1`. (`sku`/`plant` match by validation, `greige` is kept,
  and `size` is recomputed from the summed `qty`.)

### `DyeLot`

A group of `GreigeRoll`s (all sharing a `sku` and a `plant`) that tracks the
group's aggregate qualities. Constructed from a (possibly empty) list of rolls;
the constructor validates that they all share a `sku` and a `plant`, raising
otherwise. Read-only properties (with their empty-lot values):

- `sku` — the shared `sku` of the component rolls; `None` if the lot is empty.
- `plant` — the shared `plant` of the component rolls; `None` if the lot is empty.
- `avail_date` — the maximum `avail_date` among the component rolls; `None` if the
  lot is empty.
- `total_lbs` — the total pounds across the rolls (sum of their `qty`); `0` if
  empty.
- `n_ports` — the total number of ports the lot spans (sum of the rolls'
  `n_ports`); `0` if empty.
- `avg_port_wt` — the average pounds per port across the lot
  (`total_lbs / n_ports`); `0` if empty.

Methods:

- `add(roll)` — add a roll to the lot. Validates the roll shares the lot's `sku`
  and `plant` (adding to an empty lot establishes them).
- `remove(id)` — remove and return the roll with the given `id`.
- `__iter__` — iterate over the rolls in the lot.

## `inventory` submodule

The `Inventory[T]` base class and the grouping machinery (`group` sub-submodule
with the abstract `Group[T]` and its `ValGroup[T]` / `SortedGroup[T]`
implementations) it uses.

See `src/swmtplanner/core/materials/inventory/DESIGN.md`.
