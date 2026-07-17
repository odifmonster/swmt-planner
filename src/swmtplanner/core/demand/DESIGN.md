# demand — Design

`core.demand` tracks how well the current schedule fulfills demand on a single
product item: both the hard order requirements and the safety-stock
replenishment. It answers two questions about the current plan — *are orders
going to be filled late?* and *how well are desired inventory levels
maintained?* — and is where the planners look to report order fulfillment and
finished-goods inventory management.

> **Status:** the `requirement` submodule (the requirement/order hierarchy), the
> top-level `RlsItem` / `Chunk`, and the `view` submodule (`DemandView`,
> `RawView`, `SafetyView`) are all designed below, including `SafetyView`'s two
> passes — chunk distribution (carrying/safety/excess) and the physical-pool
> `drainage` walk.

## Overview

The module is organized around one top-level object per item, `RlsItem[T]`
(a "release item"), which packages together everything about the material
release on a single product `T`. It splits its tracking into two independent
concerns, each owned by a dedicated view (the views live in the `view`
submodule):

- **`RawView` — order lateness.** Tracks whether the current schedule fills the
  hard order requirements late, *even if it drains safety stock to do so*. This
  is the pure "will demand be met on time?" question.
- **`SafetyView` — inventory-level maintenance.** Tracks how well the schedule
  holds the desired inventory levels: if safety stock is drained, how long it
  stays drained; if excess is produced outside the ideal lead time, how long it
  is carried.

The views are the workhorses: they are responsible for distributing the jobs on
the schedule across the individual orders, and `RlsItem` reports through them.
Both share a base, `DemandView`, that holds the item, its orders, and the
registered chunks; each concrete view defines its own `recompute` distribution
rules.
Schedule jobs reach the views as `Chunk[T]` records (item + availability date +
quantity): a planner-specific `RlsItem` subclass converts its jobs into `Chunk`s
and feeds them in via `register_chunk` / `register_chunks`, and `RlsItem`
distributes them to the two views.

Beneath the views are lightweight objects that simply represent individual
requirements and their statuses — they carry no complicated logic of their own.
They live in the `requirement` submodule and share a common base,
`Requirement[T]`:

- `Requirement[T](HasID[str])` — the abstract base: a single quantity
  requirement on an item (`item`, `init_qty`, `covered_on_hand`, a settable
  `allocated_qty`, and a computed `remaining`).
  - `Safety[T]` — the remaining safety-stock replenishment still needed on the
    item; adds nothing (used by `SafetyView`).
  - `Order[T]` — a single dated order; adds `week_offset` and `due_date`.
    - `SafetyOrder[T]` — one safety-stock replenishment order; adds nothing
      (used by `SafetyView`).
    - `RawOrder[T]` — one hard-requirement order; adds late-arrival reporting
      (used by `RawView`).

So the containment is roughly: `RlsItem[T]` → { `RawView[T]` → `RawOrder[T]`s;
`SafetyView[T]` → `SafetyOrder[T]`s + `Safety[T]` }, with material fed in as
`Chunk[T]`s.

Every class in the module is generic and bound to `Product`
(`RlsItem[T: Product]`, `RawView[T: Product]`, `Order[T: Product]`, and so on).

### The `Product` bound

The type parameter `T` is a product style from `core.product` — currently either
`Fabric` or `Greige`. `core.product` defines `Product` as a union type alias
(`type Product = Fabric | Greige`) over exactly those concrete classes. The two
product structures share no common interface, so `Product` is a plain union alias
rather than a base class: the bound is a *conceptual* constraint on which classes
`T` may be, not an interface the generics rely on for behavior.

## Core objects

