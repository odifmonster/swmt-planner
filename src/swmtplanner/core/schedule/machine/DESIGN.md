# machine — Design

`core.schedule.machine` defines the machines that hold the plant's schedules:
the abstract `State` and `Machine` bases plus the dye-planner specific pieces —
`JetState`, the `ShadeSeq` helper, and (later) the `Jet` machine itself.

> **Status:** fully designed — the `State` / `Machine` bases, `JetState` (the
> deferred type read by `Color.get_needed_strip`), `JetUpdate`, `ShadeSeq`,
> and `Jet`.

## Overview

The module is organized around two abstract bases. A `State` is a frozen
record snapshotting a machine's status at a point in time (`as_of`); instead
of mutating, it produces successor states (`apply_activity`). A `Machine`
holds a work calendar, a schedule of `Activity`s (from the sibling `activity`
submodule), and the jobs stored on it; internally it keeps the timeline of
states after each scheduled activity, recomputed whenever an activity is
inserted, and `state_as_of` walks that timeline to answer "what was the
machine's status at time *t*?".

The dye planner subclasses both bases: `JetState` carries the jet-specific
status (`max_prev_shade`, `cycles_since_strip`) and defines the per-activity
state transitions; `Jet(Machine, Observable[JetUpdate])` is the dye jet
itself, adding the insertion-point queries the dye planner schedules through. Alongside them, the `ShadeSeq` helper tracks one
contiguous run of non-strip cycles collapsed into shade groups, to spot the
natural places a new dye cycle can slot into a jet's schedule without adding
strips. A `ShadeSeq` holds no cycles of its own — it maintains index pointers
into the jet's schedule, kept in sync by observing (`Observer[JetUpdate]`,
from `support/observable`) the `JetUpdate` events the jet publishes as its
schedule changes.

Abstract members follow the project convention: no `ABC`, a deferred member
simply raises `NotImplementedError` in the base.

## Core objects

- Constants:
  ```python
  OVERLAP_TOL = timedelta(seconds=1)   # tolerance when checking schedule overlap

  SHIFT = 'SHIFT'      # JetUpdate labels
  INSERT = 'INSERT'
  REMOVE = 'REMOVE'
  ```
- Classes:
  ```python
  @dataclass(frozen=True)
  class State:                       # abstract
      as_of: datetime
      is_idle: bool
      current_item: Product | None
      def apply_activity(self, a: Activity) -> Self: ...   # raises NotImplementedError
                                                           # in the base

  class Machine:                     # abstract
      def __init__(self, workcal: WorkCal, init_state: State) -> None: ...
      @property
      def workcal(self) -> WorkCal: ...
      @property
      def state(self) -> State: ...           # the latest state
      @property
      def schedule(self) -> tuple[Activity, ...]: ...
      @property
      def jobs(self) -> tuple[Job, ...]: ...
      def state_as_of(self, t: datetime) -> State: ...
      def insert_activity(self, a: Activity) -> None: ...
      def insert_job(self, j: Job) -> None: ...

  @dataclass(frozen=True)
  class JetState(State):
      max_prev_shade: int | None
      cycles_since_strip: int
      def apply_activity(self, a: Activity) -> Self: ...

  @dataclass(frozen=True)
  class JetUpdate:
      label: str                                    # SHIFT / INSERT / REMOVE
      at_idx: int | None
      value: int | DyeCycle | EmptyCycle | None

  class ShadeSeq(Observer[JetUpdate]):
      def __init__(self, offset: int = 0,
                   init_pointers: dict[str, tuple[int, int]] | None = None) -> None: ...
      @property
      def offset(self) -> int: ...
      def group_start(self, shade: int) -> int: ...
      def group_end(self, shade: int) -> int: ...
      def update(self, value: JetUpdate) -> None: ...
      def split(self, at_idx: int) -> tuple[ShadeSeq, ShadeSeq]: ...

  class Jet(Machine, Observable[JetUpdate], HasID[str]):
      def __init__(self, id: str, workcal: WorkCal,
                   init_state: JetState) -> None: ...
      @property
      def id(self) -> str: ...
      @property
      def state(self) -> JetState: ...        # narrowed from Machine
      def try_insert_at(self, cycle: DyeCycle, idx: int) \
          -> tuple[list[Activity], list[DyeJob]]: ...
      def natural_insertions_for(self, color: Color,
                                 priority: Priority) -> list[int]: ...
      def on_time_insertions_for(self, color: Color, priority: Priority,
                                 due_date: datetime) -> list[int]: ...
  ```

