#!/usr/bin/env python

import math
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Iterable, Literal, Mapping, Sequence, TYPE_CHECKING

from swmtplanner.support import HasID
from swmtplanner.products import BeamSet, BeamSetDesc
from swmtplanner.support import planning_mode
from swmtplanner.schedule.activity import (
    Activity, Knit, Waste, Doff, TapeOut, Unhang, Hanging, Threading,
    StyleChange, RunnerChange, PatternChange, Idle,
    TAPE_OUT_SINGLE_DURATION, TAPE_OUT_BOTH_DURATION,
    HANGING_SINGLE_DURATION, HANGING_BOTH_DURATION,
    THREADING_SINGLE_DURATION, THREADING_BOTH_DURATION,
    DOFF_DURATION,
    STYLE_CHANGE_DURATION, RUNNER_CHANGE_DURATION, PATTERN_CHANGE_DURATION,
    BEAM_FLOOR_LBS, MAX_BEAM_WASTE_LBS, rebind_sets,
)
from swmtplanner.schedule.job import Job, Roll
from swmtplanner.schedule.inventory import worth_stocking
from .status import Status

if TYPE_CHECKING:
    from swmtplanner.support import WorkCal
    from swmtplanner.products import Greige, VariantMapFile
    from swmtplanner.schedule.inventory import InventoryView
    from swmtplanner.schedule.capacity import ChangeoverCapacity, Slot


# Plant convention: fresh-beam yarn quantity depends on yarn denier. Low-
# denier yarn (≤ 45D) holds more lbs per beam; high-denier yarn holds less.
# Lives at module level because the rule is plant-wide rather than per-
# machine, and not a property of `BeamSetDesc` (which stays plant-agnostic).
_LOW_DENIER_FRESH_LBS = 2800.0
_HIGH_DENIER_FRESH_LBS = 1800.0

# A stock set lighter than this is passed over for a hang while any heavier
# set fits the bar (it would mean another swap within hours). See "Beam-set
# inventory" in DESIGN.md.
MIN_STOCK_SET_LBS = 500.0
_LOW_DENIER_THRESHOLD = 45


def fresh_beam_lbs(beam: BeamSetDesc) -> float:
    """How much yarn is on a freshly loaded beam, by denier convention. Sizes
    the sets the planner **invents** when nothing suitable is in stock. In
    planning mode every set starts with `planning_mode.BEAM_LBS`."""
    return planning_mode.beam_lbs(
        _LOW_DENIER_FRESH_LBS if beam.denier <= _LOW_DENIER_THRESHOLD
        else _HIGH_DENIER_FRESH_LBS
    )


def _doff_hours() -> float:
    """`DOFF_DURATION`, or the planning-mode handling time."""
    return planning_mode.handling_hours(DOFF_DURATION)


# Running efficiency: the share of scheduled running time a machine actually
# knits, once unplanned stops (a defect, waiting for a fixer) are taken out.
# A style's `machine_rates` are nominal lbs per running hour (rpm × 60 / 480
# revs per rack × rack_wt / 100); every rate the model uses is scaled by this.
# Planned stops (doffs, threading, changeovers) are separate activities; the
# threading team's limited throughput — beams waiting to be re-threaded — is
# folded in here too (0.85 × 0.9) rather than rationed.
RUNNING_EFFICIENCY: float = 0.765


def effective_rate(nominal: float, mtype: str) -> float:
    """A machine's working rate from a style's nominal rate: scaled by
    `RUNNING_EFFICIENCY` (or planning mode's efficiency)."""
    return nominal * planning_mode.efficiency(RUNNING_EFFICIENCY, mtype)


def stock_order(b: BeamSet) -> tuple:
    """The pull order of stock: large (40 in) sets first — the plant wants
    them used up — then the oldest received, then the lowest set number.
    See "Beam-set inventory" and "Large beams" in DESIGN.md."""
    return (0 if b.is_large else 1, b.avail_date, b.set_no)


def choose_stock(cands: list[BeamSet]) -> BeamSet:
    """The stock set to hang from `cands` (sets that fit the bar, that the
    machine accepts, available and not yet taken): the first in
    `stock_order` — a large set before any other, then the oldest received,
    then the lowest set number. Sets under `MIN_STOCK_SET_LBS` are ignored
    unless they are all there is. See "Beam-set inventory" in DESIGN.md."""
    heavy = [b for b in cands if b.lbs >= MIN_STOCK_SET_LBS]
    pool = heavy or cands
    return min(pool, key=stock_order)


@dataclass(frozen=True)
class PassedOver:
    """A plant-assigned set a hang dropped from a bar's queue because it did
    not fit the bar's requirement at the time (see "Assigned sets and bar
    queues" in DESIGN.md): the bar, the set as the queue described it, the
    requirement it failed, the hang's start and the reason: `'does not fit'`,
    or `'blacklisted'` for a set whose merge the run blacklisted (see
    "Blacklisted merges" in DESIGN.md)."""
    bar: Literal['top', 'btm']
    beam_set: BeamSet
    wanted: BeamSetDesc
    at: datetime
    reason: str = 'does not fit'


class UnhungAssignments(ValueError):
    """`plan_production(assign=)` named sets the plan never got to hang:
    `leftover` is `{bar: [set numbers]}` of them. A `ValueError`, so callers
    that do not care treat it as any refused assignment."""

    def __init__(self, leftover: dict[str, list[str]]) -> None:
        super().__init__(f'assigned sets never hung by this plan: {leftover}')
        self.leftover = leftover


@dataclass(frozen=True)
class Fill:
    """What a plan's preamble may knit instead of idling while it waits for
    a changeover-ration slot (see "Filling a slot wait" in DESIGN.md):
    whole `rolls` of the machine's *current* item the plant still wants,
    raised against `tgt_order`."""
    rolls: int
    tgt_order: str | None = None


@dataclass
class _PlanCtx:
    """Per-`plan_production` scratch: the (read-only) inventory the plan
    draws on, per-bar queues of manually assigned set numbers, the stock
    sets it has hung so far (so one set is not hung twice in a plan), the
    sets it has taped out for return and the queued sets it passed over."""
    inventory: 'InventoryView'
    assigned: dict[str, deque['str | None']] = field(default_factory=dict)
    taken: list[BeamSet] = field(default_factory=list)
    returned: list[BeamSet] = field(default_factory=list)
    taken_ids: set[str] = field(default_factory=set)
    passed: list[PassedOver] = field(default_factory=list)
    # The set most recently taped out of each bar in this plan — the set a
    # changeover's hang replaces, for the continuity rule in `pick`.
    removed: dict[str, BeamSet] = field(default_factory=dict)
    # The changeover ration the plan's tape-outs and pattern changes are
    # placed against (None: unrationed), and the slots it has taken.
    capacity: 'ChangeoverCapacity | None' = None
    slots: list['Slot'] = field(default_factory=list)
    # The fill the caller allowed (None: a slot wait is idle), the rolls of
    # it still unused, and the rolls and activities the fill has produced —
    # one budget across every wait in the preamble.
    fill: 'Fill | None' = None
    fill_left: int = 0
    fill_rolls: list[Roll] = field(default_factory=list)
    fill_acts: list[Activity] = field(default_factory=list)
    # Whether the machine is new: an old one cannot take a large (40 in)
    # set (see "Large beams" in DESIGN.md).
    is_new: bool = False

    def accepts(self, beam_set: BeamSet) -> bool:
        return self.is_new or not beam_set.is_large

    def pick(self, desc: BeamSetDesc, at: datetime, bar: str,
             working: 'Status | None' = None,
             prev: 'BeamSet | None' = None) -> BeamSet:
        """The set to hang on `bar` for `desc` at `at`, in order of
        precedence: (1) the front of the bar's **queue** on `working` — the
        set the plant has already assigned to that bar and not yet threaded
        — when it fits `desc` and has been received by `at`; it is locked
        in, so a caller assignment for this hang must be None or that set's
        number (else `ValueError`); (2) a set number the caller assigned for
        `bar` (`plan_production(assign=)`; must be in stock under `desc`,
        available and not already taken — else `ValueError`); (3) a stock
        set that is available and not already taken in this plan, chosen
        by `choose_stock` for continuity with `prev`, the set coming off the
        bar; (4) an invented set. See "Beam-set inventory" in DESIGN.md.
        A queue front that does not fit `desc` is expected to have been
        passed over already (`pass_over`), so it is never hung here."""
        queue = self.assigned.get(bar)
        set_no = queue.popleft() if queue else None   # None = "not this hang"
        if working is not None:
            staged = working.queue(bar)
            if staged and staged[0].fits(desc) and staged[0].available_at(at):
                front = staged[0]
                if set_no is not None and set_no != front.set_no:
                    raise ValueError(
                        f'set {front.set_no!r} is assigned to the {bar} bar by '
                        f'the plant and hangs at {at.isoformat()}; it cannot be '
                        f'replaced by {set_no!r}'
                    )
                return front                     # popped by Status on hang
        if set_no is not None:
            return self._take_assigned(set_no, desc, at, bar)
        cands = [b for b in self.inventory.get(desc.physical, ())
                 if b.available_at(at) and b.id not in self.taken_ids and self.accepts(b)]
        if cands:
            return self._take(choose_stock(cands))
        return BeamSet.new(desc, fresh_beam_lbs(desc), at)

    def pass_over(self, working: 'Status', bar: Literal['top', 'btm'],
                  desc: BeamSetDesc, at: datetime) -> 'Status':
        """Drop from `bar`'s queue on `working` every front set that does not
        fit `desc` — the plant staged it for a bar that now needs other
        yarn, or its merge is blacklisted and it fits nothing — recording
        each as a `PassedOver` with the reason; returns the status with the
        queue so trimmed (unchanged when the front fits or the queue is
        empty). The set stays at the machine physically, so it does not
        return to stock."""
        while working.queue(bar) and not (working.queue(bar)[0].fits(desc)
                                          and self.accepts(working.queue(bar)[0])):
            front = working.queue(bar)[0]
            reason = ('blacklisted' if front.blacklisted
                      else 'does not fit' if not front.fits(desc)
                      else 'too large for this machine')
            self.passed.append(PassedOver(bar, front, desc, at, reason=reason))
            working = working.drop_queued(bar)
        return working

    def _take(self, beam_set: BeamSet) -> BeamSet:
        self.taken.append(beam_set)
        self.taken_ids.add(beam_set.id)
        return beam_set

    def _take_assigned(self, set_no: str, desc: BeamSetDesc, at: datetime,
                       bar: str) -> BeamSet:
        for b in self.inventory.get(desc.physical, ()):
            if b.id == set_no:
                if b.id in self.taken_ids:
                    raise ValueError(
                        f'assigned set {set_no!r} ({bar}) is already hung '
                        f'earlier in this plan'
                    )
                if not b.available_at(at):
                    raise ValueError(
                        f'assigned set {set_no!r} ({bar}) is not available '
                        f'until {b.avail_date.isoformat()} (needed {at.isoformat()})'
                    )
                if not self.accepts(b):
                    raise ValueError(
                        f'assigned set {set_no!r} ({bar}) is too large for this machine'
                    )
                return self._take(b)
        raise ValueError(
            f'assigned set {set_no!r} ({bar}) is not in stock as '
            f'{desc.physical.id!r}'
        )

    def unused_assignments(self) -> dict[str, list[str]]:
        """Assigned set numbers the plan never got to hang (placeholders
        don't count)."""
        out = {bar: [s for s in q if s is not None] for bar, q in self.assigned.items()}
        return {bar: q for bar, q in out.items() if q}


