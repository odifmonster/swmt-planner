# Schedule / Machine Production — Design

Source of truth for the structure of `Activity`, `Status`, and `Machine`.
Captures decisions made before implementation so the planning logic stays in
one place and the demand-side cost layer can consume jobs without knowing how
they were produced.

## Purpose

For each knitting machine, model the sequence of work that actually happens on
the floor: jobs, beam swaps, and style changes. The submodule answers two
questions:

- **Where does production land in time?** Given an intent to produce N lbs of
  a greige item on a machine, what activities need to happen, in what order,
  and when does each start/end?
- **What state is the machine in at time T?** Beams on each bar, lbs left on
  each beam, current item/family, idle or not.

The schedule layer is the source of `Job` activities. The demand layer
(`RlsItem`) consumes them. The two layers are decoupled: schedule says
*when*, demand says *how expensive that when is*.

## Inputs

`Machine` is constructed with:

- `id` — machine identifier.
- `init_item` — greige item the machine is configured for at `start`.
- `start` — the `as_of` timestamp of the initial status (when the machine
  begins to be tracked).
- `init_top_beam`, `init_top_lbs` — beam currently on the top bar and lbs of
  yarn remaining on it.
- `init_btm_beam`, `init_btm_lbs` — same for the bottom bar.
- `workcal` — working-hours calendar; all activity start/end times respect it.
- `simple_change_duration` — how long a within-config style change takes on
  this machine.
- `family_change_duration` — how long a family change takes on this machine.
  Ignored when `is_new=True` (see below).
- `is_new` — `True` for newer/digital machines where switching to a different
  family takes the same brief reconfigure as a within-family style change.
  Defaults to `False` (legacy pattern-wheel machine, family changes are more
  expensive). New machines never emit `StyleChange(is_family_change=True)` —
  every style transition is reported as `is_family_change=False` so the
  costing layer doesn't apply a heavier weight to transitions that aren't
  actually heavier in hardware terms.

The constructor builds `initial_status` from these fields. The status is then
exposed read-only.

Module-level constants (constant across all machines):

- `TAPE_OUT_SINGLE_DURATION = 4 hours` — taping out one bar while the other
  is empty.
- `TAPE_OUT_BOTH_DURATION = 6 hours` — taping out both bars at once.
- `BEAM_LOAD_DURATION = 2 hours` — loading a fresh beam onto one bar.

Module-level function:

- `fresh_beam_lbs(beam: BeamSet) -> float` — the lbs of yarn on a freshly
  loaded beam, by yarn-denier convention. Low-denier beams (≤ 45D) hold
  **2800 lbs**; higher-denier beams hold **1800 lbs**. Used by
  `plan_production` whenever a `BeamLoad` is emitted; the values are a
  plant-wide convention rather than per-machine config. Lives at module
  level instead of on `BeamSet` because it is plant-specific operational
  knowledge (which beam stocks Shawmut keeps), and `BeamSet` is meant to
  stay plant-agnostic.

Activities are added via `add_activities(activities)`. Activities are
append-only — never removed. Planning (`plan_production`) is pure and does not
touch the activity list or status.

## Core objects

```
Activity (abstract)               # anything that occupies machine time
  start: datetime
  end: datetime

  Job(Activity)
    item: Greige
    lbs: float                    # always a multiple of item.tgt_wt

  Waste(Activity)
    item: Greige
    lbs: float                    # partial-roll fabric that gets discarded

  TapeOut(Activity)
    bars: Literal['top', 'btm', 'both']

  BeamLoad(Activity)
    bar: Literal['top', 'btm']
    beam: BeamSet
    lbs: float                  # yarn on the freshly loaded beam

  StyleChange(Activity)
    from_item: Greige
    to_item: Greige
    is_family_change: bool        # to_item.family != from_item.family

  Idle(Activity)                  # deliberate gap; machine committed to
                                  # not running due to staffing limits

Status                            # snapshot at a moment in time
  as_of: datetime
  top_beam: BeamSet | None
  btm_beam: BeamSet | None
  top_lbs_remaining: float
  btm_lbs_remaining: float
  current_item: Greige              # never None — machines are always
                                    # programmed to produce *something*
  is_idle: bool
  current_family: str               # derived from current_item

Machine (HasID)
  id, workcal
  initial_status: Status            # exposed read-only
  activities: tuple[Activity, ...]  # append-only
  current_status: Status            # status at the schedule tail
  simple_change_duration, family_change_duration
  is_new: bool                      # default False; True ⇒ no family changes emitted
  status_at(t) -> Status
  duration_of(spec) -> timedelta
  plan_production(item, lbs, start_at, idle_for=timedelta(0)) -> list[Activity]
  add_activities(activities) -> None
  # capacity + stopping-point queries
  producible_lbs_through(item, end, start=None) -> float
  producible_lbs_in_week(item, year, week, start=None) -> float
  next_job_end: datetime
  next_runout: datetime
```

