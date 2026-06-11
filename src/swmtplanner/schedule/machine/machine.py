#!/usr/bin/env python

import math
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Iterable, Literal, TYPE_CHECKING

from swmtplanner.support import HasID
from swmtplanner.products import BeamSet
from swmtplanner.schedule.activity import (
    Activity, Knit, Waste, Doff, TapeOut, Hanging, Threading,
    StyleChange, RunnerChange, PatternChange, Idle,
    TAPE_OUT_SINGLE_DURATION, TAPE_OUT_BOTH_DURATION,
    HANGING_SINGLE_DURATION, HANGING_BOTH_DURATION,
    THREADING_SINGLE_DURATION, THREADING_BOTH_DURATION,
    DOFF_DURATION,
    STYLE_CHANGE_DURATION, RUNNER_CHANGE_DURATION, PATTERN_CHANGE_DURATION,
    BEAM_FLOOR_LBS, MAX_BEAM_WASTE_LBS,
)
from swmtplanner.schedule.job import Job, Roll
from .status import Status

if TYPE_CHECKING:
    from swmtplanner.support import WorkCal
    from swmtplanner.products import Greige


# Plant convention: fresh-beam yarn quantity depends on yarn denier. Low-
# denier yarn (≤ 45D) holds more lbs per beam; high-denier yarn holds less.
# Lives at module level because the rule is plant-wide rather than per-
# machine, and not a property of `BeamSet` (which stays plant-agnostic).
_LOW_DENIER_FRESH_LBS = 2800.0
_HIGH_DENIER_FRESH_LBS = 1800.0
_LOW_DENIER_THRESHOLD = 45


