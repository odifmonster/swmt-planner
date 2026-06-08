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

The schedule layer is the source of `Job` records (in each machine's
production schedule — see Core objects). The demand layer (`RlsItem`)
consumes them. The two layers are decoupled: schedule says *when*
each roll lands, demand says *how expensive that when is*.

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
- `is_new` — `True` for newer/digital machines, where every changeover is a
  single uniform reconfigure regardless of pattern family. Defaults to `False`
  (legacy pattern-wheel machine). The flag selects the changeover activity
  type: a new machine always emits a `StyleChange`; a legacy machine emits a
  `RunnerChange` within a pattern family or a `PatternChange` across families
  (see "Beam-swap decision"). Changeover durations are no longer per-machine —
  they are module-level constants (see Constants), so the constructor no
  longer takes `simple_change_duration` / `family_change_duration`.

The constructor builds `initial_status` from these fields. The status is then
exposed read-only.

Module-level function:

- `fresh_beam_lbs(beam: BeamSet) -> float` — the lbs of yarn on a freshly
  loaded beam, by yarn-denier convention (the threshold and per-denier lbs
  are module-level constants — see the Constants section). Used by
  `plan_production` whenever a fresh beam is hung (a `Hanging`) to set that
  bar's lbs; the values are a plant-wide convention rather than per-machine
  config. Lives at module
  level instead of on `BeamSet` because it is plant-specific operational
  knowledge (which beam stocks Shawmut keeps), and `BeamSet` is meant to
  stay plant-agnostic.

Activities are added via `add_activities(activities)`. Activities are
append-only — never removed. Planning (`plan_production`) is pure and does not
touch the activity list or status.

## Core objects

A `Machine` carries two parallel schedules: an **activity schedule**
(the timeline of physical machine activities — `Knit`, `Waste`, `Doff`,
`TapeOut`, `Hanging`, `Threading`, the changeover activities
(`StyleChange` / `RunnerChange` / `PatternChange`), and `Idle`) and a
**production schedule** (a list of `Job` records, each grouping the rolls
produced
by one call to `plan_production`). The two are decoupled: only the
activity schedule drives machine `Status`; only the production
schedule is what the demand layer consumes.