`Status` is derived: `initial_status + activities -> current_status`. It is
never mutated directly. `status_at(t)` walks activities ≤ t; past the schedule
tail it returns the tail status with `is_idle=True`.

`is_idle` is informational only — it reports whether any activity is in
progress at `as_of`. **The planner does not consult `is_idle` when
deciding on changeovers.** Yarn stays threaded across idle gaps, so
changeover decisions depend purely on the threaded beam state (`top_beam`,
`btm_beam`) and `current_item`, never on whether the machine is currently
running.

Note: during an explicit `Idle` activity, `is_idle` is `False` because an
activity *is* in progress (just one that does nothing). This is consistent
with the "any activity in progress" semantic but worth flagging since the
naming reads backwards in that case. The planner doesn't care; only
consumers reading `Status` directly need to be aware.

## Activity durations

All durations are deterministic given (machine, activity spec).

| Activity | Duration |
|---|---|
| `Job(item, lbs)` | `lbs / item.get_rate_on_mchn(machine.id)` |
| `Waste(item, lbs)` | `lbs / item.get_rate_on_mchn(machine.id)` |
| `TapeOut('top')` or `TapeOut('btm')` | `TAPE_OUT_SINGLE_DURATION` |
| `TapeOut('both')` | `TAPE_OUT_BOTH_DURATION` |
| `BeamLoad(...)` | `BEAM_LOAD_DURATION` |
| `StyleChange(..., is_family_change=False)` | `machine.simple_change_duration` |
| `StyleChange(..., is_family_change=True)` | `machine.family_change_duration` |
| `Idle` | caller-supplied via `plan_production(..., idle_for=...)` |

Production rate is machine × item specific (via `Greige.get_rate_on_mchn`).
The two style-change durations are machine-specific because different
machines (manual pattern-wheel vs. digitally programmed) take different
amounts of time to reconfigure. Tape-out and beam-load are physical-handling
operations whose time does not vary meaningfully by machine.

## Beam-swap decision

The planner decides whether a transition needs beam work by checking **yarn
equality per bar**, not full `BeamConfig` equality:

```
no_swap_needed = (from_item.configuration.top_beam == to_item.configuration.top_beam
              and from_item.configuration.btm_beam == to_item.configuration.btm_beam)
```

`top_pct` / `btm_pct` differences do not trigger a swap — same yarn beams just
get drawn at different ratios for the new item. So
`top_lbs_remaining` / `btm_lbs_remaining` carry across same-yarn transitions
unchanged, and the next `Job` consumes them at the new item's ratios.

`StyleChange.is_family_change` is computed from family names and the
machine's `is_new` flag:

```
is_family_change = (not machine.is_new) and (from_item.family != to_item.family)
```

On a legacy machine (`is_new=False`), a family change with shared yarns
produces a `StyleChange(is_family_change=True)` with no surrounding beam work;
the machine still pays `family_change_duration` for the pattern-wheel /
programming reconfiguration. On a new machine (`is_new=True`), the same
transition is reported as `StyleChange(is_family_change=False)` — the
hardware reconfigure is the same brief setup as any other style change, so
flagging it as a family change would double-charge under any cost weight
that distinguishes family changes from simple ones.

## Roll-level production

The plant ships only two roll sizes: **whole rolls** of ~`Greige.tgt_wt`
lbs and **half rolls** of ~`tgt_wt / 2` lbs, each within tolerance of
its target weight. Yarn that doesn't fit those two discrete sizes is
waste.

When a beam exhausts mid-stream, the **half-roll rule** in
`_split_roll` partitions the remaining producible yarn:

- Producible close to `tgt_wt / 2`: yield one half-roll of that weight.
  Example: `producible=350, tgt_wt=700` ⇒ one 350-lb half-roll.
- Producible above the half-roll target: yield one half-roll of
  exactly `tgt_wt / 2`, the over-half remainder becomes Waste. Example:
  `producible=500, tgt_wt=700` ⇒ one 350-lb half-roll plus 150 lbs of
  Waste.