- Constants: none (so far).
- Module-level classes (all generic, bound to `Product`):
  ```python
  @dataclass(frozen=True)
  class Chunk[T: Product]:
      item: T
      avail_date: datetime
      qty: float

  class RlsItem[T: Product]:              # abstract; planner-specific subclasses
      def __init__(self, item: T, lead_time: timedelta, on_hand: float,
                   safety_tgt: float, start_week: tuple[int, int],
                   today: datetime,
                   due_reqs: list[tuple[float, datetime]]) -> None: ...
      @property
      def raw_view(self) -> RawView[T]: ...
      @property
      def safety_view(self) -> SafetyView[T]: ...
      @property
      def lead_time(self) -> timedelta: ...
      @property
      def safety_tgt(self) -> float: ...
      @property
      def today(self) -> datetime: ...
      @property
      def init_on_hand(self) -> float: ...
      def register_chunk(self, chunk: Chunk[T]) -> None: ...
      def register_chunks(self, chunks: list[Chunk[T]]) -> None: ...
      # + a planner-specific hook converting schedule jobs to Chunks (raises
      #   NotImplementedError in the base; TBD)
  ```

Abstract classes/methods here do **not** use `ABC`; a member whose
implementation is deferred to a subclass simply raises `NotImplementedError` in
the base — whether planner-specific (e.g. `Requirement.id`, the `RlsItem` job →
`Chunk` hook) or view-specific (e.g. `DemandView.recompute`).

### `view` submodule

The shared base `DemandView` and the two concrete views (documented here; no
separate `DESIGN.md`). All generic, bound to `Product`.

  ```python
  class DemandView[T: Product]:           # abstract base; recompute is subclass-specific
      def __init__(self, item: T, orders: list[Order[T]]) -> None: ...
      @property
      def item(self) -> T: ...
      @property
      def orders(self) -> tuple[Order[T], ...]: ...
      def clear_chunks(self) -> None: ...
      def register_chunk(self, chunk: Chunk[T]) -> None: ...
      def register_chunks(self, chunks: list[Chunk[T]]) -> None: ...
      def recompute(self) -> None: ...    # raises NotImplementedError in the base

  class RawView[T: Product](DemandView[T]):
      late_base: float                    # tunable lateness base; defaults to 2.0
      @property
      def lateness(self) -> float: ...    # see formula below
      def recompute(self) -> None: ...

  class SafetyView[T: Product](DemandView[T]):
      def __init__(self, item: T, orders: list[SafetyOrder[T]],
                   safety_tgt: float, lead_time: timedelta,
                   on_hand: float, today: datetime) -> None: ...
      @property
      def safety(self) -> Safety[T]: ...        # pool = safety.allocated_qty; shortfall = safety.remaining
      @property
      def carrying(self) -> float: ...         # early supply for future orders, net of lead time
      @property
      def drainage(self) -> float: ...         # time-integral of pool below the safety target
      @property
      def excess(self) -> float: ...           # scalar qty beyond total demand + safety
      def recompute(self) -> None: ...
  ```

### `requirement` submodule

The lightweight per-requirement classes (documented here; no separate
`DESIGN.md`). All generic, bound to `Product`:

  ```python
  class Requirement[T: Product](HasID[str]):
      def __init__(self, item: T, init_qty: float,
                   covered_on_hand: float) -> None: ...
      @property
      def id(self) -> str: ...          # abstract; each subclass defines its format
      @property
      def item(self) -> T: ...
      @property
      def init_qty(self) -> float: ...
      @property
      def covered_on_hand(self) -> float: ...
      @property
      def allocated_qty(self) -> float: ...
      @allocated_qty.setter
      def allocated_qty(self, value: float) -> None: ...
      @property
      def remaining(self) -> float: ...   # max(0.0, init_qty - covered_on_hand - allocated_qty)

  class Safety[T: Product](Requirement[T]):
      @property
      def id(self) -> str: ...            # f'S@{self.item.id}'

  class Order[T: Product](Requirement[T]):
      def __init__(self, item: T, init_qty: float, covered_on_hand: float,
                   first_week: tuple[int, int], due_date: datetime) -> None: ...
      @property
      def id(self) -> str: ...            # f'P{week_offset}-{iso_weekday}@{item.id}'
      @property
      def week_offset(self) -> int: ...
      @property
      def due_date(self) -> datetime: ...

  class SafetyOrder[T: Product](Order[T]):
      ...                                 # no additions

  class RawOrder[T: Product](Order[T]):
      @property
      def late_fill_date(self) -> datetime | None: ...
      @property
      def late_qty(self) -> float: ...
      def late_table(self) -> list[tuple[timedelta, float]]: ...
      def clear_chunks(self) -> None: ...
      def add_chunk(self, chunk: Chunk[T]) -> None: ...
  ```