## `State`

The abstract base for a machine's status at a single point in time. A frozen
dataclass — nothing edits a state in place; `apply_activity` produces the
successor state (and `dataclasses.replace` covers copy-with-field-overrides
where needed). Concrete subclasses are frozen dataclasses too, adding their
machine-specific fields on top of the base's.

- `as_of` — the `datetime` this state describes the machine at.
- `is_idle` — whether the machine is idle as of `as_of`.
- `current_item` — the `Product` the machine is currently running (`None` when
  it isn't running one).
- `apply_activity(a)` — return the successor state: the machine's status after
  `a` completes (its `as_of` is advanced past `a`, and the other attributes
  reflect the activity's effect). Abstract — raises `NotImplementedError` in
  the base; each concrete state defines the effects of the activity types its
  machine supports (typically building the result via `dataclasses.replace`).

## `Machine`

The abstract base for a machine holding a schedule. Constructed with its
`WorkCal` (see `support/workcal`) and its initial `State`; the schedule and
job list start empty.

Internally the machine keeps its **state timeline**: the initial state plus
the state after each scheduled activity, in order — each computed from its
predecessor via `apply_activity`. Inserting an activity recomputes the
timeline, so the machine's status at any time is derivable at any point.

- `workcal` — the machine's working calendar, a `WorkCal` (read-only).
- `state` — the machine's latest state: the last state on the timeline (the
  state after the final scheduled activity), or the initial state when the
  schedule is empty (read-only).
- `schedule` — the machine's scheduled activities, as a tuple in start order
  (read-only).
- `jobs` — the jobs stored on the machine, as a tuple (read-only).
- `state_as_of(t)` — the machine's status at time `t`: walk the state timeline
  and return the latest state whose `as_of` is on or before `t` (the initial
  state when `t` precedes the whole timeline).
- `insert_activity(a)` — insert `a` into the schedule (kept in start order)
  and recompute the state timeline: starting from the initial state, fold
  `apply_activity` across the schedule. Validates that `a` does not overlap
  any activity already on the schedule, within a small tolerance
  (`OVERLAP_TOL`, to absorb floating-point error in the date math): two
  activities overlap only when one starts more than `OVERLAP_TOL` before the
  other ends. Overlapping inserts raise `ValueError`.
- `insert_job(j)` — record `j` in `jobs`. This is storage only — a convenient
  place to keep the jobs associated with a machine; it does **not** touch the
  schedule or the state timeline.

## `JetState`

The dye jet's state — the concrete `State` for the dye planner, and the type
`Color.get_needed_strip` consumes (its documented interface lives in
`src/swmtplanner/core/product/DESIGN.md`). On top of the base fields it adds:

- `max_prev_shade` — the darkest shade still "present" on the jet, one of the
  shade-rating constants from `core.product`'s `fabric` submodule, or `None`
  when the jet is fully clean.
- `cycles_since_strip` — the number of cycles run on the jet since its last
  strip; `0` means the last activity was a strip.

**`apply_activity(a)`.** For **every** activity type: the current `as_of` must
have reached the activity's start — `as_of < a.start` raises `ValueError` —
and the successor's `as_of` is advanced to after `a`'s `end`. The other
effects depend on the activity:

- **`Idle`** — sets `is_idle` to `True` and `current_item` to `None`; changes
  nothing else.
- **`StripCycle`** — sets `max_prev_shade` to `None`, with one exception: a
  `BLACK` with `cycles_since_strip > 0` is left unchanged. (Regular black
  takes a double strip: the first strip after a black keeps `BLACK` while
  zeroing `cycles_since_strip`; a strip applied when `cycles_since_strip` is
  already `0` — the second consecutive strip — clears even a `BLACK`.) Sets
  `cycles_since_strip` to `0`, `is_idle` to `False`, and `current_item` to
  `None`.
- **`DyeCycle`** — sets `max_prev_shade` to the cycle's `color` shade if that
  shade is darker (see the darkness scale below) than the current value;
  increases `cycles_since_strip` by `1`; sets `is_idle` to `False`; sets
  `current_item` to the cycle's fabric (the `fabric` of the first lot in
  `lots`, when there are several).