- Producible below the half-roll target (minus tolerance): too small
  for any roll, all Waste. Example: `producible=14, tgt_wt=700` ⇒ 14
  lbs of Waste.
- Producible near `N * tgt_wt` (within tolerance): N whole rolls
  summing to exactly `producible` lbs (each roll's weight may sit
  within tolerance of `tgt_wt`).

A Job's lbs is always whole rolls + at most one half-roll. `Job.rolls`
is the per-roll breakdown (see `Job` in `activity.py`). `Waste.lbs`
covers the discarded yarn; its duration is calculated at the same
production rate as a Job, and no doffing / cleanup activity is emitted
afterward.

`plan_production` is called with `lbs` already a multiple of `tgt_wt`
(the demand layer plans in whole-roll quantities, since all real orders
are for full rolls). The half-roll rule applies only to runout-induced
partials inside the production loop, not to the request shape.

Only `Job` activities reach the demand layer. `Waste` shows up on the
schedule for accurate machine occupation and end-time calculation but
is never registered with an `RlsItem`.

## The `plan_production` walk

Given `(item, lbs, start_at, idle_for)` and `current_status`, build the
activity list. `start_at` is one of:

- `'next_job_end'` — production of the new item begins at
  `current_status.as_of` (the schedule tail). The activity list contains
  only the changeover preamble and the new-item production loop.
- `'next_runout'` — the machine continues running its current item until
  the next beam exhausts, *then* changes over to the new item. The activity
  list begins with `Job`s (and possibly a `Waste`) of `current_item`,
  followed by the changeover preamble and the new-item production loop.

`lbs` always refers to the *new* item's production and is always a multiple
of `item.tgt_wt`. Any current-item production at the front of a runout-mode
plan is whatever happens to fit before exhaustion; it is independent of
`lbs`.

`idle_for` is a non-negative `timedelta` that, when positive, prepends an
`Idle` activity of that work-hour duration to the plan. Used to model
staff-constrained gaps where the machine sits unstaffed during what would
otherwise be work hours. The entire downstream plan needs an operator
(including the run-up in `'next_runout'` mode), so Idle precedes
everything else — it is emitted before the run-up, the preamble, and the
production loop.

The walk proceeds in four phases. Phase 0 is the optional Idle. Phase 1
depends on `start_at`. Phases 2 and 3 are unified across both modes.

### 0. Idle (optional)

If `idle_for > timedelta(0)`, emit `Idle(start=current_status.as_of, end=
workcal.offset_work_hours(current_status.as_of, idle_for))`. The working
status's `as_of` advances to that end time; beams, lbs, and current_item
are untouched.

### 1. Run-up (mode-dependent)

In `'next_job_end'` mode, no run-up activities are emitted. The **working
status** (the status against which the changeover preamble is computed) is
`current_status` directly.

In `'next_runout'` mode, walk forward producing the current item until a
beam exhausts:

```
current_item = current_status.current_item
producible = min(current_status.top_lbs_remaining / current_item.top_pct,
                 current_status.btm_lbs_remaining / current_item.btm_pct)
complete_rolls_lbs = (producible // current_item.tgt_wt) * current_item.tgt_wt
partial_lbs        = producible - complete_rolls_lbs

if complete_rolls_lbs > 0: emit Job(current_item, complete_rolls_lbs)
if partial_lbs > 0:        emit Waste(current_item, partial_lbs)
```

The working status after the run-up has at least one beam at zero (the
bar(s) that exhausted; possibly both if they exhausted simultaneously) and
`current_item` unchanged.

### 2. Changeover preamble

For each bar, the working status falls into one of three cases:

| Bar state | New item's yarn matches? | Activities for that bar |
|---|---|---|
| Has yarn | yes | (none) |
| Has yarn | no | `TapeOut` + `BeamLoad` |
| Empty (post-runout) | always needs a load | `BeamLoad` only |

A bar with yarn never escapes a tape-out when its yarn doesn't match — the
machine doesn't drop yarn unless we have a reason. This applies whether
the working status is from `'next_job_end'` mode (both bars always have
yarn) or `'next_runout'` mode (one or both bars now empty).

When both bars have yarn *and* both need swapping, emit a single
`TapeOut('both')` instead of two singles. `'both'` is only possible in
`'next_job_end'` mode; in `'next_runout'` mode at least one bar is empty,
so the most we can emit is a single `TapeOut('top'|'btm')`.

After all beam work (if any), if `working_status.current_item != item`,
emit `StyleChange(from_item=working_status.current_item, to_item=item,
is_family_change=((not machine.is_new) and
working_status.current_item.family != item.family))`.

