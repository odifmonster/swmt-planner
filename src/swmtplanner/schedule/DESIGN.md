# Schedule / Machine Production — Design

Source of truth for the structure of `Activity`, `Status`, and `Machine`.
Captures decisions made before implementation so the planning logic stays in
one place and the demand-side cost layer can consume jobs without knowing how
they were produced.

## Purpose

For each knitting machine, model the sequence of work that actually happens on
the floor — knitting, doffing, beam swaps, style changes — and the
roll-level production those activities deliver. The submodule answers
three questions:

- **Where does production land in time?** Given an intent to produce N rolls of
  a greige item on a machine, what activities need to happen, in what order,
  and when does each start/end?
- **What rolls were produced, and when?** Each machine carries a
  production schedule of `Job`s, with one `Roll(lbs,
  completion_time)` entry per completed roll. The demand layer reads
  this for per-roll lateness accounting.
- **What state is the machine in at time T?** Beams on each bar, lbs left on
  each beam, current item/family, idle or not. Status is derived from
  the activity schedule only — the production schedule has no
  machine-state effect.

The schedule layer is the source of `Job` records (in each machine's
production schedule). The demand layer (`RlsItem`) consumes them.
The two layers are decoupled: schedule says *when* each roll lands,
demand says *how expensive that when is*. `Job`s are *not*
activities in the new model — see Core objects.

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
- `DOFF_DURATION = 20 minutes` — removing one completed roll from the
  machine. The machine is stopped during the doff; no fabric is
  produced and no beam state changes. (The original design treated
  doffing as negligible; in practice it's long enough to matter for
  end-time calculations, so it's now its own activity.)
- `BEAM_FLOOR_LBS = 50 lbs` (tunable) — the minimum yarn that stays on a
  beam when production stops. The plant can't knit a beam all the way to
  zero; this is the residue left on the spool when the beam is considered
  exhausted. Used in producibility math (`producible = (lbs_remaining -
  BEAM_FLOOR_LBS) / bar_pct`) and as the threshold below which a bar is
  "empty" for the changeover preamble. Tunable as plant conditions
  change.
- `MIN_ROLL_START_FRACTION = 0.40` (tunable) — the minimum fraction of
  `Greige.tgt_wt` of producible yarn from the current beam state required
  to start a new roll on the existing beams. When the producible from a
  bar drops below `MIN_ROLL_START_FRACTION * item.tgt_wt`, the planner
  tapes that bar out and loads fresh *before* starting the next roll
  rather than dragging a small amount of yarn into the roll. See "The
  40% rule" under Roll-level production for details.

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

A `Machine` carries two parallel schedules: an **activity schedule**
(the timeline of physical machine activities) and a **production
schedule** (the list of `Job`s — logical orders for rolls). The
activity schedule determines machine status; the production schedule
is what the demand layer consumes. A `Job` is *not* an activity —
it's a grouping of completed rolls, with no direct effect on machine
status. The Knit and Doff activities are what actually fill the
activity schedule when production happens.

```
Activity (abstract)               # anything that occupies machine time
  start: datetime
  end: datetime

  Knit(Activity)                  # a continuous block of fabric production
                                  # at the machine's current item rate.
                                  # Bounded above by exactly one roll: the
                                  # machine stops at every Doff, so a Knit
                                  # ends either at a roll completion (with a
                                  # Doff to follow) or mid-roll because a
                                  # beam exhausted (with a BeamLoad to
                                  # follow). A Knit never spans two rolls.
                                  # `lbs` is therefore in (0, item.tgt_wt].
    item: Greige
    lbs: float                    # fabric produced in this continuous knit

  Doff(Activity)                  # remove one completed roll from the
                                  # machine. The machine is stopped during
                                  # the doff (DOFF_DURATION); no fabric is
                                  # produced and beam state is unchanged.
                                  # Exactly one Doff per completed roll.
    item: Greige
    roll_lbs: float               # weight of the roll being doffed (~tgt_wt
                                  # within tolerance)

  Waste(Activity)                 # discard yarn ABOVE BEAM_FLOOR_LBS when a bar
                                  # is swapped without preserving the beam. Zero
                                  # duration — the physical removal happens
                                  # inside the subsequent BeamLoad (which already
                                  # has to remove the old beam to mount the new
                                  # one). The cost layer charges per `lbs`.
    item: Greige                  # the item whose yarn is being discarded
    bar: Literal['top', 'btm']
    lbs: float                    # lbs ABOVE BEAM_FLOOR_LBS being discarded

  TapeOut(Activity)               # remove yarn from a bar AND preserve the
                                  # partial beam for future re-use. Same
                                  # semantics as before (4h / 6h, runs the
                                  # machine in reverse). Emitted by the
                                  # changeover preamble when a still-yarned
                                  # bar has substantial yarn worth preserving.
                                  # The preserved partial beam isn't tracked
                                  # in inventory in the current phase.
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

Roll                              # one completed roll (whole-roll size,
                                  # within tolerance of item.tgt_wt). Pure
                                  # data — no machine-state effect.
  lbs: float
  completion_time: datetime       # end of the roll's Doff activity (the
                                  # moment the roll is physically off the
                                  # machine and ready to ship)

Job (HasID)                       # one entry in a machine's production
                                  # schedule — a grouping of rolls produced
                                  # in one logical production call. Pure
                                  # data: no start/end/duration, no effect
                                  # on machine status. The demand layer
                                  # reads `Job.rolls` to learn when each
                                  # roll lands.
  item: Greige
  rolls: tuple[Roll, ...]         # one entry per completed roll, in
                                  # chronological order of completion

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

ProductionPlan                    # return value of plan_production —
                                  # the activity-schedule and
                                  # production-schedule additions for a
                                  # single planning call.
  activities: tuple[Activity, ...]
  jobs: tuple[Job, ...]           # 1 or 2 entries: 1 in 'schedule_tail'
                                  # mode (just the new item), up to 2 in
                                  # 'next_runout' mode (run-up of the
                                  # current item, then the new item)

Machine (HasID)
  id, workcal
  initial_status: Status            # exposed read-only
  activities: tuple[Activity, ...]  # activity schedule; append-only
  jobs: tuple[Job, ...]             # production schedule; append-only
  current_status: Status            # status at the activity-schedule tail
  simple_change_duration, family_change_duration
  is_new: bool                      # default False; True ⇒ no family changes emitted
  status_at(t) -> Status
  duration_of(spec) -> timedelta
  plan_production(item, lbs, start_at, idle_for=timedelta(0)) -> ProductionPlan
  add_activities(activities) -> None
  add_jobs(jobs) -> None
  # capacity + stopping-point queries
  producible_lbs_through(item, end, start=None) -> float
  producible_lbs_in_week(item, year, week, start=None) -> float
  schedule_tail: datetime          # end time of the last activity on the
                                   # activity schedule (the earliest moment
                                   # a new activity can start). Was named
                                   # `next_job_end` when Jobs were
                                   # activities; renamed in the
                                   # production/schedule split.
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
| `Knit(item, lbs)` | `lbs / item.get_rate_on_mchn(machine.id)` |
| `Doff(item, roll_lbs)` | `DOFF_DURATION` (independent of `roll_lbs`) |
| `Waste(item, bar, lbs)` | 0 (no machine time; physical removal folds into the subsequent `BeamLoad`) |
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

The plant ships **whole rolls** of ~`Greige.tgt_wt` lbs (within
tolerance). `plan_production` is called with `lbs` already a multiple
of `tgt_wt` — the demand layer plans in whole-roll quantities, since
all real orders are for full rolls — and the planner produces whole
rolls only. There are no partial-roll deliveries and no salvaged
half-rolls: the new exhaustion model (below) lets the planner span a
single roll across multiple beams instead of slicing it into a
half-roll plus scrap.

The planner emits two activity types for "remove yarn from a bar"
events (see Core objects), and the choice between them is governed
by how much yarn is on the bar:

- **`Waste`** — discards the yarn above `BEAM_FLOOR_LBS`. Zero
  duration; the cost layer charges per-lb as yarn-inventory loss.
  Used when the bar has a small amount of yarn (producible below
  the `MIN_ROLL_START_FRACTION` threshold) — small enough that the
  operator wouldn't bother preserving the beam for re-use.
- **`TapeOut`** — preserves the partial beam by running the machine
  in reverse to keep threads positioned for a clean re-mount.
  Costs `TAPE_OUT_SINGLE_DURATION` / `TAPE_OUT_BOTH_DURATION` of
  machine time; no per-lb cost. Used when the bar has substantial
  yarn (producible at or above `MIN_ROLL_START_FRACTION` × current
  item's `tgt_wt`) — enough that the operator would tape out for
  future re-use rather than scrap it. The current planner doesn't
  actually track the preserved beam in inventory (so internally
  it's discarded), but the activity is still emitted to reflect the
  real machine-time cost the operator would incur.

Both can appear on the same changeover when one bar is substantial
(TapeOut) and the other near-floor (Waste).

### Beam exhaustion is a soft floor, not zero

A real beam can't be knit all the way down — there's always some
yarn left on the spool when production stops. The module-level
constant `BEAM_FLOOR_LBS` (e.g. 50 lbs) is that floor. A beam is
**exhausted** when its remaining yarn drops at or below
`BEAM_FLOOR_LBS`; the residue stays on the spool and is *not*
counted as `Waste` — it's a constant loss on every beam regardless
of planner decisions, so attributing it doesn't differentially
affect anything. Only yarn discarded *above* the floor is wasted
in the planner-accountable sense (see the 40% rule and the
post-load spacing check, below).

Producible fabric (in lbs) from the current beam state is:

```
top_usable = max(0, top_lbs_remaining - BEAM_FLOOR_LBS)
btm_usable = max(0, btm_lbs_remaining - BEAM_FLOOR_LBS)
producible = min(top_usable / item.top_pct, btm_usable / item.btm_pct)
```

This formula replaces the old `min(top_lbs / top_pct, btm_lbs /
btm_pct)`. Wherever the old design talked about a beam reaching zero,
the new model substitutes "remaining ≤ `BEAM_FLOOR_LBS`."

### Mid-roll beam loads

A beam exhausting *mid-roll* does not interrupt the roll. The
machine emits a `BeamLoad` for that bar and continues knitting the
same roll on the fresh beam. The roll completes once enough total
fabric has been produced across both beams to reach `tgt_wt` (within
tolerance).

In the activity schedule this looks like a sequence of `Knit`
activities, each ending at exactly one of two events: a roll
completion (immediately followed by a `Doff`) or a beam exhaustion
(immediately followed by a `BeamLoad`). A `Knit` is bounded above
by one roll's worth — at every roll completion the machine stops
for the `Doff`, so no `Knit` can carry production across two rolls.
A roll that straddles a mid-roll `BeamLoad` is produced by *two or
more* `Knit`s separated by `BeamLoad`(s), all summing to
`item.tgt_wt`.

Roll completions live on the `Job` in the production schedule, not
on any `Knit`. As each roll's `Doff` is emitted, a `Roll(lbs,
completion_time=doff.end)` entry is appended to the Job's `rolls`.
Knit and Doff activities don't reference the Job back; the Job is
the consumer of "roll completed" events, and the activity schedule
is the consumer of "machine spent N hours doing X" events.

The two schedules are conservation-consistent. Over any time span,
the sum of `Knit.lbs` for a given item equals the sum of `Roll.lbs`
in that item's `Job`s for rolls whose `completion_time` lands in
the same span — neither schedule can produce fabric the other
doesn't account for. Beam-residue waste (the lbs on a Waste
activity, or the unrecoverable floor residue) sits outside this
balance; it's yarn loss, not fabric output.

Natural exhaustion (the bar dropping to `BEAM_FLOOR_LBS`) emits a
`BeamLoad` only — no `TapeOut`, no `Waste`. The near-empty beam's
residue comes off as part of the BeamLoad handling, and because the
floor residue is unavoidable on every beam, no `Waste` lbs are
attributed (the cost layer only charges for above-floor yarn that
the planner *chose* to discard).

After the mid-roll `BeamLoad` on the exhausted bar, the planner also
checks whether the *other* bar can carry the rest of the roll
without forcing a second mid-roll load too close to the first. The
threshold is `min(MIN_ROLL_START_FRACTION × tgt_wt, roll_remaining)`
— i.e., the other bar must be able to either (a) finish the
remaining `roll_remaining` lbs of the current roll outright (when
the roll is more than 60% complete) or (b) carry the roll at least
another `MIN_ROLL_START_FRACTION × tgt_wt` lbs (when the roll is
less complete and any subsequent mid-roll load would land at least
40% of `tgt_wt` from the first). If the other bar can't clear that
threshold, the planner proactively swaps it too: a single mid-roll
BeamLoad event becomes a `Waste(other, other_lbs - BEAM_FLOOR_LBS) + BeamLoad(exhausted) + BeamLoad(other)` sequence. The `Waste`
captures the yarn-inventory cost of discarding the other bar's
still-usable yarn early; it has zero duration, so the only
duration-cost added vs the single-BeamLoad case is the second
`BeamLoad`. This trades a small inventory loss for a cleaner roll
(no second mid-roll defect close to the first). See the
production-loop pseudocode for the exact branching.

### The 40% rule for starting a roll

Before starting *each* roll, the planner checks whether the current
beam state has enough producible yarn for the roll to be worth
starting on those beams. The check is per-bar:

```
for each bar in {top, btm}:
    producible_from_bar = max(0, bar_lbs_remaining - BEAM_FLOOR_LBS) / item.<bar>_pct
    if producible_from_bar < MIN_ROLL_START_FRACTION * item.tgt_wt:
        emit Waste(item, bar, bar_lbs_remaining - BEAM_FLOOR_LBS) + BeamLoad(bar, fresh)
```

`MIN_ROLL_START_FRACTION` (e.g. `0.40`) is the threshold; below this
the floor would rather scrap the residue than start a roll on a
near-empty beam (the chance of two near-empty bars dropping
simultaneously and turning the roll into a chain of swaps is high
enough that pre-swapping is the cheaper move).

The check is **proactive**: it discards the limiting bar's
above-floor yarn (above the natural-exhaustion floor but below the
40%-of-roll threshold) via a zero-duration `Waste` activity, then
loads a fresh beam. The duration-cost of a pre-roll swap is just
`BEAM_LOAD_DURATION`; the variable cost is the `Waste.lbs`, charged
per-lb by the cost layer (so a bar at 49% of `tgt_wt` worth of
producible costs less to scrap than one at 5%). If both bars trip
the rule on the same roll boundary, two separate `Waste +
BeamLoad` pairs are emitted (one per bar) — the per-lb cost is
additive across the two `Waste`s, so no "both" bundling shortcut
is needed.

After any 40%-rule swaps, the producible is recomputed from the new
beam state (fresh beams hold thousands of lbs, comfortably above the
threshold) and the roll proceeds normally — with the mid-roll
beam-load rule still applying if either bar runs down during the
roll.

The 40% rule applies only to the start of each roll, *not* to the
run-up phase in `'next_runout'` mode: the run-up's purpose is to use
up what's already on the beams before changing items, and any
leftover is going to be discarded by the changeover preamble that
follows it anyway (different items ⇒ different yarn ⇒ unconditional
`Waste + BeamLoad` for every still-yarned bar). See "Run-up" under
`plan_production` for the run-up's own (whole-rolls-only) producible
math.

## The `plan_production` walk

Given `(item, lbs, start_at, idle_for)` and `current_status`, build the
activity list. `start_at` is one of:

- `'schedule_tail'` — production of the new item begins at
  `current_status.as_of` (the activity-schedule tail). The activity
  list contains only the changeover preamble and the new-item
  production loop.
- `'next_runout'` — the machine continues running its current item until
  the next beam exhausts (drops to `BEAM_FLOOR_LBS`), *then* changes
  over to the new item. The activity list begins with whole-roll
  `Knit + Doff` pairs of `current_item` (any sub-roll remainder is
  left on the beam and comes off with the changeover's tape-out),
  followed by the changeover preamble and the new-item production
  loop. A separate `Job` is yielded for the run-up rolls.

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

In `'schedule_tail'` mode, no run-up activities are emitted. The **working
status** (the status against which the changeover preamble is computed) is
`current_status` directly.

In `'next_runout'` mode, walk forward producing the current item in
whole-roll quantities up to what fits before the next exhaustion.
Any sub-roll remainder is left on the beam — it'll come off with the
beam at the changeover preamble's unconditional tape-out (different
item ⇒ different yarn), so there's no point knitting it into a
partial roll.

```
current_item = current_status.current_item
top_usable = max(0, current_status.top_lbs_remaining - BEAM_FLOOR_LBS)
btm_usable = max(0, current_status.btm_lbs_remaining - BEAM_FLOOR_LBS)
producible = min(top_usable / current_item.top_pct,
                 btm_usable / current_item.btm_pct)
n_rolls = producible // current_item.tgt_wt    # whole rolls only

run_up_rolls = []
for _ in range(n_rolls):
    emit Knit(current_item, current_item.tgt_wt)
    emit Doff(current_item, current_item.tgt_wt)
    run_up_rolls.append(Roll(lbs=current_item.tgt_wt,
                             completion_time=doff.end))

if run_up_rolls:
    yield Job(item=current_item, rolls=tuple(run_up_rolls))

# Any sub-roll remainder of `producible` is left on the beam(s); the
# upcoming changeover preamble will emit Waste(current_item, bar,
# bar_above_floor) + BeamLoad for each still-yarned bar, since the
# new item's yarn won't match.
```

The 40% rule does *not* fire in the run-up — see "The 40% rule" in
Roll-level production for why. The run-up is bounded by the existing
beam state and never loads fresh beams mid-run-up.

After the run-up, the limiting bar (the one that would have
exhausted first if the run-up were unbounded) has been drawn down
to somewhere in `[BEAM_FLOOR_LBS, BEAM_FLOOR_LBS + tgt_wt ×
limiting_pct)`. It lands exactly at `BEAM_FLOOR_LBS` only when
`producible` was an exact multiple of `tgt_wt`; otherwise the
limiting bar still has the sub-roll remainder of yarn sitting above
the floor — the run-up didn't knit it into a partial roll, but
nothing was taken off the bar either. The non-limiting bar is
always further above. `current_item` is unchanged.

The changeover preamble that follows therefore sees each bar in
one of three states (per the table below): "Empty" (at-or-below
the floor — `BeamLoad` only), "Has small yarn" (above floor but
producible below `MIN_ROLL_START_FRACTION × tgt_wt` — `Waste +
BeamLoad`), or "Has substantial yarn" (producible at or above
`MIN_ROLL_START_FRACTION × tgt_wt` — `TapeOut + BeamLoad`, beam
preserved). Since the new item's yarn differs from
`current_item`'s, both bars get swapped one way or the other.

A typical post-run-up changeover hits a mix: the limiting bar
sits near the floor (most often "Has small yarn", occasionally
"Empty") while the non-limiting bar still has substantial yarn
("Has substantial yarn" → `TapeOut`). The common emission pattern
is therefore `TapeOut(non_limiting) + Waste(limiting,
limiting_above_floor) + BeamLoad(top) + BeamLoad(btm)` — the
operator preserves the substantial beam and scraps the near-empty
one. If both bars happen to be substantial (uncommon after a
run-up, but possible when the run-up's leftover sub-roll
remainder is large relative to `tgt_wt`), the preamble collapses
to `TapeOut('both') + BeamLoad(top) + BeamLoad(btm)`.

### 2. Changeover preamble

For each bar, the working status falls into one of four cases. Let
`producible_from_bar = max(0, bar_lbs_remaining - BEAM_FLOOR_LBS) /
current_item.<bar>_pct` (where `current_item` is the item whose
yarn is currently on the bar).

| Bar state | New item's yarn matches? | Activities for that bar |
|---|---|---|
| Has yarn (lbs > `BEAM_FLOOR_LBS`) | yes | (none) |
| Has substantial yarn (producible ≥ `MIN_ROLL_START_FRACTION` × `current_item.tgt_wt`) | no | `TapeOut` + `BeamLoad` |
| Has small yarn (above floor but producible < `MIN_ROLL_START_FRACTION` × `current_item.tgt_wt`) | no | `Waste` + `BeamLoad` |
| Empty (lbs ≤ `BEAM_FLOOR_LBS`, post-runout) | always needs a load | `BeamLoad` only |

The `TapeOut` vs `Waste` decision is a per-bar judgment about
whether the yarn is worth preserving. The threshold reuses
`MIN_ROLL_START_FRACTION` — the same fraction that decides whether
a bar is worth knitting through (the 40% rule). Below that, the
yarn is small enough that the operator would scrap it; at or above,
they'd tape out for re-use. The current planner emits `TapeOut`
when the threshold is met (incurring the 4h/6h machine cost) but
doesn't actually track the preserved beam in inventory — see
TapeOut's docstring in Core objects.

"Has yarn" and "Empty" are defined relative to `BEAM_FLOOR_LBS`,
not zero — a bar at or below the floor is treated as empty
(unrecoverable residue stays on the spool and comes off with the
BeamLoad; no `Waste` is emitted because the floor residue isn't
planner-accountable). This applies whether the working status is
from `'schedule_tail'` mode (both bars always have substantial yarn,
so the typical preamble is `TapeOut('both') + BeamLoad(top) +
BeamLoad(btm)`) or `'next_runout'` mode (where the limiting bar
usually has small yarn, the non-limiting bar substantial; see "Run-
up" for the typical mix).

When both bars need swapping, the emission depends on each bar's
yarn-volume classification:

- Both `TapeOut` (both bars have substantial yarn): emit
  `TapeOut('both') + BeamLoad(top) + BeamLoad(btm)`. The 'both'
  form bundles the two tape-outs into a single 6h activity, cheaper
  than two 4h singles.
- Mixed (one `TapeOut`, one `Waste`): emit `TapeOut(<substantial
  bar>) + Waste(<small bar>) + BeamLoad(top) + BeamLoad(btm)`. The
  'both' bundling doesn't apply — only one bar is being taped out.
- Both `Waste` (both bars have small yarn above the floor): emit
  per-bar `Waste + BeamLoad` for each (two `Waste`s, two
  `BeamLoad`s). No "both" bundling for `Waste` either — its
  duration is zero and its cost is additive per-lb.

After all beam work (if any), if `working_status.current_item != item`,
emit `StyleChange(from_item=working_status.current_item, to_item=item,
is_family_change=((not machine.is_new) and
working_status.current_item.family != item.family))`.

### 3. Production loop

The loop produces `lbs / item.tgt_wt` rolls of `item`, one at a
time. Within each roll, beam exhaustion (a bar dropping to
`BEAM_FLOOR_LBS`) triggers a mid-roll `BeamLoad` and the roll
continues on the fresh beam; between rolls, the 40% rule may
trigger a proactive `Waste + BeamLoad` before the next roll starts.
Conceptually:

```
n_rolls = lbs // item.tgt_wt
new_item_rolls = []
for roll_idx in range(n_rolls):

    # ---- Pre-roll gate: the 40% rule.
    # If a bar can't contribute at least MIN_ROLL_START_FRACTION * tgt_wt
    # of fabric before exhaustion, swap it before the roll starts. The
    # discarded above-floor yarn is captured as a zero-duration Waste
    # activity (cost per-lb). An at-or-below-floor bar just gets a
    # BeamLoad (no Waste — floor residue isn't planner-accountable).
    for bar in {top, btm}:
        if bar_lbs_remaining <= BEAM_FLOOR_LBS:
            emit BeamLoad(bar, fresh)
            continue
        usable = bar_lbs_remaining - BEAM_FLOOR_LBS
        producible_from_bar = usable / item.<bar>_pct
        if producible_from_bar < MIN_ROLL_START_FRACTION * item.tgt_wt:
            emit Waste(item, bar, usable) + BeamLoad(bar, fresh)

    # ---- Knit the roll, spanning beam loads if needed.
    roll_remaining = item.tgt_wt
    while roll_remaining > 0:
        top_usable = max(0, top_lbs_remaining - BEAM_FLOOR_LBS)
        btm_usable = max(0, btm_lbs_remaining - BEAM_FLOOR_LBS)
        producible = min(top_usable / item.top_pct,
                         btm_usable / item.btm_pct)

        if producible >= roll_remaining:
            # The current beams can finish this roll.
            emit Knit(item, roll_remaining)
            roll_remaining = 0
            break

        # A beam will exhaust mid-roll. Knit what's there.
        emit Knit(item, producible)
        roll_remaining -= producible

        # Identify which bar(s) hit the floor (could be both if they exhaust
        # at the same time — the producible math gives the same exhaustion
        # point for both in that case).
        top_lbs_remaining -= producible * item.top_pct
        btm_lbs_remaining -= producible * item.btm_pct
        top_exhausted = top_lbs_remaining <= BEAM_FLOOR_LBS
        btm_exhausted = btm_lbs_remaining <= BEAM_FLOOR_LBS

        if top_exhausted and btm_exhausted:
            # Both exhausted simultaneously — load both, no Waste (both
            # bars are at-or-below the floor; the residue is non-
            # planner-accountable).
            emit BeamLoad(top, fresh) + BeamLoad(btm, fresh)
        else:
            # Exactly one bar exhausted; check whether the other has
            # enough headroom to carry the remainder of this roll without
            # forcing a second mid-roll load too close to the first.
            exhausted, other = (top, btm) if top_exhausted else (btm, top)
            other_usable = max(0, <other>_lbs_remaining - BEAM_FLOOR_LBS)
            other_producible = other_usable / item.<other>_pct
            threshold = min(MIN_ROLL_START_FRACTION * item.tgt_wt, roll_remaining)
            if other_producible < threshold:
                # The other bar would force a second mid-roll load too soon.
                # Discard its above-floor yarn and load fresh on both bars.
                emit Waste(item, other, <other>_lbs_remaining - BEAM_FLOOR_LBS) \
                     + BeamLoad(exhausted, fresh) + BeamLoad(other, fresh)
            else:
                # The other bar can carry the rest (or at least another 40%
                # of a roll before the next mid-roll load).
                emit BeamLoad(exhausted, fresh)

    # The roll has just completed (roll_remaining == 0). Doff it and
    # record the completion on the in-progress Job's rolls.
    emit Doff(item, item.tgt_wt)
    new_item_rolls.append(Roll(lbs=item.tgt_wt,
                                completion_time=doff.end))

# After all N rolls of `item` have been produced and doffed, yield the
# single Job that holds them.
yield Job(item=item, rolls=tuple(new_item_rolls))
```

Each completed roll contributes one `Roll(lbs, completion_time)`
entry to the in-progress Job's `rolls`, with `completion_time` taken
from the end of that roll's `Doff` activity (the moment the roll is
physically off the machine, ready to ship). Knit and BeamLoad
activities don't write into the Job; the Job's `rolls` is built
only at Doff time.

When only one bar exhausts during a roll, the planner may either let
the other bar carry on (its lbs carry forward unchanged) or
proactively discard its above-floor yarn (`Waste`) and load fresh
alongside the mandatory exhausted-bar `BeamLoad`. The decision is
the post-load spacing check above: the planner swaps the other bar
iff its remaining producibility falls below
`min(MIN_ROLL_START_FRACTION × tgt_wt, roll_remaining)`, so the next
mid-roll load (if any) is at least 40% of a roll away from the one
we just did. Outside of this spacing check and the pre-roll 40%
gate, the planner does not preemptively swap — that's a
scheduler-level optimization.

`MIN_ROLL_START_FRACTION` is chosen so that fresh beams always pass
both the pre-roll gate and the post-load spacing check (a freshly
loaded beam holds `fresh_beam_lbs(beam)` lbs ≫
`MIN_ROLL_START_FRACTION * tgt_wt * bar_pct`), so neither check can
re-trigger a swap on a beam that was just loaded.

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
- Mid-stream beam swaps within the window. Natural exhaustion (a bar
  drops to `BEAM_FLOOR_LBS`) consumes `BEAM_LOAD_DURATION` only.
  40%-rule proactive swaps between rolls (when a bar's producible
  falls below `MIN_ROLL_START_FRACTION * tgt_wt`) also consume only
  `BEAM_LOAD_DURATION` per swapped bar — the accompanying `Waste`
  activity has zero duration. The same goes for post-load spacing
  swaps inside a roll: `BeamLoad(exhausted) + BeamLoad(other)`, with
  a zero-duration `Waste(other)` on the side.
- One `DOFF_DURATION` per whole roll produced. The available knit
  hours in the window are `total_hours - (preamble + mid-stream
  swaps + n_rolls * DOFF_DURATION)`, where `n_rolls` is chosen to
  maximize the producible lbs.
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
machine.schedule_tail: datetime
```

End time of the last activity on the activity schedule. If no
activities have been added, returns `initial_status.as_of`. This is
the schedule tail — the earliest moment a newly planned activity
can start. (Renamed from `next_job_end` in the production/schedule
split, since Jobs are no longer activities and "next job end" no
longer corresponds to anything on the activity schedule.)

```
machine.next_runout: datetime
```

Forward-extrapolated time at which top or btm beam will exhaust — i.e.,
drop to `BEAM_FLOOR_LBS` — assuming `current_status.current_item`
continues running from `current_status.as_of`. Always well-defined:
`current_item` is never `None`, and real greiges always draw from
both bars (`top_pct, btm_pct > 0`).

```
top_usable = max(0, top_lbs_remaining - BEAM_FLOOR_LBS)
btm_usable = max(0, btm_lbs_remaining - BEAM_FLOOR_LBS)
producible_before_runout = min(top_usable / top_pct,
                               btm_usable / btm_pct)
knit_hours = producible_before_runout / current_item.get_rate_on_mchn(id)
# Each whole roll completed before runout incurs one DOFF_DURATION stop.
doffs_before_runout = producible_before_runout // current_item.tgt_wt
doff_hours = doffs_before_runout * DOFF_DURATION
next_runout = workcal.offset_work_hours(
    current_status.as_of, knit_hours + doff_hours,
)
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

`plan_production` is pure; it returns a `ProductionPlan` (with
`activities` and `jobs`) anchored against `current_status` without
mutating anything. The scheduler can score the plan freely and discard
if not committing.

```
plan = machine.plan_production(item, lbs, start_at)   # pure
# plan.jobs is already a tuple of Job objects (one per distinct item
# produced — 1 in 'schedule_tail' mode, 1-2 in 'next_runout' mode).
# Group by item id so each RlsItem gets a single batch.
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

A single call to `plan_production` can produce **multiple `Job`s** —
one per distinct item that gets rolls in this call:

- **`'schedule_tail'` mode** produces exactly one Job (for the new
  item). All `n_rolls` completed rolls are entries in that Job's
  `rolls`.
- **`'next_runout'` mode** can produce up to two Jobs: one for the
  current item (the run-up's whole rolls before changeover) and one
  for the new item (the post-changeover production). If the run-up
  produced zero whole rolls (producible was below `tgt_wt`), only
  the new-item Job is yielded.

Mid-roll beam exhaustion does *not* create extra Jobs. A roll that
straddles a `BeamLoad` is still a single `Roll` entry on a single
`Job` — the entry is appended at Doff time, regardless of how many
`Knit` activities went into producing it. Knit and Doff activities
go on the activity schedule, not on any Job.

Each `Job` is registered with the `RlsItem` corresponding to its own
`job.item`, not the requested `item`. The scheduler maintains a lookup
from greige id to `RlsItem`, groups the emitted `Job`s by `job.item.id`,
and submits each group as a batch via `register_jobs(batch)` (or pre-
prices it via `cost_if(batch)`). Both demand-side methods accept a list
specifically to support the run-up-plus-new-item case in a single
update.

Activities are invisible to the demand layer. `Waste` represents
yarn-inventory loss (per-lb cost in the schedule penalty bucket of
the planner's `CostWeights`); `Knit`, `Doff`, `TapeOut`, `BeamLoad`,
`StyleChange`, and `Idle` represent machine occupancy (their
durations affect when subsequent rolls land, which is the indirect
demand effect via roll `completion_time`). The demand layer reads
only `Job.rolls`.

The demand layer does not split a week's required lbs across multiple
machines — it cannot, because production rate is item × machine specific. The
scheduler queries each candidate machine via `producible_lbs_in_week` and
allocates the week's demand across them. Each machine's contribution becomes
one or more `Job`s in that machine's production schedule, all registered
against the same `RlsItem`.

## Out of scope

- **Cross-machine scheduling** — `Machine` knows nothing about other
  machines. Picking *which* machine should run a given production is the
  scheduler's job.
- **Activity removal / rollback** — activities are append-only. The
  plan-then-commit contract above covers "what-if" without needing an
  unregister path.
- **Unconstrained preemptive co-swapping** — the planner *does*
  proactively swap a non-exhausted bar in two bounded cases: the
  pre-roll 40% gate (a bar whose producible-until-exhaustion would
  be under `MIN_ROLL_START_FRACTION * tgt_wt` gets discarded —
  `Waste + BeamLoad` — before the roll starts) and the post-load
  spacing check (when only one bar exhausts mid-roll, the other is
  swapped alongside via `Waste + BeamLoad` if its remaining
  producibility is under `min(MIN_ROLL_START_FRACTION * tgt_wt,
  roll_remaining)`). Beyond those two thresholds, the planner does
  not opportunistically swap a still-useful bar — driving that
  finer optimization is a scheduler-level concern.
- **Partial-beam inventory tracking** — the planner *does* emit
  `TapeOut` (for changeover bars whose yarn is substantial enough
  to be worth preserving, per the threshold in the changeover
  preamble), but it doesn't actually track the preserved partial
  beam after the activity. Internally the beam is effectively
  discarded — the schedule records the operator's intent and the
  4h/6h of machine time spent, but doesn't add the partial to any
  inventory of reusable beams. A future scheduler can consume
  `TapeOut` events as the source of partial-beam supply without
  changing the schedule format.
- **Overlapping activities** — activities on a single machine are strictly
  sequential. Floor work that could in principle run in parallel (e.g.,
  taping out one bar while loading the other) is modeled by activity-type
  duration choices (`TapeOut('both')` is shorter than two single tape-outs
  sequentially), not by overlap.
- **Stochastic durations / breakdowns** — all durations are deterministic.
  Idle gaps not explained by `workcal` are not modeled.
- **Beam-removal time on a discard swap** — the physical work of
  removing an old beam (cutting threads, sliding the spool off) on
  a *discard* swap is not modeled as a separate activity; it folds
  into the subsequent `BeamLoad`'s duration. The `Waste` activity
  that accompanies a discarding swap captures the lost yarn (per-lb
  cost) but has zero duration — the cutting and removal happen
  during the `BeamLoad`. The `TapeOut` activity, on the other hand,
  *does* have its own duration because it includes running the
  machine in reverse to preserve thread positioning; the planner
  emits it when the bar's yarn is substantial enough to be worth
  preserving (per the changeover-preamble threshold). Distinct from
  the `Doff` activity, which models removing a completed roll
  (different operation, different duration).