## `Chunk[T]`

A simple, immutable record of a quantity of product becoming available on a date
— the unit of scheduled supply that gets fed into an `RlsItem`. A frozen
dataclass.

- `item` — the product style (`T`) the chunk is of.
- `avail_date` — the `datetime` the quantity becomes available.
- `qty` — the quantity (a `float`).

## `RlsItem[T]`

The top-level object for the module. Represents the material release on a single
product item `T`, packaging order fulfillment and safety-stock replenishment
together. Delegates the two tracking concerns to its `RawView[T]` (order
lateness) and `SafetyView[T]` (inventory-level maintenance), and exposes
reporting on order fulfillment and finished-goods inventory management drawn from
them. `RlsItem` is abstract: concrete, planner-specific subclasses supply the
job → `Chunk` conversion.

- Construction — takes:
  - `item` — the product style (`T`) this release is for.
  - `lead_time` — the ideal production lead time, a `timedelta` (used by the
    `SafetyView` to judge whether supply arrives within the ideal window).
  - `on_hand` — the starting on-hand quantity of the item.
  - `safety_tgt` — the target safety-stock level.
  - `start_week` — the release's first week, as an `(ISO year, ISO week)` pair;
    passed through as the `first_week` of the `Order`s it builds.
  - `today` — the plan's reference "current" date (a `datetime`), used by the
    safety-side netting below and forwarded to the `SafetyView` for its drainage
    window.
  - `due_reqs` — the hard demand, as a list of `(qty, due_date)` pairs; these
    become one order per view.
  From these it builds its `RawView` (over `RawOrder`s) and `SafetyView` (over
  the mirrored `SafetyOrder`s + a `Safety`). Each `(qty, due_date)` in `due_reqs`
  becomes one order per view (`init_qty = qty`, `first_week = start_week`,
  `due_date = due_date`).

  **Netting.** At construction the initial `on_hand` is used to set the
  `covered_on_hand` of the requirements — netted *differently per view*, so a
  `RawOrder` and its mirror `SafetyOrder` generally end up with different
  `covered_on_hand`. The distribution passes then work against the resulting net
  requirements. (The raw `on_hand` is *also* forwarded to the `SafetyView`, which
  uses it as the starting level of its `drainage` physical pool — a separate use
  from this netting; see that section.)
  - **`RawView` side.** On-hand simply covers the `RawOrder`s sequentially in
    **due-date order**: earliest-due first, each order's `covered_on_hand`
    absorbs as much of the remaining on-hand as its `init_qty` allows, until the
    on-hand is exhausted.
  - **`SafetyView` side.** On-hand is applied with the same priority logic the
    view's `recompute` uses, treating the on-hand as available at `today`
    (horizon `d0` = latest order `due_date` on or before `today + lead_time`):
    cover demand through `d0` (due-date order), then top up `safety` toward
    `safety_tgt`, then cover future orders (due after `d0`). This sets
    `covered_on_hand` on the `SafetyOrder`s **and** on the `Safety` object. Any
    on-hand left over is simply dropped (there is no on-hand "excess" — we do not
    penalize inventory that already exists). These `covered_on_hand` values are
    fixed for the life of the release; `recompute`'s reset does not change them.
- `raw_view` — the `RawView[T]` (read-only).
- `safety_view` — the `SafetyView[T]` (read-only).
- `lead_time` — the ideal production lead time, a `timedelta` (read-only).
- `safety_tgt` — the target safety-stock level (read-only).
- `init_on_hand` — the starting on-hand quantity the release was constructed with
  (read-only).