# The runout-model constants `BEAM_FLOOR_LBS` / `MAX_BEAM_WASTE_LBS` live in
# `activity.py` (imported above) so `status.py` can share them without a
# circular import.


# Tolerance for float arithmetic in plan_production. Beam capacities use
# floating-point division by top_pct / btm_pct, which can produce values
# like 499.99999999999994 where 500.0 is meant. We round to nearest
# multiple of tgt_wt within this tolerance to avoid spurious Waste
# emissions at clean roll boundaries.
_FLOAT_EPS = 1e-6
_ROLL_TOLERANCE = 1e-2


@dataclass(frozen=True)
class ProductionPlan:
    """Return value of `plan_production`: the activity-schedule and
    production-schedule additions for one planning call, plus its effect on
    the beam-set inventory. Committed together via
    `add_activities(plan.activities)` + `add_jobs(plan.jobs)`, and by
    removing `beam_sets_taken` from / adding `beam_sets_returned` to the
    inventory. A basic data record — no behavior."""
    activities: tuple[Activity, ...]
    jobs: tuple[Job, ...]
    # Stock sets the plan hung (invented sets are not listed — they were
    # never in inventory).
    beam_sets_taken: tuple[BeamSet, ...] = ()
    # Sets the plan taped out that are still worth stocking, each carrying
    # its remaining lbs and the tape-out's end as `avail_date`.
    beam_sets_returned: tuple[BeamSet, ...] = ()
    # The machine's last committed job recreated (same id) with this plan's
    # changeover `TapeOut` appended to its activities — set when the plan
    # tapes out the previous item's sets and that item's job is already on
    # the schedule (see "Job activities" in DESIGN.md). Committing the plan
    # swaps it in for the original (`Machine.replace_last_job`).
    replaced_job: Job | None = None
    # The changeover-ration slots the plan's tape-outs and pattern changes
    # occupy — `(kind, period day, units, start)` each; committing books
    # them (see "Changeover capacity" in DESIGN.md).
    capacity_taken: tuple['Slot', ...] = ()
    # Plant-assigned sets a hang in this plan dropped from a bar's queue
    # because they did not fit; committing keeps them on the machine
    # (`Machine.queue_passed_over`) for the planners to report.
    queue_passed_over: tuple[PassedOver, ...] = ()


