# schedule — Design

`core.schedule` defines the properties of the various machines and the logic for
adding new jobs to the plant's schedule. It has two submodules:

- `activity` — schedule activities: the things that occupy a span of time on a
  machine's schedule.
- `machine` — the machines themselves. Has its own `DESIGN.md`.

Both submodules define the **generalized** objects plus the **dye-planner
specific** ones, since much of the functionality is planner-specific.

> **Status:** the `activity` submodule is designed below. The `machine`
> submodule is fully designed in its own `DESIGN.md`.

## Overview

The `activity` submodule is organized around one small base record, `Activity` —
a frozen record of a `start` and `end` time, uniquely identified
(`HasID[str]`) by an auto-generated id. Everything that sits on a machine's
schedule is an `Activity`. Three branches extend it:

- **Idling** — `Idle` represents a machine sitting idle for a span of time. It
  adds nothing to `Activity` and is generic: any machine can idle.

- **Cycles** — the individual runs a dye jet performs. `DyeCycle` is a
  productive run over a tuple of `DyeLot`s; `EmptyCycle` and `StripCycle` are
  the non-productive preparation cycles matching the `EMPTY` / `STRIP` jet
  activities `Color.get_needed_strip` returns (see
  `src/swmtplanner/core/product/DESIGN.md`).