```
Activity (abstract)               # anything that occupies machine time
  start: datetime
  end: datetime

  Knit(Activity)                  # a continuous block of fabric production at
                                  # the machine's current item rate — one
                                  # `Knit` per uninterrupted run between beam
                                  # events. A roll may straddle a beam swap,
                                  # so a `Knit` can end mid-roll.
    item: Greige
    lbs: float                    # arbitrary; bounded by the usable yarn knit
                                  # before the next beam event (not constrained
                                  # to whole rolls or halves)

  Waste(Activity)                 # usable yarn discarded from a swapped-out
                                  # beam — removed unknit (zero machine time),
                                  # not fabric the machine ran. Applying it
                                  # empties the named `bar` (beam -> None,
                                  # lbs -> 0); a paired re-thread refills it.
    beam: BeamSet                 # the yarn SKU being discarded (the beam that
                                  # was on `bar`) — what's wasted is yarn, not a
                                  # greige; relevant for future beam-set
                                  # inventory tracking
    bar: Literal['top', 'btm']    # which bar's residual is discarded
    lbs: float                    # usable residue on `bar` (lbs_remaining(bar) - floor),
                                  # below the max-waste threshold, discarded
                                  # unknit when the beam is swapped

  Doff(Activity)                  # removing one completed roll from the
                                  # machine. Fieldless beyond start/end
                                  # (mirrors `Idle`'s shape; a distinct class
                                  # for readability). One `Doff` per completed
                                  # roll; invariant: Doff.end == that roll's
                                  # completion_time.

  TapeOut(Activity)               # forced removal of yarn from one/both bars,
                                  # preserved (not discarded) for re-use. Also
                                  # records the beam SKU(s) removed, per bar,
                                  # for future beam-set inventory tracking.
    bars: Literal['top', 'btm', 'both']
    top_beam: BeamSet | None      # SKU removed from top (None if top untouched)
    btm_beam: BeamSet | None      # SKU removed from btm (None if btm untouched)

  Hanging(Activity)               # mounting fresh beam set(s) onto the named
                                  # bar(s) — this is what loads the physical
                                  # set, so it sets each bar's beam and lbs and
                                  # leaves the bar un-threaded. Requires the
                                  # old set already gone (see "Beam-swap
                                  # sequencing"). Pairs with a Threading.
    bars: Literal['top', 'btm', 'both']  # which bar(s) this loads
    top_beam: BeamSet | None      # beam now loaded on top (None if untouched)
    top_lbs: float                # yarn on the freshly loaded top beam
    btm_beam: BeamSet | None
    btm_lbs: float

  Threading(Activity)             # routing the loaded yarn into the machine.
                                  # Flips the bar(s) to threaded — sets
                                  # `threaded(bar) = True` and nothing else.
                                  # Requires the bar(s) already hung (loaded
                                  # but not yet threaded). Together, Hanging +
                                  # Threading replace the old single `BeamLoad`.
    bars: Literal['top', 'btm', 'both']  # which bar(s) this threads

  # Changeovers — replace the single `StyleChange`. The class itself carries
  # the changeover semantic (there is no is_family_change flag); which one is
  # emitted depends on `machine.is_new` and the pattern-family comparison
  # (see "Beam-swap decision"). All three share the same two fields.
  StyleChange(Activity)           # new machine (is_new): one uniform
                                  # reconfigure regardless of pattern family
    from_item: Greige
    to_item: Greige

  RunnerChange(Activity)          # legacy machine, same pattern family —
                                  # the lighter runner reconfigure
    from_item: Greige
    to_item: Greige

  PatternChange(Activity)         # legacy machine, different pattern family —
                                  # the heavier pattern-wheel rework
    from_item: Greige
    to_item: Greige

  Idle(Activity)                  # deliberate gap; machine committed to
                                  # not running due to staffing limits

Roll                              # one completed roll. Pure data; no
                                  # machine-state effect.
  lbs: float                      # actual weight of the roll
  completion_time: datetime       # when the roll is ready to ship

Job (HasID)                       # an "order" for some number of rolls of
                                  # an item on a machine, fulfilled by one
                                  # call to `plan_production`. Records the
                                  # rolls that the call produced (each with
                                  # its own completion time) and the item
                                  # being knit. Pure data — no start/end of
                                  # its own and no effect on machine
                                  # `Status`. Lives on the production
                                  # schedule (`Machine.jobs`), not on the
                                  # activity schedule.
  item: Greige
  rolls: tuple[Roll, ...]
  total_rolls: int                # computed: len(rolls)
  total_lbs: float                # computed: sum(roll.lbs for roll in rolls)

ProductionPlan                    # return value of plan_production —
                                  # the activity-schedule and
                                  # production-schedule additions for one
                                  # planning call. The scheduler commits
                                  # both halves together via
                                  # `add_activities` + `add_jobs`.
  activities: tuple[Activity, ...]
  jobs: tuple[Job, ...]

Status                            # snapshot at a moment in time. Per-bar
                                  # values are read through accessors taking a
                                  # bar literal ('top' | 'btm') — there are no
                                  # separate top_*/btm_* fields.
  as_of: datetime
  beam(bar) -> BeamSet | None       # mounted beam SKU on `bar` (None after a
                                    # remove, before the re-thread)
  lbs_remaining(bar) -> float       # yarn left on `bar`'s beam
  threaded(bar) -> bool             # `bar`'s set is threaded (routed) and
                                    # ready to knit — set True by Threading,
                                    # reset False by Hanging (and by removal)
  current_item: Greige              # never None — machines are always
                                    # programmed to produce *something*
  is_idle: bool
  current_family: str               # derived from current_item

Machine (HasID)
  id, workcal
  initial_status: Status            # exposed read-only
  activities: tuple[Activity, ...]  # activity schedule; append-only
  jobs: tuple[Job, ...]             # production schedule; append-only
  current_status: Status            # status at the activity-schedule tail
  is_new: bool                      # default False; selects StyleChange (new)
                                    # vs RunnerChange / PatternChange (legacy)
  status_at(t) -> Status
  duration_of(spec) -> timedelta
  plan_production(item, lbs, start_at, idle_for=timedelta(0)) -> ProductionPlan
  add_activities(activities) -> None
  add_jobs(jobs) -> None
  # capacity + stopping-point queries
  producible_lbs_through(item, end, start=None) -> float
  producible_lbs_in_week(item, year, week, start=None) -> float
  schedule_tail: datetime           # end time of the last activity on the
                                    # activity schedule (the earliest moment
                                    # a new activity can start). Renamed
                                    # from `next_job_end` now that `Job` no
                                    # longer refers to an activity.
  next_runout: datetime
```