### 3. Production loop

Let `remaining = lbs` and run:

```
while remaining > 0:
    producible = min(top_lbs_remaining / item.top_pct,
                     btm_lbs_remaining / item.btm_pct)

    if producible >= remaining:
        emit Job(item, remaining)
        remaining = 0
        break

    complete_rolls_lbs = (producible // item.tgt_wt) * item.tgt_wt
    partial_lbs        = producible - complete_rolls_lbs

    if complete_rolls_lbs > 0:
        emit Job(item, complete_rolls_lbs)
        remaining -= complete_rolls_lbs
    if partial_lbs > 0:
        emit Waste(item, partial_lbs)

    # whichever bar(s) exhausted, swap them
    emit BeamLoad for the exhausted bar(s)   # no TapeOut — already empty
    # if only one bar exhausted, the other carries lbs forward unchanged
```

If only one bar exhausts, the other's remaining lbs carry into the next
iteration. The planner does **not** preemptively swap a non-exhausted bar
at the same time — that is a scheduler-level optimization, not a planner
responsibility.

All emitted activities have `start` / `end` anchored to the schedule tail and
threaded through `workcal`. The walk does not mutate `current_status` or
`activities`.

## Capacity queries

High-volume items routinely run on multiple machines in parallel to meet
weekly demand. The demand layer cannot split production across machines
because production rate is item × machine specific — only the schedule layer
knows how much each machine can deliver.

```
machine.producible_lbs_through(item, end, start=None) -> float
machine.producible_lbs_in_week(item, year, week, start=None) -> float
```

`producible_lbs_through` returns the lbs of `item` the machine could
produce in the window `[start, end)`, starting at `start` (if provided)
or `current_status.as_of` and ending at `end`. Accounts for:

- Required changeover preamble if the machine's threaded state doesn't
  already match `item` (tape-outs, beam-loads, style-change).
- Mid-stream beam swaps within the window (each consumes
  `BEAM_LOAD_DURATION` only — natural exhaustion doesn't require taping
  the exhausted bar).
- `workcal` — only counts actual work hours in the window.
- Rounds down to a whole multiple of `item.tgt_wt`.

`start` lets the planner ask "if I delay production until time T, how
much of this item fits between now and `end`?". Common values are
`current_status.as_of` (the default; equivalent to `start=None`),
`next_runout`, and a carrying-avoidance idle target. `start <
current_status.as_of` is rejected — production can't begin before the
machine is ready.

Returns 0 if `start >= end`, if the changeover preamble alone exceeds
the available hours, or if the resulting capacity is less than one
full roll.

`producible_lbs_in_week` is a thin wrapper that picks `end =
week_end` for a given ISO week and snaps `start` up to `week_start`
if it falls earlier. It's preserved as a convenience for callers
that naturally think in ISO weeks. The infinite planner's candidate
enumerator uses `producible_lbs_through` directly, with a
conditional one-week bump when the current-week cap would be 0 — see
"Move sizing" in `planners/infinite/DESIGN.md`.

This is a **reporting** call. It does not cap or constrain `plan_production`.
The scheduler is responsible for sizing the `lbs` it passes to
`plan_production` based on these capacity reports. Letting `plan_production`
cap itself would couple weekly accounting into the planner and obscure the
contract that "you asked for N lbs, here are the activities for N lbs."

The scheduler typically queries every eligible machine with the same
`(item, year, week)`, then allocates the week's demand across machines based
on the reports.

## Natural stopping points

Two read-only properties expose moments when the machine is at a low-cost
transition boundary. The scheduler uses these to align placement decisions
with the floor's natural rhythm (don't cut into a roll, don't interrupt
mid-job).

```
machine.next_job_end: datetime
```

End time of the last scheduled activity. If no activities have been added,
returns `initial_status.as_of`. This is the schedule tail — the earliest
moment a newly planned activity can start.

```
machine.next_runout: datetime
```

Forward-extrapolated time at which top or btm beam will exhaust, assuming
`current_status.current_item` continues running from `current_status.as_of`.
Always well-defined: `current_item` is never `None`, and real greiges always
draw from both bars (`top_pct, btm_pct > 0`).

```
producible_before_runout = min(top_lbs_remaining / top_pct,
                               btm_lbs_remaining / btm_pct)
hours = producible_before_runout / current_item.get_rate_on_mchn(id)
next_runout = workcal.offset_work_hours(current_status.as_of, hours)
```