- **Jobs** — `Job` is the generic unit of scheduled work: an `Activity`
  carrying a `priority` — a mutable `Priority` holder on the otherwise frozen
  record, set/reset by the demand module's `RlsItem` after each `recompute`;
  `DyeJob` is the dye-planner job, carrying the single `DyeLot` it produces.
  `Job` is the type the demand module's `RlsItem.register_job` hook was
  deferred against — the dye planner's `RlsItem` subclass converts a `DyeJob`
  into `Chunk`s (registering the job as the chunks' source).

The submodule also owns the cycle-time logic: a module-level constant for the
length of a strip cycle and a module-level function giving a color's cycle time
from its shade rating.

The `machine` submodule holds the machines those activities are scheduled on:
the abstract `State` / `Machine` bases and the dye-planner specific pieces
(`JetState`, `JetUpdate`, `ShadeSeq`, and `Jet`). It is documented in its own
`DESIGN.md`.

## Core objects

`core.schedule` defines no package-level constants, functions, or classes of its
own (so far); each concept lives in one of the submodules below.

### `activity` submodule

No dedicated `DESIGN.md`; documented here.

- Constants:
  ```python
  STRIP_CYCLE_HRS: float = 7   # length of a strip cycle, in hours
  ```
- Functions:
  ```python
  def cycle_time_for_color(color: Color) -> float: ...   # cycle time in hours
  ```
- Classes (`Priority` is a plain mutable holder; the rest are frozen records):
  ```python
  class Priority:
      def __init__(self, value: int | str | None) -> None: ...
      @property
      def value(self) -> int | str | None: ...
      @value.setter
      def value(self, value: int | str | None) -> None: ...   # a str must be 'S' (safety)

  @dataclass(frozen=True, eq=False)    # eq=False (here and on every subclass):
  class Activity(HasID[str]):          # HasID supplies id-based eq/hash
      start: datetime
      end: datetime
      _idx: int = field(default_factory=mk_counter(), kw_only=True)
      @property
      def id(self) -> str: ...         # f'{ClassName.upper()}{_idx:08d}'

  @dataclass(frozen=True)
  class Idle(Activity):
      ...                            # no additions

  @dataclass(frozen=True)
  class DyeCycle(Activity):
      lots: tuple[DyeLot, ...]
      @property
      def greige(self) -> str: ...
      @property
      def style(self) -> str: ...
      @property
      def color(self) -> Color: ...

  @dataclass(frozen=True)
  class EmptyCycle(Activity):
      color: Color

  @dataclass(frozen=True)
  class StripCycle(Activity):
      ...                            # no additions

  @dataclass(frozen=True)
  class Job(Activity):
      priority: Priority

  @dataclass(frozen=True)
  class DyeJob(Job):
      lot: DyeLot
  ```

### `machine` submodule

Has its own `DESIGN.md`; see
`src/swmtplanner/core/schedule/machine/DESIGN.md` for its core objects.

## The `activity` submodule

Schedule activities — the generic `Activity` base, the dye-jet cycles, the job
hierarchy, and the cycle-time constant/function. No separate `DESIGN.md`;
documented in the subsections below.

### Cycle times

- `STRIP_CYCLE_HRS` — the length of a strip cycle, in hours: `7`.
- `cycle_time_for_color(color)` — the cycle time, in hours, of dyeing the given
  `Color`, determined by its `shade_rating` (one of the shade-rating constants
  defined in `core.product`'s `fabric` submodule):
  - `BLACK` (non-solution-dyed black) — `10` hours.
  - `SD_BLACK` (solution-dyed black) — `6` hours.
  - all other shades — `8` hours.

### `Priority`

A convenience type: a small mutable holder that gives an otherwise frozen
record one settable value — the frozen record stores a reference to a
`Priority`, and the priority's `value` can be changed without mutating the
record itself.

- `value` — the priority value, `int | str | None`; settable. An `int` is a
  demand week offset; when a string, the only valid value is `'S'` (safety) —
  any other string raises `ValueError`; `None` is the cleared state (no
  requirement filled). Supplied (and validated the same way) at construction.

### `Activity`

The generic base: a frozen record of a single span of time occupied on a
machine's schedule. Implements `HasID[str]` — `Activity` and every subclass
are declared `eq=False` so `HasID`'s id-based `__eq__` / `__hash__` apply
rather than the dataclass's field-wise equality.

- `start` — when the activity begins (a `datetime`).
- `end` — when the activity ends (a `datetime`).
- `_idx` — a private `int` field whose default factory pulls the next value
  from a single module-level counter (a `support.counters.mk_counter()`)
  shared by all activity classes. Declared keyword-only (with its default,
  it would otherwise block subclasses from adding positional fields after
  it).
- `id` — a read-only property formatting the private field: the concrete
  class's name in all upper case followed by the 8-digit zero-padded `_idx` —
  e.g. `'DYECYCLE00000004'`, `'IDLE00000007'`.

### `Idle`

A frozen record representing a machine idling for a period of time. Adds
nothing to `Activity`. Generic — any machine can idle.

### `DyeCycle`

A frozen record for one productive dye run: the `DyeLot`s dyed together in a
single cycle on a jet.

- `lots` — the `DyeLot`s run in the cycle, as a tuple. All three computed
  properties below must be well defined: construction raises `ValueError` when
  any of them cannot be derived (e.g. no lots, or a lot with no assigned
  `Fabric`), and likewise when the lots don't share a value for all three.
- `greige` — computed from `lots`: the shared greige style string of the lots.
- `style` — computed from `lots`: the shared `style` string of the lots'
  assigned `Fabric`s.
- `color` — computed from `lots`: the shared `Color` of the lots' assigned
  `Fabric`s.

### `EmptyCycle`

A frozen record for one empty light cycle — the `EMPTY` preparation activity
`Color.get_needed_strip` calls for before an `EXTRA_LIGHT` color: a light cycle
run with no lots in the jet.

- `color` — the `Color` the empty cycle is run with.

### `StripCycle`

A frozen record for one strip (cleaning) cycle — the `STRIP` preparation
activity `Color.get_needed_strip` returns. Adds nothing to `Activity`; its
length is `STRIP_CYCLE_HRS`.

### `Job` and `DyeJob`

The unit of scheduled work.

- `Job` — the generic job: a frozen record adding one field to `Activity`:
  - `priority` — the job's `Priority`. The record itself is frozen; the
    priority's `value` is owned by the `RlsItem` the job is registered with
    (see `src/swmtplanner/core/demand/DESIGN.md`): each `recompute` clears it
    to `None`, then sets `'S'` when the job's supply first fills safety stock,
    or the `week_offset` of the first order it fills. A value still `None`
    after a `recompute` marks the job as entirely excess — nothing it produced
    filled any requirement.

  This is the type referenced (as a deferred interface) by
  `RlsItem.register_job` in `core.demand`.
- `DyeJob` — the dye-planner job. Adds:
  - `lot` — the single `DyeLot` the job produces.

## The `machine` submodule

The machines the activities are scheduled on — the abstract `State` and
`Machine` bases plus the dye-planner specific `JetState`, `JetUpdate`,
`ShadeSeq`, and `Jet`.

See `src/swmtplanner/core/schedule/machine/DESIGN.md`.