- `register_chunk(chunk)` — register one `Chunk[T]` of available supply,
  distributing it to the views to be allocated against orders / safety.
- `register_chunks(chunks)` — the list convenience form of `register_chunk`.
- A planner-specific hook converts the planner's own schedule jobs into `Chunk`s
  to hand to the register methods. The base raises `NotImplementedError`;
  concrete planner subclasses override it. Its signature depends on the
  `schedule` module's job representation and is *TBD*.

## The `view` submodule

The shared base `DemandView` and the two concrete views (`RawView`,
`SafetyView`). No separate `DESIGN.md`; documented in the subsections below.

### `DemandView[T]`

The abstract base for both views. Holds the item, its orders, and the chunks
registered against it, and exposes the machinery for (re)distributing those
chunks. `item` and `orders` are supplied at construction (`orders` as a list,
stored/exposed as a tuple).

- `item` — the product style (`T`) this view is for (read-only).
- `orders` — the view's orders, as a tuple (read-only). Concrete views narrow
  the element type (`RawOrder[T]` for `RawView`, `SafetyOrder[T]` for
  `SafetyView`).
- Internally maintains a **sorted list of chunks** (by `avail_date`), kept in
  order as chunks are registered/cleared.
- `clear_chunks()` — empty the view's chunk list.
- `register_chunk(chunk)` — insert one `Chunk[T]` into the sorted chunk list.
- `register_chunks(chunks)` — the list convenience form of `register_chunk`.
- `recompute()` — distribute the registered chunks across the view's
  orders/requirements according to that view's rules. Abstract: raises
  `NotImplementedError` in the base; each concrete view overrides it.

### `RawView[T]`

Tracks whether the current schedule fills the item's hard order requirements
late, even at the cost of draining safety stock. Distributes the registered
chunks across the item's `RawOrder[T]`s. The main entry point for
order-fulfillment reporting.

- `late_base` — the tunable base of the lateness penalty (an instance attribute);
  defaults to `2.0`.