- **`EmptyCycle`** — same `max_prev_shade` / `cycles_since_strip` updates as a
  `DyeCycle` (using the empty cycle's `color`); sets `is_idle` to `False` and
  `current_item` to `None`.

**Darkness.** "Darker" is judged on the darkness scale
`BLACK` > `SD_BLACK` > `MEDIUM` > `LIGHT` = `EXTRA_LIGHT` — the shade-rating
constants' numeric values are arbitrary identifiers, not a darkness ordering.
Regular black sits above solution-dyed black (only regular black demands the
double strip), which is what keeps `max_prev_shade == BLACK` when an
`SD_BLACK` runs after a regular black.

## `JetUpdate`

A basic frozen record describing one change to a jet's schedule — the event
type a `Jet` publishes (`Observable[JetUpdate]`) and a `ShadeSeq` observes.
An event is one of three kinds, named by the module-level label constants;
any attribute unused by an event's kind is `None`:

- `label` — the event kind: `SHIFT`, `INSERT`, or `REMOVE`.
- `at_idx` — `INSERT`/`REMOVE`: the index the event happened at, relative to
  the **jet's schedule**. `None` for a `SHIFT`.
- `value` — `SHIFT`: the `int` amount to shift the offset by. `INSERT`: the
  inserted `DyeCycle` / `EmptyCycle`. `None` for a `REMOVE`.

## `ShadeSeq`

A dye-planner helper tracking one **contiguous run of non-strip cycles**
(`DyeCycle`s / `EmptyCycle`s with no `StripCycle` between them) on a jet's
schedule. Its purpose is to make it easy to identify the natural space in the
schedule where a new dye cycle can be introduced **without adding strips**.

Within a run, cycles go lightest → darkest, so the run partitions into up to
three contiguous **shade groups** — the shades collapse into the three tiers
from `src/swmtplanner/core/product/DESIGN.md`: **light** (`EXTRA_LIGHT`,
`LIGHT`), **medium** (`MEDIUM`), **black** (`BLACK`, `SD_BLACK`) — and the
natural insertion points for a shade are exactly the positions inside/adjacent
to its tier's group.

A `ShadeSeq` stores no cycles of its own — it simply maintains **index
pointers** to places in the jet's schedule: its `offset` plus the start/end
insertion points of each shade group. It keeps them in sync with the jet by
implementing `Observer[JetUpdate]` and reacting to the events the jet
publishes. Group pointers are **sequence-local** (insertion positions from `0`
through the run's length); adding `offset` translates a local position to a
position in the jet's full activity schedule. The pointers strictly enforce
the group ordering invariant: `light.end <= medium.start` and
`medium.end <= black.start`.

- Construction — `ShadeSeq(offset=0, init_pointers=None)`. `init_pointers`
  optionally seeds the group start/end pointers: a dict keyed `'light'` /
  `'medium'` / `'black'` mapping each tier to its `(start, end)` **local**
  indexes (used by `split` to build the two halves). When omitted, the run
  starts empty (every group's pointers at `(0, 0)`).
- `offset` — the index in the jet's activity schedule of the run's first cycle
  (a run whose first cycle sits at schedule index 8 has offset 8). Read-only —
  it changes only via `SHIFT` events.
- `group_start(shade)` — the smallest natural index at which a cycle of the
  given shade could be inserted into the sequence: the stored start point of
  the shade's group. Exception: for an `EXTRA_LIGHT` shade it returns one
  **after** the light group's start — unless the light group is empty, in
  which case it returns the stored point as-is (an extra light cannot lead
  the light group: it has to follow a light-tier cycle — the priming rule in
  `Color.get_needed_strip`).
- `group_end(shade)` — the last natural insertion index for the given shade:
  the stored end point of the shade's group.
- `update(value)` — the `Observer[JetUpdate]` hook; dispatch on the event's
  `label`:
  - `SHIFT` — add the event's `value` to `offset`. Nothing else changes.
  - `INSERT` — the event's `at_idx` is relative to the jet's schedule, so
    subtract `offset` first to get the local index. Validate the inserted
    cycle (the event's `value`) can go there — the local index must lie
    within `[group_start, group_end]` for the cycle's `color` shade (using
    the extra-light-adjusted `group_start`), raising `ValueError` otherwise —
    then shift the stored group points (starts and ends both) up by `1`:
    every point strictly after the insertion point moves, and a point
    **equal** to it is tie-broken by the inserted cycle's shade — the cycle's
    tier says which groups fall before it and which after (via the ordering
    invariant above), so the points of lighter groups and the inserted
    tier's own start stay put, while the inserted tier's own end and the
    points of darker groups shift.
  - `REMOVE` — subtract `offset` from the event's `at_idx` to get the local
    index, then decrease every stored group point strictly after it by `1`.
    (A `REMOVE` carries no cycle, but no shade tie-break is needed: the
    removed cycle sat inside its group, so a point equal to the removed
    index is either that group's start or a lighter group's boundary — the
    points that must not move.)
- `split(at_idx)` — return two **new** `ShadeSeq`s cut at local index
  `at_idx`: the first keeps this run's `offset` and the pointers falling
  before `at_idx`; the second gets offset `offset + at_idx` and the remaining
  pointers, re-based to its own local `0` (each half's pointers are handed to
  the constructor via `init_pointers`). The original is unchanged. (This is
  what a mid-run strip insertion does to a run: it cuts it into two runs.)

## `Jet`

The dye jet — the dye planner's concrete machine. Subclasses both `Machine`
and `Observable[JetUpdate]`, and implements `HasID[str]`: its string `id` is
supplied at construction (this is the jet id that `Fabric.can_run_on_jet` /
`load_range_on_jet` key on). Constructed with its `id`, its `WorkCal`, and an
initial `JetState` (`state` is narrowed to return `JetState`).

**`ShadeSeq` maintenance.** The jet is responsible for maintaining and
updating its `ShadeSeq` objects — one per contiguous run of non-strip cycles
on its schedule. It keeps them subscribed to itself and translates its
schedule operations into `JetUpdate` events published to them: insertions
ahead of a run become `SHIFT`s, cycle insertions into a run become `INSERT`s,
removals become `REMOVE`s / `SHIFT`s, and a strip inserted mid-run cuts the
run's `ShadeSeq` in two (`split`). `natural_insertions_for` reads these
sequences to find strip-free space.

**Priority order.** Both insertion queries compare `Priority` values: lower
week offsets are more urgent; a `None` priority (an entirely-excess job)
always loses the contest, except against another `None`; safety (`'S'`) is
unrestricted.

- `try_insert_at(cycle, idx)` — a what-if evaluation: does **not** modify the
  jet's schedule; it returns what the schedule would gain from inserting the
  cycle at schedule index `idx`. If the jet's state at that point calls for
  preparation first (strips / an empty light cycle per
  `Color.get_needed_strip`), those cycles are part of the result and the dye
  cycle itself may land after `idx` rather than at it. Returns
  `(activities, jobs)`:
  - `activities` — only the **additional** activities the insertion creates
    (the dye cycle plus any needed `StripCycle`s / `EmptyCycle`); scheduled
    activities that merely shift later are not included.
  - `jobs` — the new `DyeJob`s the insertion creates (possibly several, when
    the dye cycle produces multiple items), plus the shifted jobs: jobs are
    frozen records, so each job pushed later by the insertion appears as a
    new record with the new times.
- `natural_insertions_for(color, priority)` — every **natural** insertion
  point (schedule index) for a new dye cycle of the given `color`: points
  that neither disrupt shade sequencing (forcing additional strips) nor
  schedule cycles out of priority order. A natural insertion point is always
  at the **end** of the color's shade group (per the jet's `ShadeSeq`s)
  unless priority order makes that undesirable. The priority rules:
  - a higher-priority order must never run after a lower-priority one — with
    the one exception that replacing an `EmptyCycle` with a dye cycle of the
    **same shade** is always allowed;
  - safety orders (priority `'S'`) can go anywhere.
- `on_time_insertions_for(color, priority, due_date)` — every insertion point
  (schedule index) where the new cycle could run **and be available by
  `due_date`**. Unlike the natural points, there is no restriction on
  interrupting shade sequences with additional strips — but priority order is
  still enforced: we don't make already-late orders even later in order to
  fulfill a less urgent order on time.