def fresh_beam_lbs(beam: BeamSet) -> float:
    """How much yarn is on a freshly loaded beam, by denier convention."""
    return (_LOW_DENIER_FRESH_LBS if beam.denier <= _LOW_DENIER_THRESHOLD
            else _HIGH_DENIER_FRESH_LBS)


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
    production-schedule additions for one planning call. Committed
    together via `add_activities(plan.activities)` +
    `add_jobs(plan.jobs)`. A basic data record — no behavior."""
    activities: tuple[Activity, ...]
    jobs: tuple[Job, ...]


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
    ) -> None:
        self._id = id
        self._workcal = workcal
        self._is_new = is_new
        # A machine begins threaded and running the init item on both bars.
        self._initial_status = Status.create(
            as_of=start,
            current_item=init_item,
            is_idle=True,
            top_beam=init_top_beam,
            top_lbs_remaining=init_top_lbs,
            top_threaded=True,
            btm_beam=init_btm_beam,
            btm_lbs_remaining=init_btm_lbs,
            btm_threaded=True,
        )
        self._activities: list[Activity] = []
        self._jobs: list[Job] = []
        self._current_status: Status = self._initial_status

    @property
    def id(self) -> str:
        return self._id

    @property
    def workcal(self) -> 'WorkCal':
        return self._workcal

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
    def initial_status(self) -> Status:
        return self._initial_status

    @property
    def current_status(self) -> Status:
        return self._current_status

    @property
    def activities(self) -> tuple[Activity, ...]:
        return tuple(self._activities)

    @property
    def jobs(self) -> tuple[Job, ...]:
        """The committed production schedule — `Job` records appended via
        `add_jobs`. Parallel to `activities`; `Job`s have no machine-state
        effect (they record the rolls produced, not machine time)."""
        return tuple(self._jobs)

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
        immediately due."""
        s = self._current_status
        cfg = s.current_item.configuration
        item = s.current_item
        n_rolls = _whole_rolls_before_floor(
            s.lbs_remaining('top'), cfg.top_pct,
            s.lbs_remaining('btm'), cfg.btm_pct, item.tgt_wt,
        )
        # Each whole roll costs its knit time plus a Doff; folding in the
        # doffs keeps this equal to the run-up's last Doff.end.
        rate = item.get_rate_on_mchn(self._id)
        per_roll = item.tgt_wt / rate + DOFF_DURATION
        return self._workcal.offset_work_hours(s.as_of, n_rolls * per_roll)

    def producible_lbs_through(
        self, item: 'Greige', end: datetime,
        start: datetime | None = None,
    ) -> float:
        """Returns the lbs of `item` the machine could produce in the
        window `[start, end)`.

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

        rate = item.get_rate_on_mchn(self._id)
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
            idle_for=idle_for,
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
            item, end=week_end, start=effective_start,
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

    # ----- plan_production --------------------------------------------

    def plan_production(
        self,
        item: 'Greige',
        lbs: float,
        start_at: Literal['schedule_tail', 'next_runout'],
        idle_for: timedelta = timedelta(0),
        tgt_order: str | None = None,
    ) -> 'ProductionPlan':
        """Plan production of `lbs` of `item` on this machine. Pure — does
        not mutate state.

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

        emitted: list[Activity] = []
        jobs: list[Job] = []
        working = self._current_status

        # 0. Optional idle gap at the head of the plan.
        if idle_for > timedelta(0):
            working = self._emit_idle(emitted, working, idle_for)

        # 1. Run-up (only in 'next_runout' mode).
        if start_at == 'next_runout':
            working = self._emit_run_up(emitted, working, jobs)

        # 2. Changeover preamble.
        working = self._emit_preamble(emitted, working, item)

        # 3. Production loop for the new item.
        self._emit_production_loop(emitted, working, item, lbs, jobs, tgt_order)
        return ProductionPlan(activities=tuple(emitted), jobs=tuple(jobs))

    # ----- private plan_production helpers -----

    def _emit_run_up(
        self, emitted: list[Activity], working: Status, jobs: list[Job],
    ) -> Status:
        """Produce `working.current_item` toward a beam runout in **whole
        rolls only** — never starting a roll the current beams can't finish
        above `BEAM_FLOOR_LBS`, so the machine is never stranded mid-roll at
        the changeover. Each roll is a `Knit(tgt_wt)` followed by a `Doff`;
        the roll's `completion_time` is that `Doff`'s end. Emits no `Waste`
        and no beam work of its own (each bar keeps its leftover usable yarn
        for the preamble). Appends one run-up `Job` (omitted when no whole
        roll fits) and returns the working status with `current_item`
        unchanged."""
        cur = working.current_item
        cfg = cur.configuration
        # Whole rolls only — the same stopping point next_runout predicts.
        n_rolls = _whole_rolls_before_floor(
            working.lbs_remaining('top'), cfg.top_pct,
            working.lbs_remaining('btm'), cfg.btm_pct, cur.tgt_wt,
        )
        if n_rolls <= 0:
            return working

        rolls: list[Roll] = []
        for _ in range(n_rolls):
            working = self._emit_knit(emitted, working, cur, cur.tgt_wt)
            knit = emitted[-1]                # the Knit just emitted
            working = self._emit_doff(emitted, working)
            rolls.append(Roll(lbs=cur.tgt_wt, completion_time=working.as_of,
                              knits=(knit,)))
        jobs.append(Job(item=cur, rolls=tuple(rolls)))
        return working

    def _emit_preamble(
        self, emitted: list[Activity], working: Status, item: 'Greige',
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
            (mismatch worth preserving), or 'waste' (mismatch to discard)."""
            usable = working.lbs_remaining(bar) - BEAM_FLOOR_LBS
            if usable <= _FLOAT_EPS:
                return 'load'
            beam = working.beam(bar)
            if beam is not None and beam.id == want_beam:
                return 'keep'
            return 'tape' if usable > MAX_BEAM_WASTE_LBS else 'waste'

        top_action = bar_action('top', cfg.top_beam)
        btm_action = bar_action('btm', cfg.btm_beam)

        # Tape-out phase — batch into one 'both' when both bars tape out.
        if top_action == 'tape' and btm_action == 'tape':
            working = self._emit_tape_out(emitted, working, 'both')
        elif top_action == 'tape':
            working = self._emit_tape_out(emitted, working, 'top')
        elif btm_action == 'tape':
            working = self._emit_tape_out(emitted, working, 'btm')

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
        # (Hanging + Threading). Batch into 'both' when both are re-threaded.
        rethread_top = top_action != 'keep'
        rethread_btm = btm_action != 'keep'
        if rethread_top and rethread_btm:
            working = self._emit_rethread(emitted, working, 'both', item)
        elif rethread_top:
            working = self._emit_rethread(emitted, working, 'top', item)
        elif rethread_btm:
            working = self._emit_rethread(emitted, working, 'btm', item)

        # Changeover phase — the right changeover type when the item changes.
        if item != working.current_item:
            working = self._emit_changeover(emitted, working, item)
        return working

    def _emit_production_loop(
        self, emitted: list[Activity], working: Status,
        item: 'Greige', lbs: float, jobs: list[Job],
        tgt_order: str | None = None,
    ) -> None:
        """Wind `lbs` of `item` (a whole multiple of `tgt_wt`) one roll at a
        time, recording each completed `Roll` on one straddle-aware `Job`.
        Every roll ends in a `Doff`, so its `completion_time` is the `Doff`'s
        end; a `Knit` is one uninterrupted run that ends at a doff or a beam
        swap, so `0 < Knit.lbs <= tgt_wt`. A roll that hits a beam floor
        mid-wind continues on the fresh beam (a `Hanging` + `Threading`), so
        it can span two `Knit`s. See the production-loop walk in DESIGN.md."""
        cfg = item.configuration
        tgt = item.tgt_wt
        rolls: list[Roll] = []

        rolls_left = round(lbs / tgt)   # whole rolls owed (lbs is a multiple)
        roll_filled = 0.0               # lbs wound on the in-progress roll
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
            working = self._emit_rethread(emitted, working, bars, item)

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

        if rolls:
            jobs.append(Job(item=item, rolls=tuple(rolls), tgt_order=tgt_order))

    # ----- single-activity emission helpers -----

    def _emit_knit(
        self, emitted: list[Activity], working: Status,
        item: 'Greige', lbs: float,
    ) -> Status:
        """Emit one `Knit` activity for `lbs` of `item` — one uninterrupted
        run (it ends at a doff or a beam swap). Roll tracking is the caller's
        job: the run-up and production loop record each `Roll` after its
        `Doff`. See DESIGN.md."""
        rate = item.get_rate_on_mchn(self._id)
        start = working.as_of
        end = self._workcal.offset_work_hours(start, lbs / rate)
        emitted.append(Knit(start=start, end=end, item=item, lbs=lbs))
        return working.apply_activity(emitted[-1])

    def _emit_doff(
        self, emitted: list[Activity], working: Status,
    ) -> Status:
        """Emit a `Doff` taking one just-completed roll off the machine. The
        roll's `completion_time` is this `Doff`'s end (the returned status's
        `as_of`)."""
        start = working.as_of
        end = self._workcal.offset_work_hours(start, DOFF_DURATION)
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
        bars: Literal['top', 'btm', 'both'],
    ) -> Status:
        """Emit a `TapeOut` of `bars`, recording the beam SKU(s) removed from
        each affected bar (read from `working`) for inventory tracking."""
        duration = (TAPE_OUT_BOTH_DURATION if bars == 'both'
                    else TAPE_OUT_SINGLE_DURATION)
        start = working.as_of
        end = self._workcal.offset_work_hours(start, duration)
        top_beam = working.beam('top') if bars in ('top', 'both') else None
        btm_beam = working.beam('btm') if bars in ('btm', 'both') else None
        emitted.append(TapeOut(start=start, end=end, bars=bars,
                               top_beam=top_beam, btm_beam=btm_beam))
        return working.apply_activity(emitted[-1])

    def _emit_hanging(
        self, emitted: list[Activity], working: Status,
        bars: Literal['top', 'btm', 'both'], item: 'Greige',
    ) -> Status:
        """Mount a fresh beam set on the named bar(s), loading each bar's beam
        (from `item`'s yarn) and lbs (`fresh_beam_lbs`) and leaving it
        un-threaded. Pairs with a `_emit_threading`."""
        cfg = item.configuration
        start = working.as_of
        duration = (HANGING_BOTH_DURATION if bars == 'both'
                    else HANGING_SINGLE_DURATION)
        end = self._workcal.offset_work_hours(start, duration)
        top_beam = BeamSet(cfg.top_beam) if bars in ('top', 'both') else None
        btm_beam = BeamSet(cfg.btm_beam) if bars in ('btm', 'both') else None
        top_lbs = fresh_beam_lbs(top_beam) if top_beam is not None else 0.0
        btm_lbs = fresh_beam_lbs(btm_beam) if btm_beam is not None else 0.0
        emitted.append(Hanging(
            start=start, end=end, bars=bars,
            top_beam=top_beam, top_lbs=top_lbs,
            btm_beam=btm_beam, btm_lbs=btm_lbs,
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
        duration = (THREADING_BOTH_DURATION if bars == 'both'
                    else THREADING_SINGLE_DURATION)
        end = self._workcal.offset_work_hours(start, duration)
        emitted.append(Threading(start=start, end=end, bars=bars))
        return working.apply_activity(emitted[-1])

    def _emit_rethread(
        self, emitted: list[Activity], working: Status,
        bars: Literal['top', 'btm', 'both'], item: 'Greige',
    ) -> Status:
        """Re-thread the named bar(s): a `Hanging` (mount the fresh set) then
        a `Threading` (route the yarn). Together these replace the old single
        `BeamLoad`; the bar(s) must already be removed."""
        working = self._emit_hanging(emitted, working, bars, item)
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

    def _emit_changeover(
        self, emitted: list[Activity], working: Status, to_item: 'Greige',
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