- `lateness` — an overall `float` collapsing the item's total "lateness" under
  the current schedule to a single number. For every chunk applied to an order
  whose `avail_date` is past that order's `due_date`, add
  `chunk.qty * late_base ** days_late`, where
  `days_late = (chunk.avail_date - order.due_date).total_seconds() / 86400`;
  `lateness` is the sum of these penalties over all late chunk/order
  applications. (Equivalently, summing `qty * late_base ** (lag.total_seconds()
  / 86400)` over each order's `late_table()` entries.) With the default
  `late_base = 2.0`, each additional day late doubles that chunk's contribution.
- `recompute()` — the distribution algorithm:
  1. Reset every order: set its `allocated_qty` to `0` and `clear_chunks()`.
  2. Walk the view's chunks earliest → latest (by `avail_date`). For each chunk,
     fill orders in due-date order, earliest → latest: give the current order as
     much of the chunk as it still needs (its `remaining`), updating that order's
     `allocated_qty` in parallel as material is assigned. When a chunk has more
     than the current order needs, split it — carry the leftover to the next
     order — and continue.
  3. Because one input chunk can span several orders, a **fresh `Chunk`** (same
     `item` and `avail_date`, the split-off portion of `qty`) is created for each
     `RawOrder.add_chunk` call, so the order records only the portion allocated
     to it (and classifies it on-time/late by its own `due_date`).

**Pseudo-code** (`days(δ) = δ.total_seconds() / 86400`; `self._chunks` is the
`DemandView` chunk list, kept sorted by `avail_date`):

```python
def recompute(self):
    for o in self.orders:
        o.allocated_qty = 0.0
        o.clear_chunks()
    by_due = sorted(self.orders, key=lambda o: o.due_date)
    i = 0                                          # earliest not-yet-full order
    for chunk in self._chunks:
        left = chunk.qty
        while left > 0 and i < len(by_due):
            o = by_due[i]
            need = o.remaining                     # init_qty - covered_on_hand - allocated_qty
            if need <= 0:                          # already satisfied
                i += 1
                continue
            take = min(left, need)
            o.allocated_qty += take
            o.add_chunk(Chunk(chunk.item, chunk.avail_date, take))   # fresh split chunk
            left -= take
            if take == need:                       # this order is now full
                i += 1
        # any leftover (left > 0 with every order full) is surplus RawView ignores

@property
def lateness(self):
    return sum(qty * self.late_base ** days(lag)
               for o in self.orders
               for (lag, qty) in o.late_table())
```

### `SafetyView[T]`

Tracks how well the current schedule maintains the item's desired inventory
levels — how long safety stock stays drained when it is dipped into, and how
long excess is carried when produced outside the ideal lead time. Distributes
the registered chunks across the item's `SafetyOrder[T]`s and against its
`Safety[T]`. The main entry point for finished-goods inventory-management
reporting. Constructed with the base `item` / `orders` plus the `safety_tgt`, the
`lead_time`, the initial `on_hand`, and `today`; builds a `Safety[T]` from
`safety_tgt`. The `on_hand` has two roles: it was already netted into each
order's/safety's `covered_on_hand` at `RlsItem` construction (used by the
chunk-distribution pass, which works against net requirements), and it enters the
physical pool the separate `drainage` pass simulates — as a fill event at
`today`. `today` also anchors the drainage window's start and pins past-due
orders (see below).

- `safety` — the `Safety[T]` requirement holding the safety-stock target and its
  current allocation (read-only). The total allocated to safety is its
  `allocated_qty` and the shortfall to target is its `remaining`, so the view
  exposes no separate `safety_pool` / `remaining_safety`.
- `carrying`, `drainage`, `excess` — the inventory-maintenance metrics defined
  below.

**`recompute()` — the distribution algorithm.** After resetting every
`SafetyOrder`'s `allocated_qty` to `0`, the safety allocation to `0`, and the
metrics to `0`, walk the chunks earliest → latest (by `avail_date`). For each
chunk, in priority order:

1. **Near-term demand.** Let `d` be the *latest* order `due_date` on or before
   `chunk.avail_date + lead_time`. Fill any still-unfilled demand for orders due
   through `d` (in due-date order) from the chunk.
2. **Safety.** If the chunk is not used up, put the extra toward safety stock, up
   to the `safety` requirement's `remaining` (raising its `allocated_qty`).
3. **Future demand.** If the chunk is still not used up, fill future orders
   (those due after `d`, in due-date order).
4. **Excess.** Any remainder is added to `excess`.

This distribution pass has no on-hand seeding — the on-hand was already netted
into each order's `covered_on_hand` at construction, so it distributes only
scheduled supply against net requirements, filling `safety` and accumulating
`carrying` and `excess`. `drainage` is then computed by a **separate** physical-pool pass
(see Metrics), which the distribution deliberately cannot do itself: while
distributing, it cannot know whether material it sends to safety will later be
drained by a future order.

**Pseudo-code — distribution pass** (`days` as above; `d` = the latest due date
on or before `horizon`, so "due `≤ horizon`" is exactly "due through `d`"):

```python
def recompute(self):
    for o in self.orders:
        o.allocated_qty = 0.0
    self.safety.allocated_qty = 0.0
    self._carrying = self._excess = 0.0

    by_due = sorted(self.orders, key=lambda o: o.due_date)
    for chunk in self._chunks:                     # sorted by avail_date
        left = chunk.qty
        horizon = chunk.avail_date + self.lead_time
        # (1) near-term demand: unfilled orders due on/before the horizon
        for o in by_due:
            if left <= 0: break
            if o.due_date <= horizon and o.remaining > 0:
                take = min(left, o.remaining)
                o.allocated_qty += take
                left -= take
        # (2) safety
        if left > 0:
            take = min(left, self.safety.remaining)
            self.safety.allocated_qty += take
            left -= take
        # (3) future demand -> carrying (held beyond the lead time)
        for o in by_due:
            if left <= 0: break
            if o.due_date > horizon and o.remaining > 0:
                take = min(left, o.remaining)
                o.allocated_qty += take
                left -= take
                self._carrying += take * days((o.due_date - chunk.avail_date) - self.lead_time)
        # (4) excess
        if left > 0:
            self._excess += left

    self._drainage = self._compute_drainage()      # separate physical-pool pass
```

**Metrics.** (`days(δ) = δ.total_seconds() / 86400`.)

- **`carrying`** — falls directly out of the chunk → *future*-order pairings the
  algorithm produces (step 3). For a quantity `q` of a chunk available at `a`
  applied to a future order due at `u` (`u > a + lead_time`), add
  `q × days((u − a) − lead_time)` — the time the material is held beyond its free
  lead-time window. Because a chunk only reaches a future order after near-term
  demand *and* safety are filled, carrying inherently accounts for the safety
  target (you cannot carry for a future order while safety is still short).
- **`drainage`** — the *risk* penalty for the schedule planning to run inventory
  **below the safety target**, deliberately distinct from `lateness`:
  - `lateness` (in `RawView`) is demand the schedule cannot meet by its due date
    at all — a *guaranteed* short-ship, the serious problem.
  - `drainage` is demand the schedule *does* meet, but only by drawing the safety
    buffer below target — leaving us exposed to unexpected fallout / quality
    problems (a *risk* of short-shipping) without guaranteeing a miss.

  It is computed by the separate physical-pool pass:
  1. Start the physical pool empty (`0`); it is reset on every `recompute`.
  2. Build a time-sorted **event list** (ties broken so *fill* events sort before
     *drain* events at the same timestamp):
     - a *fill* of `on_hand` at `today` (the on-hand enters the pool here);
     - each order a *drain* of its **full** `init_qty` at `max(due_date, today)`
       — orders already past due (`due_date < today`) are pinned to `today`, so
       no drainage is charged for pre-`today` spans (those orders are already
       late, and their penalties surface in `RawView`);
     - each chunk a *fill* of its `qty` at its `avail_date`.
  3. Walk the events, updating the pool at each. Between an event at `t1` that
     leaves the pool at `x1` and the next event at `t2`, add
     `max(0, min(safety_tgt, safety_tgt − x1)) × days(t2 − t1)` to `drainage`.
     `x1` is the raw physical quantity (negative when the pool is short), so the
     clamp keeps the deficit in `[0, safety_tgt]`: a pool below zero contributes
     at most `safety_tgt`, because the sub-zero shortfall is `lateness`, not
     drainage.
  4. Cap the window at the **last order `due_date`** — do not integrate past it
     (so the window runs from `today` to the last due date).

  Letting the on-hand enter at `today` and orders drain their full amounts is
  what accounts for on-hand in this pass (independently of the `covered_on_hand`
  netting the distribution pass uses); the drained buffer is thus whatever was
  physically on hand or produced earlier, exactly as intended.

  **Pseudo-code — drainage pass** (`days` as above):

  ```python
  def _compute_drainage(self):
      if not self.orders:
          return 0.0
      window_end = max(o.due_date for o in self.orders)   # cap at the last due date

      events =  [(self.today, +self.on_hand)]                          # on-hand fill at today
      events += [(max(o.due_date, self.today), -o.init_qty)            # full-amount drains
                 for o in self.orders]                                 #   (past-due pinned to today)
      events += [(c.avail_date, +c.qty) for c in self._chunks]         # chunk fills
      events.sort(key=lambda e: (e[0], 0 if e[1] > 0 else 1))          # fills before drains on ties

      total, pool = 0.0, 0.0
      for (t1, delta), (t2, _) in zip(events, events[1:]):
          pool += delta                                                # x1 = pool after this event
          lo, hi = max(t1, self.today), min(t2, window_end)            # clamp to [today, last due]
          if hi > lo:
              deficit = max(0.0, min(self.safety_tgt, self.safety_tgt - pool))
              total += deficit * days(hi - lo)
      return total
  ```
- **`excess`** — a plain scalar: the raw quantity produced beyond total demand
  plus safety replenishment (step 4). It gets no time-based penalty here (we
  cannot know how long it will be held); the *weight* of any excess penalty is
  out of scope for `demand`, which only reports the quantity.

`carrying` (per supply → future-order pairing, from the distribution pass) and
`drainage` (per inter-event span, from the physical-pool pass) are computed by
two different passes, reflecting their different concerns.

## The `requirement` submodule

The lightweight per-requirement classes (`Requirement` and its subclasses). No
separate `DESIGN.md`; documented in the subsections below.

### `Requirement[T]`

The abstract base for the whole hierarchy: a single quantity requirement on a
product item. Implements `HasID[str]` (keyed by its `id`). `item`, `init_qty`,
and `covered_on_hand` are supplied at construction and exposed read-only;
`allocated_qty` is settable; `remaining` is computed.

- `item` — the product style (`T`) this requirement is against.
- `init_qty` — the initial quantity required.
- `covered_on_hand` — how much of `init_qty` is already covered by on-hand
  inventory.
- `allocated_qty` — how much the current schedule has allocated to this
  requirement. Settable (starts at `0.0`), so the views can update it as they
  distribute jobs.
- `remaining` — computed as `max(0.0, init_qty - covered_on_hand -
  allocated_qty)`: the quantity still unmet after on-hand coverage and the
  current allocation.
- `id` — abstract; the concrete subclasses (`Safety`, `Order`) define the string
  format. `Requirement` itself is not instantiated directly.

### `Safety[T]`

Represents the remaining safety-stock replenishment still needed on an item.
Adds nothing to `Requirement` beyond the `id` format:

- `id` — `f'S@{self.item.id}'`.

### `Order[T]`

A single dated order. Extends `Requirement` with a due date and the release-week
offset it falls in.

- Construction — in addition to `Requirement`'s `item` / `init_qty` /
  `covered_on_hand`, takes `first_week` (a `(ISO year, ISO week)` pair
  identifying the first week of the material release) and `due_date` (a
  `datetime`). `week_offset` is derived from the two; `due_date` is stored as
  given.
- `due_date` — the order's due date (read-only).
- `week_offset` — read-only; how many ISO weeks after the release's `first_week`
  the `due_date` falls. Computed by taking the `due_date`'s ISO `(year, week)`
  (via `due_date.isocalendar()`) and counting whole ISO weeks from `first_week`
  to it. Because ISO years hold 52 or 53 weeks, when the years differ this is not
  a plain subtraction — the intervening years' week counts must be summed rather
  than assuming 52.
- `id` — `f'P{week_offset}-{iso_weekday}@{self.item.id}'`, where `iso_weekday` is
  the `due_date`'s ISO weekday (`due_date.isoweekday()`, Mon = 1 … Sun = 7).

### `SafetyOrder[T]` and `RawOrder[T]`

The two concrete `Order` subclasses.

- `SafetyOrder[T]` — one individual safety-stock replenishment order. Adds
  nothing to `Order`.
- `RawOrder[T]` — one individual hard-requirement order. The `RawView` records
  the chunks allocated to it, and the order reports late arrivals for supply that
  lands after its `due_date`. Internally it maintains **two sorted lists of
  chunks** — one for on-time supply (`avail_date <= due_date`) and one for late
  supply (`avail_date > due_date`), each kept in `avail_date` order:
  - `clear_chunks()` — empty both lists (called before the view re-distributes,
    so a `RawOrder` can be recomputed as the schedule changes).
  - `add_chunk(chunk)` — classify the chunk as on-time or late by comparing its
    `avail_date` to `due_date`, and insert it into the matching list in sorted
    order.
  - `late_fill_date` — derived from the late list: if the order is late, the date
    it will be filled (or the last date the schedule produces something against
    it); `None` if the order is not late.
  - `late_qty` — the total quantity in the late list (arriving after
    `due_date`).
  - `late_table()` — every late chunk, as `(time after due date, quantity)`
    pairs: `list[tuple[timedelta, float]]` (the `timedelta` is the lag past
    `due_date`, the `float` is that chunk's quantity).