`next_runout` is a **prediction**. The run-out is not necessarily reflected
as activities on the machine's schedule yet — it just describes when the
current beam state, run forward, would force a swap.

## File I/O

The schedule submodule owns its own input format for machine setups.
Exported reader:

```
read_machines(
    path: Path, *, start_date: datetime, workcal: WorkCal,
    greige_by_id: dict[str, Greige],
) -> dict[str, Machine]
```

`path` points to a JSON file with one entry per machine. Per-entry
fields: machine id, initial item (resolved against `greige_by_id`),
the lbs remaining on each bar (`init_top_lbs`, `init_btm_lbs`),
`style_change_time` and `family_change_time` (decimal hours), and
`is_new`. The initial top and bottom beam yarns are *not* in the file
— they're derived from the resolved `Greige`'s `configuration`, since
a machine currently set up to run an item is by definition threaded
with that item's beams. `start_date` and `workcal` are plant-wide
rather than per-machine, so they're passed alongside the path.

No writer is exported from `schedule/`: per-machine schedules in the
output Excel are written by the top-level CLI from the `PlanReport`,
not by the schedule module itself.

## Test-placement contract

`plan_production` is pure; it returns a list of activities anchored against
`current_status` without mutating anything. The scheduler can score the plan
freely and discard if not committing.

```
plan = machine.plan_production(item, lbs, start_at)   # pure
# extract Job activities; in runout mode some may be for current_item
jobs = [a for a in plan if isinstance(a, Job)]
# group by item id so each RlsItem gets a single batch
jobs_by_item: dict[str, list[Job]] = {}
for j in jobs:
    jobs_by_item.setdefault(j.item.id, []).append(j)
# cost each batch against the right RlsItem; combine with schedule-side
# cost (changeover time, end-time, ...)
demand_cost_components = [
    rls_items[item_id].cost_if(batch)
    for item_id, batch in jobs_by_item.items()
]
```

If the scheduler decides to commit:

```
machine.add_activities(plan)
for item_id, batch in jobs_by_item.items():
    rls_items[item_id].register_jobs(batch)
```

`add_activities` is the only mutating call; it appends and rolls
`current_status` forward.

## Integration with demand

A single call to `plan_production` can produce **multiple `Job` activities**.
Two distinct mechanisms cause this:

- **Beam exhaustion** mid-loop splits one logical production into back-to-back
  `Job`s separated by a `BeamLoad`. All these `Job`s share the same `item`.
- **`'next_runout'` mode** prepends `Job`s of the *current* item (the run-up
  before changeover) to the new item's production. These `Job`s have a
  different `item` than the one passed to `plan_production`.

Each `Job` is registered with the `RlsItem` corresponding to its own
`job.item`, not the requested `item`. The scheduler maintains a lookup
from greige id to `RlsItem`, groups the emitted `Job`s by `job.item.id`,
and submits each group as a batch via `register_jobs(batch)` (or pre-
prices it via `cost_if(batch)`). Both demand-side methods accept a list
specifically to support this multi-Job case in a single update.

`Waste` activities are intentionally invisible to the demand layer. They
affect machine occupancy (and therefore the start times of later jobs on the
same machine) but contribute nothing to fulfillment accounting.

The demand layer does not split a week's required lbs across multiple
machines — it cannot, because production rate is item × machine specific. The
scheduler queries each candidate machine via `producible_lbs_in_week` and
allocates the week's demand across them. Each machine's contribution becomes
one or more `Job` activities on that machine, all registered against the same
`RlsItem`.

## Out of scope

- **Cross-machine scheduling** — `Machine` knows nothing about other
  machines. Picking *which* machine should run a given production is the
  scheduler's job.
- **Activity removal / rollback** — activities are append-only. The
  plan-then-commit contract above covers "what-if" without needing an
  unregister path.
- **Preemptive co-swapping** — when one bar exhausts mid-job and the other
  still has yarn, the planner does not opportunistically swap the second
  bar. The scheduler can drive that decision at a higher level if it wants.
- **Overlapping activities** — activities on a single machine are strictly
  sequential. Floor work that could in principle run in parallel (e.g.,
  taping out one bar while loading the other) is modeled by activity-type
  duration choices (`TapeOut('both')` is shorter than two single tape-outs
  sequentially), not by overlap.
- **Stochastic durations / breakdowns** — all durations are deterministic.
  Idle gaps not explained by `workcal` are not modeled.
- **Doffing / cleanup after waste** — negligible time, ignored.