A `Job` corresponds one-to-one with a `plan_production` call: the
caller asks for `lbs` worth of rolls of `item`, and the planner
returns a `Job` whose `rolls` list captures every roll that the
call produced (the call also returns the activity-schedule
additions separately as part of the `ProductionPlan`). Unlike a
`Knit` activity — which is a single uninterrupted run on the
machine — a `Job` can span one or more beam swaps: when a beam
exhausts mid-production, the current `Knit` ends, the bar is
re-threaded (a `Hanging` + `Threading`), the next `Knit` begins,
and rolls completed across the sequence all land on the same `Job`. The same plan_production
call may also yield a second `Job` in `'next_runout'` mode (the
run-up's whole rolls of the current item, distinct from the new
item's `Job`).

The demand layer reads `Job.rolls` to learn when each roll lands;
it never inspects machine activities directly. The costing layer,
which used to filter `Job` instances out of `Machine.activities`
to find rolls, now consumes `Machine.jobs` directly.

`Status` is derived: `initial_status + activities -> current_status`. It is
never mutated directly. `status_at(t)` walks activities ≤ t; past the schedule
tail it returns the tail status with `is_idle=True`. The production
schedule (`jobs`) has no effect on `Status` and isn't consulted by
`status_at`.

`is_idle` is informational only — it reports whether any activity is in
progress at `as_of`. **The planner does not consult `is_idle` when
deciding on changeovers.** Yarn stays threaded across idle gaps, so
changeover decisions depend purely on the threaded beam state (`beam('top')`,
`beam('btm')`) and `current_item`, never on whether the machine is currently
running.

Note: during an explicit `Idle` activity, `is_idle` is `False` because an
activity *is* in progress (just one that does nothing). This is consistent
with the "any activity in progress" semantic but worth flagging since the
naming reads backwards in that case. The planner doesn't care; only
consumers reading `Status` directly need to be aware.

### Beam-swap sequencing (guard rails)

Splitting a beam swap into three steps — **remove** the old set (`TapeOut`,
`Waste`, or knitting it down to the floor), **hang** the fresh set
(`Hanging`, which loads the new beam + lbs), then **thread** it (`Threading`,
which routes the yarn) — means those steps must occur in order on a given
bar. `Status.apply_activity` enforces the order and raises if an activity is
applied out of sequence, so a malformed activity list can't silently produce
an impossible machine state.

Per bar, predicates of the (pre-activity) status drive the checks:

- **removed** — the old set is gone or spent: `beam(bar) is None` (after an
  explicit `TapeOut` / `Waste`) **or** `lbs_remaining(bar) <= BEAM_FLOOR_LBS`
  (knit down to the floor at a run-out). A removed bar is ready to hang.
- **threaded** — `threaded(bar)` is set: the loaded set's yarn is routed and
  ready to knit. A bar holding a freshly hung set that isn't yet threaded
  (`not removed and not threaded`) is **hung**.

The per-bar transitions and their guards:

- **`Hanging(bar, beam, lbs)`** — requires the bar **removed**; otherwise
  raises (hanging onto a bar that still holds a usable set, or hanging
  twice). Effect: loads the fresh set — sets `beam(bar)` and
  `lbs_remaining(bar)` — and leaves it un-threaded (`threaded(bar)` False),
  since a newly mounted set hasn't been routed yet.
- **`Threading(bar)`** — requires the bar **hung** (`not removed and not
  threaded`); otherwise raises (threading before hanging, or threading an
  already-threaded bar). Effect: `threaded(bar)` becomes True, nothing else.
- **`TapeOut(bar)` / `Waste(bar)`** — remove the old set: `beam(bar)` → None,
  `lbs_remaining(bar)` → 0, `threaded(bar)` → False.

The `'both'` variants apply the same per-bar checks to each bar. A
freshly-constructed machine is threaded and running, so both bars start
threaded (`threaded(bar)` is True).

## Activity durations

All durations are deterministic given (machine, activity spec).

| Activity | Duration |
|---|---|
| `Knit(item, lbs)` | `lbs / item.get_rate_on_mchn(machine.id)` |
| `Waste(beam, bar, lbs)` | `timedelta(0)` — yarn is swapped out unknit, not run |
| `Doff` | `DOFF_DURATION` |
| `TapeOut('top')` or `TapeOut('btm')` | `TAPE_OUT_SINGLE_DURATION` |
| `TapeOut('both')` | `TAPE_OUT_BOTH_DURATION` |
| `Hanging('top')` or `Hanging('btm')` | `HANGING_SINGLE_DURATION` |
| `Hanging('both')` | `HANGING_BOTH_DURATION` |
| `Threading('top')` or `Threading('btm')` | `THREADING_SINGLE_DURATION` |
| `Threading('both')` | `THREADING_BOTH_DURATION` |
| `StyleChange` | `STYLE_CHANGE_DURATION` |
| `RunnerChange` | `RUNNER_CHANGE_DURATION` |
| `PatternChange` | `PATTERN_CHANGE_DURATION` |
| `Idle` | caller-supplied via `plan_production(..., idle_for=...)` |

Production rate is machine × item specific (via `Greige.get_rate_on_mchn`).
Every other duration is now a plant-wide module-level constant (see
Constants) — including the three changeover durations, which used to be
per-machine. The `is_new` flag and the pattern-family comparison select
*which* changeover activity is emitted (and hence which duration constant
applies), rather than scaling a per-machine value. Tape-out, hanging,
threading, and doff are physical-handling operations whose time does not vary
meaningfully by machine.

## Constants

Module-level constants (defined in `activity.py` / `machine.py`).

**Fixed activity durations** — physical-handling operations whose time does
not vary meaningfully by machine (referenced by name in the durations table
above):

- **`TAPE_OUT_SINGLE_DURATION = 2h`** — a single-bar `TapeOut`.
- **`TAPE_OUT_BOTH_DURATION = 3h`** — a `TapeOut('both')`; cheaper than two
  separate singles (shared setup) but more than one, since the floor can't
  fully parallelize the cuts.
- **`HANGING_SINGLE_DURATION = 1h`** / **`HANGING_BOTH_DURATION = 1.5h`** —
  physically mounting a fresh beam on one bar / both bars.
- **`THREADING_SINGLE_DURATION = 2h`** / **`THREADING_BOTH_DURATION = 3.5h`**
  — routing yarn into the machine for one bar / both bars. `Hanging` +
  `Threading` together replace the old single `BEAM_LOAD_DURATION = 2h`.
- **`DOFF_DURATION = 20min`** — removing one completed roll.

**Changeover durations** (Step 3) — plant-wide, previously the per-machine
`simple_change_duration` / `family_change_duration`. The `is_new` flag and
the pattern-family comparison pick which one applies (see "Beam-swap
decision"):

- **`STYLE_CHANGE_DURATION = 5min`** — a new machine's uniform reconfigure.
- **`RUNNER_CHANGE_DURATION = 45min`** — a legacy machine's
  within-pattern-family runner change (the lighter case).
- **`PATTERN_CHANGE_DURATION = 1.5h`** — a legacy machine's
  cross-pattern-family pattern-wheel rework (the heavier case).

**Fresh-beam yarn** — plant-wide convention for how much yarn a freshly loaded
beam holds, by yarn denier (used by `fresh_beam_lbs`):

- **`LOW_DENIER_FRESH_LBS = 2800`** — lbs on a fresh low-denier (≤ 45D) beam.
- **`HIGH_DENIER_FRESH_LBS = 1800`** — lbs on a fresh higher-denier beam.
- **`LOW_DENIER_THRESHOLD = 45`** — denier at or below which a beam counts as
  low-denier.

**Runout model** (Step 2) — tunable, to be calibrated against real floor
behavior:

- **`BEAM_FLOOR_LBS = 5`** — residue that can't be knit off a beam. A beam is
  never run to zero; the usable yarn on a bar is
  `usable = lbs_remaining(bar) - BEAM_FLOOR_LBS`.
- **`MAX_BEAM_WASTE_LBS = 100`** — the operator won't knit through a
  near-empty beam: when a bar's `usable` falls below this, the bar is
  swapped — its residual discarded as `Waste` — before the next roll
  starts, rather than knit down further.

## Beam-swap decision

The planner decides whether a transition needs beam work by checking **yarn
equality per bar**, not full `BeamConfig` equality:

```
no_swap_needed = (from_item.configuration.top_beam == to_item.configuration.top_beam
              and from_item.configuration.btm_beam == to_item.configuration.btm_beam)
```

`top_pct` / `btm_pct` differences do not trigger a swap — same yarn beams just
get drawn at different ratios for the new item. So
`lbs_remaining('top')` / `lbs_remaining('btm')` carry across same-yarn
transitions unchanged, and the next `Knit` consumes them at the new item's
ratios.

When the item changes, *which* changeover activity is emitted is selected
from `machine.is_new` and the pattern-family comparison. The activity class
carries the semantic directly — there is no `is_family_change` flag:

```
if machine.is_new:
    change = StyleChange(from_item, to_item)      # uniform reconfigure
elif from_item.family == to_item.family:
    change = RunnerChange(from_item, to_item)     # legacy, same pattern family
else:
    change = PatternChange(from_item, to_item)    # legacy, cross pattern family
```

A **new** machine always emits a `StyleChange`, regardless of family: its
hardware reconfigure is the same brief setup either way, so it never incurs
the heavier cross-family rework. A **legacy** machine emits a `RunnerChange`
within a pattern family (the lighter runner reconfigure) or a `PatternChange`
across pattern families (the heavier pattern-wheel rework). Each activity's
duration is its own module-level constant (see Constants); the *selection* —
not a per-machine duration — is what distinguishes the cases, and the cost
layer weights the three activity types independently. A changeover with
shared yarns emits its change activity with no surrounding beam work; only a
yarn mismatch (per the yarn-equality check above) adds tape-out / re-thread
work.

## Roll-level production

The plant ships **whole rolls** of ~`Greige.tgt_wt` lbs (within tolerance of
the target weight). `plan_production` is called with `lbs` already a multiple
of `tgt_wt` (the demand layer plans in whole-roll quantities, since all real
orders are for full rolls), so every roll a call produces is a whole roll.
There are no half rolls and no run-out-induced partials.

**A `Knit` is one uninterrupted run of knitting** — the fabric wound between
two consecutive interruptions (a doff, a beam swap, or the start/end of the
run). It is bounded above by a single roll (`0 < Knit.lbs <= tgt_wt`):
knitting stops at every roll boundary for a `Doff`, and can also stop
mid-roll for a beam swap. A `Knit` no longer spans multiple rolls the way it
did before doffs were modeled.

**Every completed roll ends in a `Doff`.** Once a roll's final lbs are wound,
a `Doff` (`DOFF_DURATION`) takes it off the machine before the next roll
starts. A roll is "ready to ship" when it comes off, so its `completion_time`
is the **`Doff`'s end** (`Doff.end == Roll.completion_time`) — not the moment
its last lb was knit. Exactly one `Doff` is emitted per completed roll,
regardless of how many `Knit`s produced it. Because each doff occupies machine
time, it pushes every subsequent roll (and the schedule tail) later.

**Rolls straddle beam swaps.** A beam is never knit to zero, and a roll is
never cut short at a runout. When a bar reaches `BEAM_FLOOR_LBS` partway
through a roll, that bar is re-threaded (a `Hanging` + `Threading`) and the
*same* roll keeps winding on the fresh beam up to its full `tgt_wt`:

- Example (`tgt_wt = 700`): a bar with 430 usable lbs of capacity left
  mid-roll ⇒ `Knit(430)`, then `Hanging` + `Threading`, then `Knit(270)`
  finishing the roll, then a `Doff`. Both `Knit`s lie within `(0, tgt_wt]`.
- A roll that needs no mid-roll swap is simply `Knit(tgt_wt)` + `Doff`.
- The roll is still a whole roll (~`tgt_wt`); only its winding is split
  across the swap. Its `completion_time` is its `Doff.end`.

`Waste` is not knitted fabric. It is the **usable residue on a beam the
planner swaps early** — when a bar's `usable` (`lbs_remaining(bar) - BEAM_FLOOR_LBS`)
falls below `MAX_BEAM_WASTE_LBS`, that yarn is discarded unknit (see the
max-waste rule in the production loop). `Waste` carries the discarded `beam`
SKU and its `bar`, has zero duration, and emits **no `Doff`** — a doff
attends a completed roll, not discarded yarn.

Across a single `plan_production` call, every (whole) roll produced is
recorded as a `Roll(lbs, completion_time)` entry on the same `Job` record
(its `completion_time` being the roll's `Doff.end`), which the call returns
alongside the activity list.

Only `Job` records reach the demand layer. `Knit`, `Doff`, `Waste`, and the
other activity types affect machine occupation and end-time calculation but
are never registered with an `RlsItem`.

## The `plan_production` walk

Given `(item, lbs, start_at, idle_for)` and `current_status`, build a
`ProductionPlan` carrying both the activity-schedule additions
(`Knit`s, `Doff`s, `Hanging`s, `Threading`s, `Waste`s, etc.) and the
production-schedule additions (one or two `Job` records). `start_at` is one
of:

- `'schedule_tail'` — production of the new item begins at
  `current_status.as_of` (the activity-schedule tail). The activity
  list contains only the changeover preamble and the new-item
  production loop, and the call yields one `Job` for the new item.
- `'next_runout'` — the machine continues running its current item until
  the next beam exhausts, *then* changes over to the new item. The
  activity list begins with the run-up's `Knit`/`Doff` pairs of
  `current_item`, followed by the changeover preamble and the
  new-item production loop. The call yields one `Job` for the
  current item's run-up rolls plus one for the new item (or only the
  new-item `Job` if the run-up produced no whole rolls).

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

In `'schedule_tail'` mode, no run-up activities are emitted. The
**working status** (the status against which the changeover preamble
is computed) is `current_status` directly.

In `'next_runout'` mode, the run-up produces the current item toward a beam
runout — but only in **whole rolls**. It never starts a roll the current
beams can't finish above the floor, so it never strands the machine mid-roll
at the changeover:

```
current_item = current_status.current_item
top_usable = current_status.lbs_remaining('top') - BEAM_FLOOR_LBS
btm_usable = current_status.lbs_remaining('btm') - BEAM_FLOOR_LBS
producible = min(top_usable / current_item.top_pct,
                 btm_usable / current_item.btm_pct)
n_rolls    = producible // current_item.tgt_wt
for _ in range(n_rolls):                  # each run-up roll is a clean roll
    emit Knit(current_item, current_item.tgt_wt)
    emit Doff                             # ends the roll
    record Roll(current_item.tgt_wt, completion_time = Doff.end)
```

Because `n_rolls * tgt_wt <= producible`, no bar reaches the floor partway
through a run-up roll, so each roll is a single `Knit(tgt_wt)` followed by a
`Doff` — no mid-roll swap. Each roll is appended as a `Roll` entry on the
run-up's `Job` record for `current_item` (its `completion_time` is the
roll's `Doff.end`); the call yields that `Job` alongside the new-item `Job`
from phase 3 (no run-up `Job` when `n_rolls == 0`). **No `Waste` is emitted
here** — the run-up never knits a partial, so there is no runout fabric to
discard.

The run-up emits **no beam work of its own.** Because it stops on a whole-roll
boundary rather than draining a bar, each bar is left with its leftover usable
yarn — the **limiting bar** (the one that capped `producible`) with less than
one roll's worth, the other bar possibly more. The changeover preamble
(phase 2) then resolves every bar uniformly — preserve (`TapeOut`), discard
(`Waste`), keep, or load — per the new item's yarn and each bar's `usable`.

The working status after the run-up has `current_item` unchanged, with both
bars still carrying their leftover yarn.

### 2. Changeover preamble

The run-up no longer drains a bar to empty, so a bar reaching the preamble
can be in one of four states. For each bar — given the new `item`'s required
yarn and the bar's `usable = lbs_remaining(bar) - BEAM_FLOOR_LBS` — the preamble emits:

| Bar state | Activities for that bar |
|---|---|
| Empty / at the floor (`usable <= 0`) | re-thread (`Hanging` + `Threading`) only |
| Yarn matches the new item | (none) — the beam and its leftover carry over; the new item draws it at its own pct |
| Yarn doesn't match, `usable > MAX_BEAM_WASTE_LBS` | `TapeOut` + re-thread (`Hanging` + `Threading`) — preserve the worthwhile yarn (machine reverses; preserved beam not tracked in inventory yet) |
| Yarn doesn't match, `usable <= MAX_BEAM_WASTE_LBS` | `Waste(bar)` + re-thread (`Hanging` + `Threading`) — discard the residue |

Mounting a fresh beam is now two activities — a `Hanging` (physical mount)
then a `Threading` (yarn routing, which is what updates `Status`) — replacing
the old single `BeamLoad`. The bottom two rows are the runout-model behavior:
the run-up stops on a whole-roll boundary, leaving the bar with
**post-run-out yarn** — usable that's less than one roll's worth but, when
above `MAX_BEAM_WASTE_LBS`, still worth preserving with a `TapeOut` rather
than discarding. A bar whose yarn matches is never taped out or wasted — the
machine doesn't drop yarn without reason.

When **both** bars need the same operation together, emit the `'both'`
variant rather than two singles (cheaper per the duration table): a single
`TapeOut('both')` when both tape out, and a single `Hanging('both')` +
`Threading('both')` when both are re-threaded. Since the run-up emits no beam
work, the `'both'` tape-out applies in either mode — a `'next_runout'` run can
leave both bars carrying mismatched yarn above the threshold, exactly the
`'both'` case.

After all beam work (if any), if `working_status.current_item != item`, emit
the changeover activity selected per "Beam-swap decision":
`StyleChange` on a new machine, else `RunnerChange` within the pattern family
or `PatternChange` across it. The activity type carries the semantic — there
is no `is_family_change` flag.

### 3. Production loop

`plan_production` is called with `lbs` a multiple of `tgt_wt`, so the loop
owes `rolls_left = lbs / item.tgt_wt` whole rolls. It produces them one roll
at a time: a `Doff` ends each roll, and a mid-roll beam swap can split a roll,
so each `Knit` covers at most one roll (`0 < Knit.lbs <= tgt_wt`). Each bar's
`usable = lbs_remaining(bar) - BEAM_FLOOR_LBS`; a bar is exhausted at `usable <= 0`.

There are two swap triggers, both routed through one `resolve` step:

- **Pre-roll max-waste gate** — before starting a roll, swap any bar whose
  `usable` is below `MAX_BEAM_WASTE_LBS` (discard its residue as `Waste`)
  rather than knit through a near-empty beam.
- **Mid-roll runout + co-swap** — if a bar reaches the floor partway through a
  roll, re-thread it (the roll continues on the fresh beam) and, in the same
  operation, co-swap the *other* bar when it has also fallen below the
  threshold.

```
rolls_left  = lbs / item.tgt_wt        # whole rolls owed
roll_filled = 0.0                      # lbs wound on the in-progress roll
knit        = 0.0                      # lbs in the current (unflushed) Knit

flush():   if knit > 0: emit Knit(item, knit); knit = 0

# Swap any bar at/below the floor (re-thread to continue) or near-empty
# (discard its residue as Waste, then re-thread). Flush the open Knit once
# before any beam work. Bars swapped together use the 'both' variants.
resolve():
    top_swap = usable(top) < MAX_BEAM_WASTE_LBS
    btm_swap = usable(btm) < MAX_BEAM_WASTE_LBS
    if not (top_swap or btm_swap): return
    flush()
    if 0 < usable(top) < MAX_BEAM_WASTE_LBS: emit Waste(top, usable(top))
    if 0 < usable(btm) < MAX_BEAM_WASTE_LBS: emit Waste(btm, usable(btm))
    bars = 'both' if top_swap and btm_swap else ('top' if top_swap else 'btm')
    emit Hanging(bars); emit Threading(bars)     # mount, then route yarn

while rolls_left > 0:
    if roll_filled == 0:
        resolve()                                # pre-roll max-waste gate
    producible = min(usable(top) / item.top_pct,
                     usable(btm) / item.btm_pct)
    step = min(item.tgt_wt - roll_filled, producible)
    knit += step; roll_filled += step            # draws both bars at their pcts
    if roll_filled >= item.tgt_wt:               # roll complete
        flush()                                  # end the roll's final Knit
        emit Doff                                # takes the roll off (DOFF_DURATION)
        record Roll(item.tgt_wt, completion_time = Doff.end)
        roll_filled = 0; rolls_left -= 1
    else:                                        # a bar hit BEAM_FLOOR mid-roll
        resolve()                                # re-thread it; co-swap the other if near-empty
```

A `Knit` is one uninterrupted run of knitting, ending at the roll's `Doff` or
at a mid-roll swap — its `lbs` is whatever was wound in that segment, within
`(0, tgt_wt]`. Every roll is a whole `tgt_wt` roll, ends in exactly one
`Doff`, and a roll that straddles a swap is wound partly before and partly
after it, completing in the later `Knit`. There is no trailing `flush` after
the loop — each roll already flushes at its `Doff`.

Every completed roll is appended as a `Roll(lbs, completion_time)` entry on the
new-item `Job` record, its `completion_time` being the roll's `Doff.end`. When
the loop terminates, that `Job` (and the run-up `Job` from phase 1, if any) is
bundled into the `ProductionPlan` the call returns.

Unlike the previous model, the loop **does** co-swap a non-exhausted bar: when
one bar runs out, the other is swapped too if it has fallen below
`MAX_BEAM_WASTE_LBS`, so the machine doesn't return to a near-empty beam it
would have to swap again a roll or two later. A bar still above the threshold
carries its remaining yarn into the next `Knit` unchanged.

All emitted activities have `start` / `end` anchored to the activity-schedule
tail and threaded through `workcal`. The walk does not mutate `current_status`,
`activities`, or `jobs`.

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
  already match `item` (tape-outs, re-threads — `Hanging` + `Threading` — and
  the changeover activity).
- A `Doff` per completed roll (`DOFF_DURATION` each): every roll ends in a
  doff, so that overhead is part of each roll's cost and materially lowers how
  many rolls fit in the window.
- Mid-stream beam swaps within the window (each adds a re-thread,
  `HANGING_* + THREADING_*`; swaps never tape out, and a max-waste residue
  discard is a zero-duration `Waste`, so neither adds machine time beyond the
  re-thread).
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
with the floor's natural rhythm (don't cut into a roll, interrupt mid-knit, or
break before a roll is doffed off).

```
machine.schedule_tail: datetime
```

End time of the last activity on the activity schedule. If no
activities have been added, returns `initial_status.as_of`. This is
the activity-schedule tail — the earliest moment a newly planned
activity can start. (Renamed from `next_job_end` now that `Job` is
a production-schedule record rather than an activity.)

```
machine.next_runout: datetime
```

Forward-extrapolated time at which the machine would change over after
running `current_status.current_item` from `current_status.as_of`. This must
agree with what `plan_production` actually does in `'next_runout'` mode: the
run-up produces **whole rolls only** and stops before any roll the beams
can't finish above the floor (`BEAM_FLOOR_LBS`), and each of those rolls ends
in a `Doff`. So `next_runout` is the end of that **last whole roll** — i.e.
after its `Doff` — not the instant a beam first crosses the floor. Each roll
costs its knit time **plus** a `DOFF_DURATION` doff; folding in the doffs is
what keeps the prediction equal to the run-up's last `Doff.end`. Always
well-defined: `current_item` is never `None`, and real greiges always draw
from both bars (`top_pct, btm_pct > 0`).

```
usable      = min((lbs_remaining('top') - BEAM_FLOOR_LBS) / top_pct,
                  (lbs_remaining('btm') - BEAM_FLOOR_LBS) / btm_pct)
n_rolls     = floor(usable / current_item.tgt_wt)   # whole rolls only, snapped for float drift
per_roll    = current_item.tgt_wt / current_item.get_rate_on_mchn(id)  # knit hours
            + DOFF_DURATION                          # one doff per roll
next_runout = workcal.offset_work_hours(current_status.as_of, n_rolls * per_roll)
```

When fewer than one whole roll fits above the floor (`n_rolls == 0`,
including a bar already at or below the floor), `next_runout ==
current_status.as_of` — the changeover is immediately due.

`next_runout` is a **prediction**. The run-out is not necessarily reflected
as activities on the machine's schedule yet — it just describes when the
current beam state, run forward in whole rolls (each with its doff), would
force a swap. It shares the same whole-roll-plus-doff computation as the
run-up (see "Run-up" above) so the predicted changeover time matches the
activities a `'next_runout'` plan emits.

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
the lbs remaining on each bar (`init_top_lbs`, `init_btm_lbs`), and
`is_new`. (Changeover durations are no longer per-machine — they're
module-level constants — so the file no longer carries
`style_change_time` / `family_change_time`.) The initial top and
bottom beam yarns are *not* in the file
— they're derived from the resolved `Greige`'s `configuration`, since
a machine currently set up to run an item is by definition threaded
with that item's beams. `start_date` and `workcal` are plant-wide
rather than per-machine, so they're passed alongside the path.

No writer is exported from `schedule/`: per-machine schedules in the
output Excel are written by the top-level CLI from the `PlanReport`,
not by the schedule module itself.

## Test-placement contract

`plan_production` is pure; it returns a `ProductionPlan` anchored against
`current_status` without mutating anything. The scheduler can score the plan
freely and discard if not committing.

```
plan = machine.plan_production(item, lbs, start_at)   # pure
# plan.jobs is already a tuple of Job records (1 in 'schedule_tail'
# mode, 1-2 in 'next_runout' mode). Group by item id so each RlsItem
# gets a single batch.
jobs_by_item: dict[str, list[Job]] = {}
for j in plan.jobs:
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
machine.add_activities(plan.activities)
machine.add_jobs(plan.jobs)
for item_id, batch in jobs_by_item.items():
    rls_items[item_id].register_jobs(batch)
```

`add_activities` and `add_jobs` are the only mutating calls.
`add_activities` appends to the activity schedule and rolls
`current_status` forward (status depends only on activities, since
Jobs have no machine-state effect). `add_jobs` appends to the
production schedule and is otherwise inert.

## Integration with demand

A single call to `plan_production` can produce up to **two `Job`
records** — one per distinct item that gets rolls in this call:

- **`'schedule_tail'` mode** yields exactly one `Job` (for the new
  item). All rolls produced during the call are entries on that
  `Job`'s `rolls`, however the underlying `Knit`s fell — a `Knit` + `Doff`
  per roll, with the occasional roll split across a mid-call beam swap
  (`Hanging` + `Threading`).
- **`'next_runout'` mode** can yield two `Job`s: one for the run-up
  rolls of the current item and one for the new item's
  post-changeover production. If the run-up produced no whole rolls,
  only the new-item `Job` is yielded.

Each `Job` is registered with the `RlsItem` corresponding to its own
`job.item`, not the requested `item`. The scheduler maintains a lookup
from greige id to `RlsItem`, groups the yielded `Job`s by `job.item.id`,
and submits each group as a batch via `register_jobs(batch)` (or pre-
prices it via `cost_if(batch)`). Both demand-side methods accept a list
specifically to support the run-up-plus-new-item case in a single
update.

Activities on the activity schedule are intentionally invisible to
the demand layer. They affect machine occupancy — and therefore the
`Roll.completion_time` of subsequent rolls, which is the indirect
demand effect — but they contribute nothing to fulfillment
accounting directly. The demand layer reads only `Job.rolls`.

The demand layer does not split a week's required lbs across multiple
machines — it cannot, because production rate is item × machine specific. The
scheduler queries each candidate machine via `producible_lbs_in_week` and
allocates the week's demand across them. Each machine's contribution becomes
one or more `Job` records in that machine's production schedule, all
registered against the same `RlsItem`.

## Out of scope

- **Cross-machine scheduling** — `Machine` knows nothing about other
  machines. Picking *which* machine should run a given production is the
  scheduler's job.
- **Activity removal / rollback** — activities are append-only. The
  plan-then-commit contract above covers "what-if" without needing an
  unregister path.
- **Preemptive co-swapping** — when one bar exhausts mid-knit and the
  other still has yarn, the planner does not opportunistically swap
  the second bar. The scheduler can drive that decision at a higher
  level if it wants.
- **Overlapping activities** — activities on a single machine are strictly
  sequential. Floor work that could in principle run in parallel (e.g.,
  taping out one bar while loading the other) is modeled by activity-type
  duration choices (`TapeOut('both')` is shorter than two single tape-outs
  sequentially), not by overlap.
- **Stochastic durations / breakdowns** — all durations are deterministic.
  Idle gaps not explained by `workcal` are not modeled.
- **Doffing / cleanup after waste** — negligible time, ignored.