class Machine(HasID[str]):
    """Single knitting machine. Owns an append-only sequence of activities
    and the derived `Status` after each. `plan_production` produces a
    `ProductionPlan` to enact a desired production goal — handling the
    changeover preamble (tape-outs, re-threads, the changeover activity as
    needed), optional run-up of the current item, and the new item's
    production loop (a `Knit` + `Doff` per roll) with mid-stream re-threads
    when beams run out mid-request."""

    def __init__(
        self,
        id: str,
        init_item: 'Greige',
        start: datetime,
        init_top_beam: BeamSet,
        init_top_lbs: float,
        init_btm_beam: BeamSet,
        init_btm_lbs: float,
        workcal: 'WorkCal',
        is_new: bool = False,
        init_variant: 'str | None' = None,
        variant_map: 'VariantMapFile | None' = None,
        init_roll_lbs_remaining: float = 0.0,
        init_top_queue: Sequence[BeamSet] = (),
        init_btm_queue: Sequence[BeamSet] = (),
        init_top_threaded: bool = True,
        init_btm_threaded: bool = True,
    ) -> None:
        if init_roll_lbs_remaining < 0:
            raise ValueError('init_roll_lbs_remaining must be non-negative')
        self._id = id
        self._workcal = workcal
        self._is_new = is_new
        self._init_variant = init_variant
        self._variant_map = variant_map
        # A machine begins threaded and running the init item on both bars,
        # possibly part-way through a roll (`init_roll_lbs_remaining` still
        # to knit on it; 0 = between rolls). A bar whose reported set does
        # not fit the item is *foreign* (the plant reported the machine
        # mid-change): no roll can be in progress across it, so the roll is
        # taken as finished — see "Foreign bars" in DESIGN.md.
        # A bar the plant has hung but not threaded (`init_*_threaded`
        # False) likewise carries no roll in progress — see "Hung bars".
        # So does a set the machine cannot take at all (a large beam on an
        # old machine — see "Large beams"), and a machine on an item it
        # cannot run (see "An item the machine cannot run").
        cfg = init_item.configuration
        foreign = (not init_top_beam.fits(BeamSetDesc(cfg.top_beam))
                   or not init_btm_beam.fits(BeamSetDesc(cfg.btm_beam))
                   or not self.accepts(init_top_beam) or not self.accepts(init_btm_beam)
                   or not init_top_threaded or not init_btm_threaded
                   or not init_item.can_run_on_mchn(id))
        self._initial_status = Status.create(
            as_of=start,
            current_item=init_item,
            is_idle=True,
            top_beam=init_top_beam,
            top_lbs_remaining=init_top_lbs,
            top_threaded=init_top_threaded,
            btm_beam=init_btm_beam,
            btm_lbs_remaining=init_btm_lbs,
            btm_threaded=init_btm_threaded,
            roll_lbs_remaining=(0.0 if foreign
                                else min(init_roll_lbs_remaining, init_item.tgt_wt)),
            top_queue=init_top_queue, btm_queue=init_btm_queue,
        )
        self._activities: list[Activity] = []
        self._jobs: list[Job] = []
        self._passed_over: list[PassedOver] = []
        self._current_status: Status = self._initial_status

    @property
    def id(self) -> str:
        return self._id

    @property
    def workcal(self) -> 'WorkCal':
        return self._workcal

    def accepts(self, beam_set: BeamSet) -> bool:
        """Whether the set can go on this machine: False only for a large
        (40 in) set on an old machine — see "Large beams" in DESIGN.md. The
        yarn match is a separate question (`BeamSet.fits`)."""
        return self._is_new or not beam_set.is_large

    @property
    def is_new(self) -> bool:
        """True for modern/digital machines, where every changeover is a
        uniform brief reconfigure regardless of pattern family. Selects the
        changeover activity type: a new machine emits a `StyleChange`; a
        legacy machine emits a `RunnerChange` (same pattern family) or a
        `PatternChange` (cross-family). See "Beam-swap decision" in
        `schedule/DESIGN.md`."""
        return self._is_new

    @property
    def init_variant(self) -> 'str | None':
        """The plant's variant name for what the machine was running at
        `start`, when the machines file named one (else `None` — the machine
        is known only by its master item)."""
        return self._init_variant

    @property
    def initial_status(self) -> Status:
        return self._initial_status

    @property
    def current_status(self) -> Status:
        return self._current_status

    @property
    def can_run_current_item(self) -> bool:
        """Whether the machine may knit its current item — the style's
        machine list names it (`Greige.can_run_on_mchn`; True for `NONE`).
        False for a machine still set up for a style the plant has pulled
        from it: no run-up, no fill, the roll in progress zeroed — see "An
        item the machine cannot run" in DESIGN.md."""
        return self._current_status.current_item.can_run_on_mchn(self._id)

    @property
    def activities(self) -> tuple[Activity, ...]:
        return tuple(self._activities)

    @property
    def jobs(self) -> tuple[Job, ...]:
        """The committed production schedule — `Job` records appended via
        `add_jobs`. Parallel to `activities`; `Job`s have no machine-state
        effect (they record the rolls produced, not machine time)."""
        return tuple(self._jobs)

    def rebind_sets(self, mapping: Mapping[str, BeamSet]) -> None:
        """Relabel every set whose id is in `mapping` — a placeholder a plan
        invented — throughout the committed schedule with the mapped set's
        identity under the plan's pounds (`BeamSet.relabelled`): the
        activities (`activity.rebind_sets`), the jobs and rolls that
        reference them (same objects, same ids) and the initial and current
        statuses. Lbs and times are untouched, so the statuses re-derive as
        before. See "Assigning sets after planning" in DESIGN.md."""
        if not mapping:
            return

        def relabel(bs: 'BeamSet | None') -> 'BeamSet | None':
            if bs is None or bs.id not in mapping:
                return bs
            return bs.relabelled(mapping[bs.id])

        rebound: dict[int, Activity] = {}

        def act(a: Activity) -> Activity:
            key = id(a)
            if key not in rebound:
                rebound[key] = rebind_sets(a, relabel)
            return rebound[key]

        self._activities = [act(a) for a in self._activities]
        self._jobs = [
            replace(job,
                    activities=tuple(act(a) for a in job.activities),
                    rolls=tuple(replace(r, knits=tuple(act(k) for k in r.knits))
                                for r in job.rolls))
            for job in self._jobs
        ]
        self._initial_status = self._initial_status.rebind_sets(relabel)
        self._current_status = self._current_status.rebind_sets(relabel)

    @property
    def queue_passed_over(self) -> tuple[PassedOver, ...]:
        """Every plant-assigned set a committed plan dropped from a bar's
        queue because it did not fit the bar's requirement at the hang, in
        commit order (see "Assigned sets and bar queues" in DESIGN.md)."""
        return tuple(self._passed_over)

    @property
    def schedule_tail(self) -> datetime:
        """End time of the last scheduled activity, or `initial_status.as_of`
        if no activities have been added."""
        return self._current_status.as_of

    @property
    def next_runout(self) -> datetime:
        """Forward-extrapolated time at which the machine would change over
        after running `current_status.current_item` from
        `current_status.as_of`. Matches `plan_production`'s whole-roll
        behavior: the run-up produces whole rolls only, each followed by a
        `Doff`, so this is the end of the **last whole roll** (after its
        `Doff`) that finishes above the floor (`BEAM_FLOOR_LBS`) — not the
        instant a beam first crosses the floor.
        Real greiges always draw from both bars (top_pct, btm_pct > 0), so
        this is always well-defined. When fewer than one whole roll fits
        above the floor (including a bar already at or below it),
        `next_runout == current_status.as_of` — the changeover is
        immediately due. A roll in progress at the initial status is
        finished first (see `_emit_run_up`): when the current beams can
        finish it, its knit and doff precede the whole rolls; when they
        can't, finishing it forces a mid-roll re-thread, which *is* the
        runout, and the prediction is that roll's `Doff.end` — obtained by
        running the run-up walk itself (rare, and cheap: one roll)."""
        s = self._current_status
        _n_rolls, hours, walked = self._run_up_outline()
        if walked is not None:
            return walked
        if hours <= 0.0:
            return s.as_of
        # Offset in two steps — everything up to the last Doff, then the Doff
        # — rather than one sum: a single offset can land on a work-day's end
        # where the walk's final Doff lands on the next day's start (the same
        # work moment, a different datetime), and this must equal the run-up's
        # last `Doff.end` exactly.
        t = self._workcal.offset_work_hours(s.as_of, hours - _doff_hours())
        return self._workcal.offset_work_hours(t, _doff_hours())

    def _rate(self, item: 'Greige') -> float:
        """`item`'s working rate on this machine, lbs per hour: its nominal
        `machine_rates` entry scaled by the running efficiency."""
        return effective_rate(item.get_rate_on_mchn(self._id), 'new' if self.is_new else 'old')

    def run_until(
        self, t: datetime, inventory: 'InventoryView | None' = None,
    ) -> 'ProductionPlan | None':
        """Keep the machine on its current item up to `t` — the moment the
        plant can first change it over: a plan (via `plan_production` in
        `'schedule_tail'` mode) that finishes the roll in progress and every
        whole roll that *starts* before `t`, so the last roll may run past
        `t`. A machine with nothing to run (the `NONE` item, or an item it
        cannot run — "An item the machine cannot run" in DESIGN.md) gets one
        `Idle` up to `t` instead, so no changeover can be placed before it.
        `None` when `t` is not after the schedule
        tail. The caller commits the plan (`commit_plan` / the planner's
        `State.commit_move`)."""
        s = self._current_status
        if t <= s.as_of:
            return None
        item = s.current_item
        rate = (self._rate(item)
                if item.id != 'NONE' and item.can_run_on_mchn(self._id) else 0.0)
        if rate <= 0.0:
            hours = self._workcal.get_work_hours_between(s.as_of, t)
            if hours <= 0.0:
                return None
            emitted: list[Activity] = []
            self._emit_idle(emitted, s, timedelta(hours=hours))
            return ProductionPlan(activities=tuple(emitted), jobs=())
        now = s.as_of
        if s.roll_lbs_remaining > _FLOAT_EPS:            # the roll in progress
            now = self._workcal.offset_work_hours(
                now, s.roll_lbs_remaining / rate + _doff_hours())
        n = 0
        while now < t:                                   # rolls starting before t
            n += 1
            now = self._workcal.offset_work_hours(now, item.tgt_wt / rate + _doff_hours())
        return self.plan_production(item, n * item.tgt_wt, 'schedule_tail',
                                    inventory=inventory)

    @property
    def whole_rolls_before_runout(self) -> int:
        """How many rolls the machine doffs running `current_status.current_item`
        from `current_status.as_of` until the changeover at `next_runout` —
        the roll in progress (if the current beams can finish it) plus the
        whole rolls that fit above the floor; 0 when the changeover is
        immediately due. Same model as `next_runout`."""
        return self._run_up_outline()[0]

    def _run_up_outline(self) -> tuple[int, float, datetime | None]:
        """`(rolls, hours, walked)` for running the current item from the
        current status to its runout: `rolls` doffed (a finishable roll in
        progress counts), `hours` of work they take (knits + doffs). When
        finishing the roll in progress needs beam work (the pre-roll
        max-waste gate, or a mid-roll re-thread because the beams can't
        supply the rest) the run-up walk is simulated instead: `walked` is
        then its end (`next_runout`), `rolls` the doffs it emitted, and
        `hours` is not meaningful (0)."""
        s = self._current_status
        item = s.current_item
        cfg = item.configuration
        rate = self._rate(item)
        top_lbs, btm_lbs = self._run_up_lbs(s)
        hours = 0.0
        n_rolls = 0

        remaining = s.roll_lbs_remaining
        if remaining > _FLOAT_EPS:
            top_u = top_lbs - BEAM_FLOOR_LBS
            btm_u = btm_lbs - BEAM_FLOOR_LBS
            producible = min(top_u / cfg.top_pct, btm_u / cfg.btm_pct)
            # A roll with nothing wound yet passes the pre-roll max-waste
            # gate like any fresh roll (see `_wind_rolls`).
            gated = (remaining >= item.tgt_wt - _FLOAT_EPS
                     and min(top_u, btm_u) < MAX_BEAM_WASTE_LBS)
            if gated or producible < remaining - _FLOAT_EPS:
                # Finishing needs beam work (a gate swap, or a mid-roll
                # re-thread because the beams can't supply the rest): the
                # walk decides what follows — simulate it exactly.
                scratch: list[Activity] = []
                working = self._emit_run_up(
                    scratch, s, [], _PlanCtx({}), whole_rolls=True,
                )
                return sum(isinstance(a, Doff) for a in scratch), 0.0, working.as_of
            hours += remaining / rate + _doff_hours()
            n_rolls += 1
            top_lbs -= remaining * cfg.top_pct
            btm_lbs -= remaining * cfg.btm_pct

        whole = _whole_rolls_before_floor(
            top_lbs, cfg.top_pct, btm_lbs, cfg.btm_pct, item.tgt_wt,
        )
        # Each whole roll costs its knit time plus a Doff.
        hours += whole * (item.tgt_wt / rate + _doff_hours())
        return n_rolls + whole, hours, None

    def _run_up_lbs(self, working: Status) -> tuple[float, float]:
        """`(top, btm)` lbs the run-up may draw on for `working.current_item`:
        each bar's remaining lbs, or 0 for a **foreign** bar — one whose set
        does not fit the item (a machine the plant reported mid-change), which
        holds no usable yarn for the item and so allows no whole roll of it;
        the preamble meets the set with its real lbs (see "Foreign bars" in
        DESIGN.md). `(0, 0)` outright for an item the machine cannot run
        (see "An item the machine cannot run"), whatever its sets."""
        if not working.current_item.can_run_on_mchn(self._id):
            return 0.0, 0.0
        cfg = working.current_item.configuration
        out = []
        for bar, label in (('top', cfg.top_beam), ('btm', cfg.btm_beam)):
            beam = working.beam(bar)
            fits = (beam is not None and beam.fits(BeamSetDesc(label))
                    and self.accepts(beam)            # a large set on an old machine
                    and working.threaded(bar))        # a hung bar cannot knit yet
            out.append(working.lbs_remaining(bar) if fits else 0.0)
        return out[0], out[1]

    def producible_lbs_through(
        self, item: 'Greige', end: datetime,
        start: datetime | None = None,
        inventory: 'InventoryView | None' = None,
        capacity: 'ChangeoverCapacity | None' = None,
        fill: 'Fill | None' = None,
    ) -> float:
        """Returns the lbs of `item` the machine could produce in the
        window `[start, end)`. `fill` is passed through to `plan_production`
        so a slot wait filled with the current item counts against the
        window the way it will in the plan.

        `start` is the earliest moment at which production may begin.
        Defaults to `current_status.as_of`. Passing a later datetime
        (e.g. `next_runout`, or a carrying-avoidance idle target) lets
        the caller ask "if I delay production until this time, how
        much fits?". `start` may not be earlier than
        `current_status.as_of` (the machine can't time-travel) —
        raises `ValueError` if so.

        Accounts for required changeover preamble, mid-stream beam
        reloads, and non-work hours via `workcal`, and rounds the
        result down to a whole multiple of `item.tgt_wt`. Returns 0.0
        if `start` is already past `end`, if the preamble alone
        exceeds the window, or if the remaining time can't accommodate
        a full roll.

        Pure: does not mutate any machine state. Implementation
        re-uses `plan_production` by asking for a generous upper bound
        and tallying the lbs of `Knit` activities whose execution
        overlaps `[start, end)`."""
        as_of = self._current_status.as_of
        if start is not None and start < as_of:
            raise ValueError(
                f'start={start!r} is before machine\'s '
                f'current_status.as_of ({as_of!r})'
            )
        effective_start = start if start is not None else as_of
        if effective_start >= end:
            return 0.0

        rate = self._rate(item)
        # Upper bound on plan_production's lbs argument: max producible
        # if the entire `[as_of, end]` span were work hours at full
        # rate, plus one roll of headroom. plan_production will simply
        # produce more activities than we need; we truncate via the
        # window check below.
        span_hours = (end - as_of).total_seconds() / 3600
        upper_lbs_bound = (
            math.ceil(span_hours * rate / item.tgt_wt) * item.tgt_wt
            + item.tgt_wt
        )

        # Bridge: idle from the machine's actual schedule tail (as_of)
        # to the production-begin moment, `effective_start`. The bridge
        # is measured in **work hours** so a non-work gap (weekend
        # under a weekday workcal) collapses to zero and
        # `plan_production` picks up at the next work moment naturally.
        bridge_hours = self._workcal.get_work_hours_between(
            as_of, effective_start,
        )
        idle_for = timedelta(hours=bridge_hours)
        plan = self.plan_production(
            item, upper_lbs_bound, start_at='schedule_tail',
            idle_for=idle_for, inventory=inventory, capacity=capacity,
            fill=fill,
        )

        # Tally lbs of `Knit`s for `item` that overlap
        # [effective_start, end). Activities other than Knit (Doff, TapeOut,
        # Hanging, Threading, the changeovers, Waste, Idle) consume time but
        # produce nothing; their effect on production capacity is already
        # reflected in subsequent Knits' start times.
        total_lbs = 0.0
        for a in plan.activities:
            if a.start >= end:
                break
            if not isinstance(a, Knit):
                continue
            if a.item != item:
                continue
            if a.end <= effective_start:
                continue
            win_start = max(a.start, effective_start)
            win_end = min(a.end, end)
            hours_in_window = self._workcal.get_work_hours_between(
                win_start, win_end,
            )
            total_lbs += hours_in_window * rate

        # Round down to whole rolls, snapping near-integer rolls (float
        # drift from `min(top_lbs/top_pct, btm_lbs/btm_pct) * rate`
        # chains).
        n_rolls_exact = total_lbs / item.tgt_wt
        n_rolls_rounded = round(n_rolls_exact)
        if abs(n_rolls_rounded - n_rolls_exact) < _ROLL_TOLERANCE:
            n_rolls = n_rolls_rounded
        else:
            n_rolls = math.floor(n_rolls_exact)
        return max(0, n_rolls) * item.tgt_wt

    def producible_lbs_in_week(
        self, item: 'Greige', year: int, week: int,
        start: datetime | None = None,
        inventory: 'InventoryView | None' = None,
    ) -> float:
        """Returns the lbs of `item` the machine could produce within
        the given ISO week (Monday 00:00 to next Monday 00:00).

        Thin wrapper over `producible_lbs_through`: snaps `start` up to
        `week_start` if it falls before the week begins (so the bridge
        idle covers the gap to the week's beginning), then asks for
        the cap through `week_end`.

        `start` defaults to `current_status.as_of` and may not be
        earlier than it — raises `ValueError` otherwise."""
        monday = date.fromisocalendar(year, week, 1)
        week_start = datetime(monday.year, monday.month, monday.day)
        week_end = week_start + timedelta(days=7)

        as_of = self._current_status.as_of
        if start is not None and start < as_of:
            raise ValueError(
                f'start={start!r} is before machine\'s '
                f'current_status.as_of ({as_of!r})'
            )
        effective_start = start if start is not None else as_of
        # Snap to week_start if effective_start falls before the week.
        effective_start = max(effective_start, week_start)
        return self.producible_lbs_through(
            item, end=week_end, start=effective_start, inventory=inventory,
        )

    def status_at(self, t: datetime) -> Status:
        """Status at time `t`. Walks activities whose `end <= t`, then sets
        `as_of=t` on the result. If `t` falls strictly inside an activity
        (`start <= t < end`), `is_idle` is False; otherwise True. Raises if
        `t` is before `initial_status.as_of`."""
        if t < self._initial_status.as_of:
            raise ValueError(
                f't={t!r} is before this machine\'s initial status '
                f'({self._initial_status.as_of!r})'
            )

        status = self._initial_status
        in_progress = False
        for activity in self._activities:
            if activity.end <= t:
                status = status.apply_activity(activity)
            else:
                if activity.start <= t:
                    in_progress = True
                break

        return replace(status, as_of=t, is_idle=not in_progress)

    def add_activities(self, activities: Iterable[Activity]) -> None:
        """Append activities to the schedule and roll `current_status`
        forward. Activities are expected in execution order, each starting
        at or after the previous one's end."""
        for a in activities:
            self._activities.append(a)
            self._current_status = self._current_status.apply_activity(a)

    def add_jobs(self, jobs: Iterable[Job]) -> None:
        """Append `Job` records to the production schedule. Jobs carry no
        machine-state effect, so (unlike `add_activities`) this does not
        touch `current_status` — it only records what was produced."""
        self._jobs.extend(jobs)

    def replace_last_job(self, job: Job) -> None:
        """Swap the last job on the production schedule for `job`, a recreated
        copy with the same id (see `ProductionPlan.replaced_job`). Raises if
        there is no last job or the ids differ."""
        if not self._jobs or self._jobs[-1].id != job.id:
            have = self._jobs[-1].id if self._jobs else None
            raise ValueError(
                f'replace_last_job: {job.id!r} is not the last job ({have!r})'
            )
        self._jobs[-1] = job

    def commit_plan(self, plan: 'ProductionPlan') -> None:
        """Apply a `ProductionPlan` to this machine: append its activities,
        swap in its `replaced_job` (if any), then append its jobs. The
        inventory and demand-side effects are the caller's (see the
        planner's `State.commit_move`)."""
        self.add_activities(plan.activities)
        if plan.replaced_job is not None:
            self.replace_last_job(plan.replaced_job)
        self.add_jobs(plan.jobs)
        self._passed_over.extend(plan.queue_passed_over)

    # ----- plan_production --------------------------------------------

    def plan_production(
        self,
        item: 'Greige',
        lbs: float,
        start_at: Literal['schedule_tail', 'next_runout'],
        idle_for: timedelta = timedelta(0),
        tgt_order: str | None = None,
        inventory: 'InventoryView | None' = None,
        assign: 'Mapping[str, Sequence[str | None]] | None' = None,
        capacity: 'ChangeoverCapacity | None' = None,
        prior_job: str | None = None,
        fill: 'Fill | None' = None,
    ) -> 'ProductionPlan':
        """Plan production of `lbs` of `item` on this machine. Pure — does
        not mutate state, nor the `inventory` or `capacity` it reads.

        `capacity` is the plant's changeover ration (`schedule.capacity`):
        the preamble takes one `change` unit when it changes the machine at
        all (a tape-out or a changeover activity), and places each
        `TapeOut` (one unit per bar) and each old machine's `PatternChange`
        (one unit) at the next slot the ration allows, emitting an `Idle`
        (with its `reason`) while the machine waits, and reports the slots
        as `capacity_taken` for the caller to book when it commits. None
        (or an unrationed kind) never waits.

        `fill` lets a wait be spent knitting: whole rolls of the machine's
        current item, up to `fill.rolls` across the preamble's waits, as
        long as the beams can finish one and the roll starts before the
        slot (see "Filling a slot wait" in DESIGN.md). They go on the
        current item's job — the run-up job, extended, or a new job raised
        against `fill.tgt_order` — marked `fill`.

        `assign` (manual scheduling) queues set numbers per bar (`'top'` /
        `'btm'`): each hang on that bar takes the next queued set from the
        inventory instead of the automatic pick. A `None` in the list leaves
        that hang to the normal choice (the machine's own queue, then stock),
        so `[None, 'X']` assigns only the bar's second hang. A queued set
        that is not in stock under the bar's requirement, not yet available,
        or already hung in this plan raises `ValueError`, as does a queued
        set the plan never gets to hang — a manual assignment is never
        silently dropped.

        `inventory` is the beam-set stock (`schedule.inventory`) a `Hanging`
        may draw on: for each bar it needs, the available, not-yet-taken set
        with the most lbs under the bar's physical description is hung;
        with none (or no inventory at all) a set is invented
        (`BeamSet.new`, sized by `fresh_beam_lbs`). The stock sets hung and
        the sets taped out for return are reported on the plan as
        `beam_sets_taken` / `beam_sets_returned` for the caller to apply
        when it commits.

        `idle_for` schedules an explicit `Idle` activity as the **first**
        emitted activity, used to model staff-constrained gaps where the
        machine sits unstaffed during what would otherwise be work hours.
        The entire downstream plan (run-up, preamble, production) needs an
        operator, so Idle precedes everything else.

        `tgt_order` records which order the caller is raising this call to
        fill (an order id, default `None`). It is stamped onto the new-item
        `Job` only; the `'next_runout'` run-up `Job` always carries `None`.
        It captures intent, not the order actually filled (resolved later by
        the `SafetyAwareView`).

        Walk (see DESIGN.md for details):
          0. Optional `Idle` (when `idle_for > 0`).
          1. Run-up — `'next_runout'` mode emits `Knit`/`Doff` pairs of the
             current item for whole rolls until a beam runout;
             `'schedule_tail'` mode emits nothing here.
          2. Changeover preamble — per-bar `TapeOut`/`Waste` then re-thread
             (`Hanging` + `Threading`) for any bar whose yarn doesn't match
             the new item, re-thread only for any empty bar, then the
             changeover activity if the item differs.
          3. Production loop — `Knit`/`Doff` per roll, with mid-stream
             re-threads (and `Waste`) when beams run out, until `lbs` is done.

        Returns a `ProductionPlan` carrying both the emitted activities
        and the production-schedule `Job` records: one `Job` for the new
        item, plus a run-up `Job` for the current item in `'next_runout'`
        mode (omitted when the run-up yields no whole rolls). Each
        `Job`'s rolls accumulate across any mid-run beam swaps, so a
        single `Job` can straddle one."""
        if start_at not in ('schedule_tail', 'next_runout'):
            raise ValueError(
                f"start_at must be 'schedule_tail' or 'next_runout', "
                f'got {start_at!r}'
            )
        if idle_for < timedelta(0):
            raise ValueError(f'idle_for must be non-negative, got {idle_for}')
        # 'next_runout' means "finish the current item, then change over to a
        # different one." With no item change it would emit no changeover and
        # split one continuous run into a run-up Job + new-item Job at the
        # arbitrary beam-runout boundary — a caller mistake ('schedule_tail'
        # is the way to continue the current item).
        if (start_at == 'next_runout'
                and item == self._current_status.current_item):
            raise ValueError(
                "'next_runout' mode requires a changeover, but item "
                f'{item.id!r} is already the machine\'s current item'
            )

        if assign:
            bad = set(assign) - {'top', 'btm'}
            if bad:
                raise ValueError(f"assign keys must be 'top' / 'btm', got {sorted(bad)}")
        emitted: list[Activity] = []
        jobs: list[Job] = []
        working = self._current_status
        if fill is not None and fill.rolls < 0:
            raise ValueError(f'fill.rolls must be non-negative, got {fill.rolls}')
        ctx = _PlanCtx(
            inventory if inventory is not None else {},
            assigned={bar: deque(sets) for bar, sets in (assign or {}).items()},
            capacity=capacity,
            fill=fill, fill_left=fill.rolls if fill is not None else 0,
            is_new=self._is_new,
        )

        # 0. Optional idle gap at the head of the plan (belongs to no job).
        if idle_for > timedelta(0):
            working = self._emit_idle(emitted, working, idle_for)

        # 1. Run-up: always finish a roll in progress; in 'next_runout' mode
        #    also run whole rolls of the current item to the runout.
        working = self._emit_run_up(
            emitted, working, jobs, ctx, whole_rolls=(start_at == 'next_runout'),
        )

        # 2. Changeover preamble. Its TapeOut (if any) ends the *previous*
        #    item's job; the re-thread and changeover open the new item's.
        pre_start = len(emitted)
        cur = working.current_item
        working = self._emit_preamble(emitted, working, item, ctx)
        preamble = emitted[pre_start:]
        tape_outs = [a for a in preamble if isinstance(a, TapeOut)]
        # A slot wait (`Idle`) belongs to no job, like the head idle; the
        # only `Knit`s / `Doff`s a preamble holds are a fill's, which are
        # the current item's (below).
        setup = [a for a in preamble
                 if not isinstance(a, (TapeOut, Unhang, Waste, Idle, Knit, Doff))]

        # The fill's rolls join the current item's job: the run-up job, or a
        # new one when the run-up produced nothing.
        if ctx.fill_rolls:
            if jobs:
                jobs[0] = replace(
                    jobs[0], rolls=jobs[0].rolls + tuple(ctx.fill_rolls),
                    activities=jobs[0].activities + tuple(ctx.fill_acts), fill=True)
            else:
                jobs.append(Job(item=cur, rolls=tuple(ctx.fill_rolls),
                                tgt_order=ctx.fill.tgt_order,
                                activities=tuple(ctx.fill_acts), fill=True))

        replaced_job = None
        if tape_outs:
            if jobs:                        # the run-up job is the previous job
                jobs[0] = jobs[0].with_activities(tape_outs)
            elif self._jobs:                # previous job is already committed
                replaced_job = self._jobs[-1].with_activities(tape_outs)
            # else: nothing produced the previous item's sets — orphaned.

        # 3. Production loop for the new item.
        self._emit_production_loop(
            emitted, working, item, lbs, jobs, ctx, tgt_order, setup=setup,
            prior_job=prior_job,
        )
        leftover = ctx.unused_assignments()
        if leftover:
            raise UnhungAssignments(leftover)
        return ProductionPlan(
            activities=tuple(emitted), jobs=tuple(jobs),
            beam_sets_taken=tuple(ctx.taken),
            beam_sets_returned=tuple(ctx.returned),
            replaced_job=replaced_job,
            capacity_taken=tuple(ctx.slots),
            queue_passed_over=tuple(ctx.passed),
        )

    # ----- private plan_production helpers -----

    def _emit_run_up(
        self, emitted: list[Activity], working: Status, jobs: list[Job],
        ctx: _PlanCtx, whole_rolls: bool,
    ) -> Status:
        """Production of `working.current_item` before any changeover, as one
        current-item `Job` (omitted when nothing is produced):

        1. **Finish the roll in progress** (`working.roll_lbs_remaining > 0`,
           only ever true at a machine's initial status) — always, in both
           modes: the plant never doffs a roll short. It is wound with the
           production loop's roll mechanics pre-filled to `tgt_wt - remaining`,
           so a bar that runs out mid-roll gets the normal mid-roll re-thread
           (a fresh set of the *current* item's yarn just to complete the
           roll — expensive, and meant to be).
        2. **Whole rolls to the runout** — only when `whole_rolls`
           (`'next_runout'` mode) and only if finishing needed no re-thread
           (a re-thread *is* the runout): `Knit(tgt_wt)` + `Doff` per roll
           for as many whole rolls as the beams finish above
           `BEAM_FLOOR_LBS`, never starting a roll they can't finish. No
           `Waste`, no beam work of its own — each bar keeps its leftover
           usable yarn for the preamble.

        `next_runout` predicts this walk by running it, so the two agree
        exactly. Returns the working status with `current_item` unchanged."""
        cur = working.current_item
        cfg = cur.configuration
        first = len(emitted)
        rolls: list[Roll] = []

        remaining = working.roll_lbs_remaining
        rethreaded = False
        if remaining > _FLOAT_EPS:
            working, finished = self._wind_rolls(
                emitted, working, cur, 1, ctx,
                roll_filled=max(0.0, cur.tgt_wt - remaining),
            )
            rolls.extend(finished)
            rethreaded = any(isinstance(a, Hanging) for a in emitted[first:])

        if whole_rolls and not rethreaded:
            top_lbs, btm_lbs = self._run_up_lbs(working)   # 0 for a foreign bar
            n_rolls = _whole_rolls_before_floor(
                top_lbs, cfg.top_pct, btm_lbs, cfg.btm_pct, cur.tgt_wt,
            )
            for _ in range(n_rolls):
                working = self._emit_knit(emitted, working, cur, cur.tgt_wt)
                knit = emitted[-1]                # the Knit just emitted
                working = self._emit_doff(emitted, working)
                rolls.append(Roll(lbs=cur.tgt_wt, completion_time=working.as_of,
                                  knits=(knit,)))

        if rolls:
            jobs.append(Job(item=cur, rolls=tuple(rolls),
                            activities=tuple(a for a in emitted[first:]
                                             if not isinstance(a, Waste))))
        return working

    def _emit_preamble(
        self, emitted: list[Activity], working: Status, item: 'Greige',
        ctx: _PlanCtx,
    ) -> Status:
        """Changeover preamble. Each bar arrives in one of four states,
        resolved against the new `item`'s yarn and the bar's
        `usable = lbs_remaining(bar) - BEAM_FLOOR_LBS`:

        - Empty / at the floor (`usable <= 0`): re-thread only.
        - Yarn matches `item`: nothing — the beam and its leftover carry
          over (a near-empty match is left for the production loop's pre-roll
          gate to swap).
        - Yarn mismatches, `usable > MAX_BEAM_WASTE_LBS`: `TapeOut` +
          re-thread — preserve the worthwhile yarn.
        - Yarn mismatches, `usable <= MAX_BEAM_WASTE_LBS`: `Waste` +
          re-thread — discard the residue (zero-duration unknit drop).

        Removing (TapeOut/Waste) precedes the re-thread so the beam-swap
        guards are satisfied. When both bars tape out, a single
        `TapeOut('both')`; when both are re-threaded, a single re-thread of
        `'both'` (cheaper per the duration table). After all beam work, emit
        the changeover (`StyleChange` / `RunnerChange` / `PatternChange`) when
        `item != current_item`."""
        cfg = item.configuration

        def bar_action(bar: Literal['top', 'btm'], want_beam: str) -> str:
            """One of 'load' (empty), 'keep' (matching yarn), 'tape'
            (mismatch worth preserving), 'waste' (mismatch to discard),
            'thread' (hung by the plant, not threaded, matching yarn) or
            'unhang' (hung, not threaded, mismatched — see "Hung bars").
            "Matching" is the physical set — split lease aside."""
            usable = working.lbs_remaining(bar) - BEAM_FLOOR_LBS
            if usable <= _FLOAT_EPS:
                return 'load'
            beam = working.beam(bar)
            fits = (beam is not None and beam.fits(BeamSetDesc(want_beam))
                    and self.accepts(beam))
            if not working.threaded(bar):
                return 'thread' if fits else 'unhang'
            if fits:
                return 'keep'
            return 'tape' if usable > MAX_BEAM_WASTE_LBS else 'waste'

        top_action = bar_action('top', cfg.top_beam)
        btm_action = bar_action('btm', cfg.btm_beam)

        # A preamble that changes the machine — a tape-out or a changeover
        # activity — is one unit of the plant-wide change ration, taken
        # before any beam work (see "Changeover capacity slots" in
        # DESIGN.md). A fill while waiting draws the bars down, so the
        # actions are read again after it.
        if ('tape' in (top_action, btm_action)
                or item != working.current_item):
            working = self._wait_for_slot(emitted, working, ctx, 'change', 1, 0.0)
            top_action = bar_action('top', cfg.top_beam)
            btm_action = bar_action('btm', cfg.btm_beam)

        # Tape-out phase — batch into one 'both' when both bars tape out.
        if top_action == 'tape' and btm_action == 'tape':
            working = self._emit_tape_out(emitted, working, 'both', ctx)
        elif top_action == 'tape':
            working = self._emit_tape_out(emitted, working, 'top', ctx)
        elif btm_action == 'tape':
            working = self._emit_tape_out(emitted, working, 'btm', ctx)

        # Unhang phase — a hung, never-threaded set that does not fit comes
        # straight off again (no tape-out: nothing was threaded), back to
        # stock with all its lbs. Batched into one 'both' like a tape-out.
        if top_action == 'unhang' and btm_action == 'unhang':
            working = self._emit_unhang(emitted, working, 'both', ctx)
        elif top_action == 'unhang':
            working = self._emit_unhang(emitted, working, 'top', ctx)
        elif btm_action == 'unhang':
            working = self._emit_unhang(emitted, working, 'btm', ctx)

        # Waste phase — discard near-empty mismatched residue (the beam
        # currently on the bar). Zero duration; empties the bar.
        if top_action == 'waste':
            working = self._emit_waste(
                emitted, working, 'top',
                working.lbs_remaining('top') - BEAM_FLOOR_LBS,
            )
        if btm_action == 'waste':
            working = self._emit_waste(
                emitted, working, 'btm',
                working.lbs_remaining('btm') - BEAM_FLOOR_LBS,
            )

        # Re-thread phase — every bar that wasn't kept gets a fresh set
        # (Hanging), then every bar owed a threading — freshly hung, or
        # hung by the plant and not yet threaded — is threaded; each batched
        # into 'both' when both bars need it.
        actions = (('top', top_action), ('btm', btm_action))
        hang = [b for b, a in actions if a not in ('keep', 'thread')]
        thread = [b for b, a in actions if a != 'keep']
        if hang:
            working = self._emit_hanging(
                emitted, working, 'both' if len(hang) == 2 else hang[0], item, ctx)
        if thread:
            working = self._emit_threading(
                emitted, working, 'both' if len(thread) == 2 else thread[0])

        # Changeover phase — the right changeover type when the item changes.
        if item != working.current_item:
            working = self._emit_changeover(emitted, working, item, ctx)
        return working

    def _emit_production_loop(
        self, emitted: list[Activity], working: Status,
        item: 'Greige', lbs: float, jobs: list[Job], ctx: _PlanCtx,
        tgt_order: str | None = None, setup: Iterable[Activity] = (),
        prior_job: str | None = None,
    ) -> None:
        """Wind `lbs` of `item` (a whole multiple of `tgt_wt`) as whole rolls
        (`_wind_rolls`) and record them on one straddle-aware `Job` whose
        activities are `setup` (the preamble's re-thread and changeover, which
        prepared this item) followed by everything the loop emits except
        `Waste`, through the last roll's `Doff`."""
        loop_start = len(emitted)
        _, rolls = self._wind_rolls(
            emitted, working, item, round(lbs / item.tgt_wt), ctx,
        )
        if rolls:
            acts = tuple(setup) + tuple(
                a for a in emitted[loop_start:] if not isinstance(a, Waste)
            )
            jobs.append(Job(item=item, rolls=tuple(rolls), tgt_order=tgt_order,
                            prior_job=prior_job,
                            activities=acts))

    def _wind_rolls(
        self, emitted: list[Activity], working: Status, item: 'Greige',
        n_rolls: int, ctx: _PlanCtx, roll_filled: float = 0.0,
    ) -> tuple[Status, list[Roll]]:
        """Wind `n_rolls` rolls of `item` one roll at a time, the first one
        already holding `roll_filled` lbs (a roll in progress at the machine's
        initial status). Every roll ends in a `Doff`, so its `completion_time`
        is the `Doff`'s end; a `Knit` is one uninterrupted run that ends at a
        doff or a beam swap, so `0 < Knit.lbs <= tgt_wt`. A roll that hits a
        beam floor mid-wind continues on the fresh beam (a `Hanging` +
        `Threading`), so it can span two `Knit`s; a roll starting from empty
        first passes the max-waste gate. A pre-filled roll's knits sum to
        `tgt_wt - roll_filled`, not to the roll's weight. See the
        production-loop walk in DESIGN.md. Returns the working status after the
        last `Doff` and the rolls wound."""
        cfg = item.configuration
        tgt = item.tgt_wt
        rolls: list[Roll] = []

        rolls_left = n_rolls            # whole rolls owed
        knit = 0.0                      # lbs in the current (unflushed) Knit
        roll_knits: list[Knit] = []     # Knits wound onto the in-progress roll

        def usable(bar: Literal['top', 'btm'], pct: float) -> float:
            """Live usable yarn on a bar, net of the un-flushed Knit: a bar
            is exhausted at `usable <= 0`, near-empty below
            `MAX_BEAM_WASTE_LBS`."""
            return working.lbs_remaining(bar) - knit * pct - BEAM_FLOOR_LBS

        def flush() -> None:
            """Emit the open Knit (if any), record it on the in-progress
            roll, and reset the accumulator. The Knit's start is the current
            `working.as_of`, unchanged since the accumulator opened (nothing
            else is emitted mid-segment)."""
            nonlocal working, knit
            if knit > _FLOAT_EPS:
                working = self._emit_knit(emitted, working, item, knit)
                roll_knits.append(emitted[-1])
                knit = 0.0

        def resolve() -> None:
            """Swap any bar at/below the floor (re-thread to continue) or
            near-empty (discard its residue as `Waste`, then re-thread).
            Flushes the open Knit once before any beam work; bars swapped
            together use the 'both' re-thread (the co-swap)."""
            nonlocal working
            top_u = usable('top', cfg.top_pct)
            btm_u = usable('btm', cfg.btm_pct)
            if top_u >= MAX_BEAM_WASTE_LBS and btm_u >= MAX_BEAM_WASTE_LBS:
                return                          # neither bar needs a swap
            flush()
            swapped: list[str] = []
            for bar, u in (('top', top_u), ('btm', btm_u)):
                if u < MAX_BEAM_WASTE_LBS:
                    if u > _FLOAT_EPS:          # near-empty — discard residue
                        working = self._emit_waste(emitted, working, bar, u)
                    swapped.append(bar)
            bars = 'both' if len(swapped) == 2 else swapped[0]
            working = self._emit_rethread(emitted, working, bars, item, ctx)

        while rolls_left > 0:
            if roll_filled == 0.0:
                resolve()                       # pre-roll max-waste gate
            producible = min(
                usable('top', cfg.top_pct) / cfg.top_pct,
                usable('btm', cfg.btm_pct) / cfg.btm_pct,
            )
            step = min(tgt - roll_filled, producible)
            knit += step
            roll_filled += step
            if roll_filled >= tgt - _FLOAT_EPS:  # roll complete
                flush()                          # emit the roll's final Knit
                working = self._emit_doff(emitted, working)
                rolls.append(Roll(lbs=tgt, completion_time=working.as_of,
                                  knits=tuple(roll_knits)))
                roll_filled = 0.0
                rolls_left -= 1
                roll_knits.clear()
            else:                                # a bar hit the floor mid-roll
                resolve()                        # re-thread it; co-swap other
        return working, rolls

    # ----- single-activity emission helpers -----

    def _emit_knit(
        self, emitted: list[Activity], working: Status,
        item: 'Greige', lbs: float,
    ) -> Status:
        """Emit one `Knit` activity for `lbs` of `item` — one uninterrupted
        run (it ends at a doff or a beam swap), stamped with the variant the
        bars' merges identify (see `_variant_for`). Roll tracking is the
        caller's job: the run-up and production loop record each `Roll`
        after its `Doff`. See DESIGN.md."""
        rate = self._rate(item)
        start = working.as_of
        end = self._workcal.offset_work_hours(start, lbs / rate)
        emitted.append(Knit(start=start, end=end, item=item, lbs=lbs,
                            variant=self._variant_for(working, item),
                            top_beam=working.beam('top'), btm_beam=working.beam('btm')))
        return working.apply_activity(emitted[-1])

    def _variant_for(self, working: Status, item: 'Greige') -> 'str | None':
        """The plant variant (recipe names, comma-separated) that the merges
        on the two bars identify under `item`'s master — `None` without a
        variant map, when either set has no known merge, or when the pair
        matches no recipe. Among recipes for the same merge pair, one at the
        bars' construction is preferred."""
        if self._variant_map is None:
            return None
        top, btm = working.beam('top'), working.beam('btm')
        if (top is None or btm is None or not top.known_merge
                or not btm.known_merge):
            return None
        master = self._variant_map.masters.get(item.id)
        if master is None:
            return None
        recipes = master.lookup(top.merge, btm.merge)
        if not recipes:
            return None
        for r in recipes:
            if (r.n_beams == top.desc.spools and r.top.ends == top.desc.ends
                    and r.btm.ends == btm.desc.ends):
                return r.names
        return recipes[0].names

    def _emit_doff(
        self, emitted: list[Activity], working: Status,
    ) -> Status:
        """Emit a `Doff` taking one just-completed roll off the machine. The
        roll's `completion_time` is this `Doff`'s end (the returned status's
        `as_of`)."""
        start = working.as_of
        end = self._workcal.offset_work_hours(start, _doff_hours())
        emitted.append(Doff(start=start, end=end))
        return working.apply_activity(emitted[-1])

    def _emit_waste(
        self, emitted: list[Activity], working: Status,
        bar: Literal['top', 'btm'], lbs: float,
    ) -> Status:
        """Emit a zero-duration `Waste` discarding `lbs` of usable residue
        from `bar`. The discarded yarn is the beam currently on that bar
        (read from `working`). The yarn is removed unknit, so the activity
        occupies no machine time (`start == end`); applying it empties the
        named bar (beam -> None, lbs -> 0) so a paired re-thread can refill
        it."""
        start = working.as_of
        beam = working.beam(bar)
        emitted.append(Waste(start=start, end=start, beam=beam,
                             bar=bar, lbs=lbs))
        return working.apply_activity(emitted[-1])

    def _emit_tape_out(
        self, emitted: list[Activity], working: Status,
        bars: Literal['top', 'btm', 'both'], ctx: _PlanCtx,
    ) -> Status:
        """Emit a `TapeOut` of `bars`, recording the set removed from each
        affected bar **as returned to inventory** (its remaining lbs, available
        from this activity's end). A returned set that is no longer worth
        stocking is recorded on the activity but not returned to stock."""
        duration = (TAPE_OUT_BOTH_DURATION if bars == 'both'
                    else TAPE_OUT_SINGLE_DURATION)
        working = self._wait_for_slot(
            emitted, working, ctx, 'tape_out', 2 if bars == 'both' else 1, duration)
        start = working.as_of
        end = self._workcal.offset_work_hours(start, duration)

        def off(bar: Literal['top', 'btm']) -> 'BeamSet | None':
            beam = working.beam(bar)
            if beam is None:
                return None
            lbs = working.lbs_remaining(bar)
            back = beam.returned(lbs, end)
            if worth_stocking(back):
                ctx.returned.append(back)
            ctx.removed[bar] = beam
            return back

        top_beam = off('top') if bars in ('top', 'both') else None
        btm_beam = off('btm') if bars in ('btm', 'both') else None
        emitted.append(TapeOut(start=start, end=end, bars=bars,
                               top_beam=top_beam, btm_beam=btm_beam))
        return working.apply_activity(emitted[-1])

    def _emit_hanging(
        self, emitted: list[Activity], working: Status,
        bars: Literal['top', 'btm', 'both'], item: 'Greige', ctx: _PlanCtx,
    ) -> Status:
        """Mount a beam set on the named bar(s) — for each, the stock set
        `ctx.pick` chooses for `item`'s beam-set requirement (for continuity
        with the set coming off that bar), or an invented one — loading the
        bar with the set and its lbs and leaving it un-threaded. Pairs with
        a `_emit_threading`."""
        cfg = item.configuration
        start = working.as_of
        duration = planning_mode.handling_hours(
            HANGING_BOTH_DURATION if bars == 'both' else HANGING_SINGLE_DURATION)
        end = self._workcal.offset_work_hours(start, duration)
        # The set each hang replaces: what is (or was, before a tape-out
        # earlier in this preamble) on the bar — `pick` keeps its merge or
        # vendor when stock allows.
        def prev(bar: Literal['top', 'btm']) -> 'BeamSet | None':
            return working.beam(bar) or ctx.removed.get(bar)

        # Queued sets that do not fit the bar's requirement are passed over
        # (dropped from the queue and recorded) before the pick; the hang
        # carries them so applying it drops them from any status too.
        first = len(ctx.passed)
        if bars in ('top', 'both'):
            working = ctx.pass_over(working, 'top', BeamSetDesc(cfg.top_beam), start)
        if bars in ('btm', 'both'):
            working = ctx.pass_over(working, 'btm', BeamSetDesc(cfg.btm_beam), start)
        passed = tuple((p.bar, p.beam_set) for p in ctx.passed[first:])
        top_beam = (ctx.pick(BeamSetDesc(cfg.top_beam), start, 'top', working,
                             prev('top'))
                    if bars in ('top', 'both') else None)
        btm_beam = (ctx.pick(BeamSetDesc(cfg.btm_beam), start, 'btm', working,
                             prev('btm'))
                    if bars in ('btm', 'both') else None)
        emitted.append(Hanging(
            start=start, end=end, bars=bars,
            top_beam=top_beam, btm_beam=btm_beam, passed_over=passed,
        ))
        return working.apply_activity(emitted[-1])

    def _emit_threading(
        self, emitted: list[Activity], working: Status,
        bars: Literal['top', 'btm', 'both'],
    ) -> Status:
        """Route the loaded yarn on the named bar(s) — flips them to
        threaded. The beam/lbs were already loaded by the preceding
        `_emit_hanging`."""
        start = working.as_of
        duration = planning_mode.handling_hours(
            THREADING_BOTH_DURATION if bars == 'both' else THREADING_SINGLE_DURATION)
        end = self._workcal.offset_work_hours(start, duration)
        emitted.append(Threading(start=start, end=end, bars=bars))
        return working.apply_activity(emitted[-1])

    def _emit_unhang(
        self, emitted: list[Activity], working: Status,
        bars: Literal['top', 'btm', 'both'], ctx: _PlanCtx,
    ) -> Status:
        """Emit an `Unhang` of `bars` — a hung, never-threaded set taken off
        again (see "Hung bars" in DESIGN.md): zero duration, no ration slot,
        the set recorded as returned to inventory with all its lbs (not when
        it is no longer worth stocking, or blacklisted)."""
        start = working.as_of

        def off(bar: Literal['top', 'btm']) -> 'BeamSet | None':
            beam = working.beam(bar)
            if beam is None:
                return None
            back = beam.returned(working.lbs_remaining(bar), start)
            if worth_stocking(back):
                ctx.returned.append(back)
            ctx.removed[bar] = beam
            return back

        top_beam = off('top') if bars in ('top', 'both') else None
        btm_beam = off('btm') if bars in ('btm', 'both') else None
        emitted.append(Unhang(start=start, end=start, bars=bars,
                              top_beam=top_beam, btm_beam=btm_beam))
        return working.apply_activity(emitted[-1])

    def _emit_rethread(
        self, emitted: list[Activity], working: Status,
        bars: Literal['top', 'btm', 'both'], item: 'Greige', ctx: _PlanCtx,
    ) -> Status:
        """Re-thread the named bar(s): a `Hanging` (mount the set) then a
        `Threading` (route the yarn). Together these replace the old single
        `BeamLoad`; the bar(s) must already be removed."""
        working = self._emit_hanging(emitted, working, bars, item, ctx)
        return self._emit_threading(emitted, working, bars)

    def _emit_idle(
        self, emitted: list[Activity], working: Status, duration: timedelta,
    ) -> Status:
        start = working.as_of
        end = self._workcal.offset_work_hours(
            start, duration.total_seconds() / 3600,
        )
        emitted.append(Idle(start=start, end=end))
        return working.apply_activity(emitted[-1])

    def _wait_for_slot(
        self, emitted: list[Activity], working: Status, ctx: _PlanCtx,
        kind: str, units: int, duration: float,
    ) -> Status:
        """Place a rationed activity: find the next `kind` slot for `units`
        at or after `working.as_of` (the plan's capacity, if any), spend the
        wait knitting the current item while the plan's fill allows it (a
        whole roll at a time, each started before the slot, the slot looked
        up again after each), emit an `Idle(reason=f'{kind} slot')` for what
        is left of the wait, and record the slot on the context for the plan
        to report. Unrationed (no capacity, or the kind has no limit):
        returns `working` as is."""
        cap = ctx.capacity
        if cap is None or cap.limits(kind) is None:
            return working
        while True:
            slot = cap.next_slot(kind, units, working.as_of, duration)
            if slot <= working.as_of:
                break
            if ctx.fill_left > 0 and self._can_fill_roll(working):
                working = self._emit_fill_roll(emitted, working, ctx)
                continue
            emitted.append(Idle(start=working.as_of, end=slot,
                                reason=f'{kind} slot'))
            working = working.apply_activity(emitted[-1])
            break
        period = cap.period_of(kind, slot)
        ctx.slots.append((kind, period.day, units, slot))
        return working

    def _can_fill_roll(self, working: Status) -> bool:
        """Whether the bars as they stand can finish one more whole roll of
        the current item above the floor (a foreign bar counts 0 lbs; a
        machine with no item cannot fill)."""
        cur = working.current_item
        if cur.id == 'NONE':
            return False
        cfg = cur.configuration
        top_lbs, btm_lbs = self._run_up_lbs(working)
        return _whole_rolls_before_floor(
            top_lbs, cfg.top_pct, btm_lbs, cfg.btm_pct, cur.tgt_wt) >= 1

    def _emit_fill_roll(
        self, emitted: list[Activity], working: Status, ctx: _PlanCtx,
    ) -> Status:
        """Knit and doff one whole roll of the current item against the
        plan's fill, recording it on the context."""
        cur = working.current_item
        working = self._emit_knit(emitted, working, cur, cur.tgt_wt)
        knit = emitted[-1]
        working = self._emit_doff(emitted, working)
        ctx.fill_rolls.append(Roll(lbs=cur.tgt_wt, completion_time=working.as_of,
                                   knits=(knit,)))
        ctx.fill_acts.extend((knit, emitted[-1]))
        ctx.fill_left -= 1
        return working

    def _emit_changeover(
        self, emitted: list[Activity], working: Status, to_item: 'Greige',
        ctx: '_PlanCtx | None' = None,
    ) -> Status:
        """Emit the changeover activity for switching to `to_item`, selected
        from `is_new` and the pattern-family comparison (see "Beam-swap
        decision" in DESIGN.md): `StyleChange` on a new machine, else
        `RunnerChange` within the pattern family or `PatternChange` across
        it. The activity class carries the semantic — there is no
        `is_family_change` flag."""
        from_item = working.current_item
        if self._is_new:
            cls, duration = StyleChange, STYLE_CHANGE_DURATION
        elif from_item.family == to_item.family:
            cls, duration = RunnerChange, RUNNER_CHANGE_DURATION
        else:
            cls, duration = PatternChange, PATTERN_CHANGE_DURATION
            if ctx is not None:
                working = self._wait_for_slot(
                    emitted, working, ctx, 'pattern_change', 1, duration)
        start = working.as_of
        end = self._workcal.offset_work_hours(start, duration)
        emitted.append(cls(
            start=start, end=end, from_item=from_item, to_item=to_item,
        ))
        return working.apply_activity(emitted[-1])


def _whole_rolls_before_floor(
    top_lbs: float, top_pct: float,
    btm_lbs: float, btm_pct: float, tgt_wt: float,
) -> int:
    """Whole rolls of an item with these pcts and `tgt_wt` that the given
    bar lbs can finish before either beam reaches `BEAM_FLOOR_LBS`. Snaps a
    near-integer count to absorb float drift from the usable/pct division,
    then floors; never negative.

    Shared by the run-up and `next_runout` so both stop at exactly the same
    whole-roll boundary. The plant ships only whole rolls, so the runout
    decision point is the end of the last whole roll — not the instant a
    beam first crosses the floor — and the prediction must match the
    activities a `'next_runout'` plan actually emits."""
    usable = min(
        (top_lbs - BEAM_FLOOR_LBS) / top_pct,
        (btm_lbs - BEAM_FLOOR_LBS) / btm_pct,
    )
    n_exact = usable / tgt_wt
    n_rounded = round(n_exact)
    if abs(n_rounded - n_exact) < _ROLL_TOLERANCE:
        n = n_rounded
    else:
        n = math.floor(n_exact)
    return max(0, n)
