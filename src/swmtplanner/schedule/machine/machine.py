#!/usr/bin/env python

import math
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Iterable, Literal, TYPE_CHECKING

from swmtplanner.support import HasID
from swmtplanner.products import BeamSet
from swmtplanner.schedule.activity import (
    Activity, Knit, Waste, TapeOut, BeamLoad, StyleChange, Idle,
    BEAM_LOAD_DURATION, TAPE_OUT_SINGLE_DURATION, TAPE_OUT_BOTH_DURATION,
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
    changeover preamble (tape-outs, beam loads, style change as needed),
    optional run-up of the current item, and the new item's production
    loop with mid-stream reloads when beams exhaust mid-request."""

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
        simple_change_duration: timedelta,
        family_change_duration: timedelta,
        is_new: bool = False,
    ) -> None:
        self._id = id
        self._workcal = workcal
        self._simple_change_duration = simple_change_duration
        self._family_change_duration = family_change_duration
        self._is_new = is_new
        self._initial_status = Status(
            as_of=start,
            top_beam=init_top_beam,
            btm_beam=init_btm_beam,
            top_lbs_remaining=init_top_lbs,
            btm_lbs_remaining=init_btm_lbs,
            current_item=init_item,
            is_idle=True,
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
        """True for modern/digital machines, where family changes and
        in-family style changes are equally cheap (a brief reconfigure)
        rather than the heavier pattern-wheel rework required on older
        machines. New machines emit every style transition as
        `StyleChange(is_family_change=False)` — see "Style changes" in
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
        """Forward-extrapolated time at which top or btm beam will exhaust,
        assuming `current_status.current_item` continues running from
        `current_status.as_of`. Real greiges always draw from both bars
        (top_pct, btm_pct > 0), so this is always well-defined."""
        s = self._current_status
        cfg = s.current_item.configuration
        producible_before_runout = min(
            s.top_lbs_remaining / cfg.top_pct,
            s.btm_lbs_remaining / cfg.btm_pct,
        )
        rate = s.current_item.get_rate_on_mchn(self._id)
        hours = producible_before_runout / rate
        return self._workcal.offset_work_hours(s.as_of, hours)

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
        # [effective_start, end). Activities other than Knit (TapeOut,
        # BeamLoad, StyleChange, Waste, Idle) consume time but produce
        # nothing; their effect on production capacity is already
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
    ) -> 'ProductionPlan':
        """Plan production of `lbs` of `item` on this machine. Pure — does
        not mutate state.

        `idle_for` schedules an explicit `Idle` activity as the **first**
        emitted activity, used to model staff-constrained gaps where the
        machine sits unstaffed during what would otherwise be work hours.
        The entire downstream plan (run-up, preamble, production) needs an
        operator, so Idle precedes everything else.

        Walk (see DESIGN.md for details):
          0. Optional `Idle` (when `idle_for > 0`).
          1. Run-up — `'next_runout'` mode emits Knits (and a possible
             Waste) of the current item until a beam exhausts;
             `'schedule_tail'` mode emits nothing here.
          2. Changeover preamble — per-bar `TapeOut`/`BeamLoad` for any
             bar whose yarn doesn't match the new item, `BeamLoad` only
             for any empty bar, then `StyleChange` if the item differs.
          3. Production loop — Knits/Waste/BeamLoad cycles until `lbs` are
             complete.

        Returns a `ProductionPlan` carrying both the emitted activities
        and the production-schedule `Job` records: one `Job` for the new
        item, plus a run-up `Job` for the current item in `'next_runout'`
        mode (omitted when the run-up yields no whole rolls). Each
        `Job`'s rolls accumulate across any mid-run `BeamLoad`s, so a
        single `Job` can straddle a beam swap."""
        if start_at not in ('schedule_tail', 'next_runout'):
            raise ValueError(
                f"start_at must be 'schedule_tail' or 'next_runout', "
                f'got {start_at!r}'
            )
        if idle_for < timedelta(0):
            raise ValueError(f'idle_for must be non-negative, got {idle_for}')

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
        self._emit_production_loop(emitted, working, item, lbs, jobs)
        return ProductionPlan(activities=tuple(emitted), jobs=tuple(jobs))

    # ----- private plan_production helpers -----

    def _emit_run_up(
        self, emitted: list[Activity], working: Status, jobs: list[Job],
    ) -> Status:
        """Produce `working.current_item` until a beam exhausts. Emits a
        `Knit` for whole rolls plus any half-roll-or-larger partial, and a
        `Waste` for any sub-half-roll partial — see `_split_roll` for the
        rule. Appends one run-up `Job` of the produced rolls to `jobs`
        (omitted when the run-up yields no whole rolls). Returns the
        working status after the run-up (at least one beam at 0 lbs)."""
        cur = working.current_item
        cfg = cur.configuration
        producible = min(
            working.top_lbs_remaining / cfg.top_pct,
            working.btm_lbs_remaining / cfg.btm_pct,
        )
        job_lbs, waste_lbs = _split_roll(producible, cur.tgt_wt)

        rolls: list[Roll] = []
        if job_lbs > 0:
            working = self._emit_knit(emitted, working, cur, job_lbs, rolls)
        if waste_lbs > 0:
            working = self._emit_waste(emitted, working, cur, waste_lbs)
        if rolls:
            jobs.append(Job(item=cur, rolls=tuple(rolls)))
        return _clamp_zero_lbs(working)

    def _emit_preamble(
        self, emitted: list[Activity], working: Status, item: 'Greige',
    ) -> Status:
        """Full changeover preamble. Per-bar logic:

        - Has yarn matching `item`: no activity for that bar.
        - Has yarn not matching `item`: `TapeOut` + `BeamLoad`.
        - Empty (post-runout): `BeamLoad` only — no `TapeOut`.

        When both bars have yarn AND both need swapping, emit a single
        `TapeOut('both')` instead of two singles (cheaper than two singles
        per the design's duration table).

        After all beam work, emit `StyleChange` if `item != current_item`,
        with `is_family_change` set from the family comparison."""
        cfg = item.configuration

        top_empty = working.top_lbs_remaining <= _FLOAT_EPS
        btm_empty = working.btm_lbs_remaining <= _FLOAT_EPS

        top_yarn_matches = (
            not top_empty
            and working.top_beam is not None
            and working.top_beam.id == cfg.top_beam
        )
        btm_yarn_matches = (
            not btm_empty
            and working.btm_beam is not None
            and working.btm_beam.id == cfg.btm_beam
        )

        top_needs_tape_out = (not top_empty) and (not top_yarn_matches)
        btm_needs_tape_out = (not btm_empty) and (not btm_yarn_matches)
        top_needs_load = top_empty or not top_yarn_matches
        btm_needs_load = btm_empty or not btm_yarn_matches

        # Tape-out phase. 'both' is reserved for the case where both bars
        # still carry (mismatched) yarn — it cannot arise in 'next_runout'
        # mode where at least one bar is empty after the run-up.
        if top_needs_tape_out and btm_needs_tape_out:
            working = self._emit_tape_out(emitted, working, 'both')
        elif top_needs_tape_out:
            working = self._emit_tape_out(emitted, working, 'top')
        elif btm_needs_tape_out:
            working = self._emit_tape_out(emitted, working, 'btm')

        # Beam-load phase. Top first, then btm.
        if top_needs_load:
            working = self._emit_beam_load(
                emitted, working, 'top', BeamSet(cfg.top_beam),
            )
        if btm_needs_load:
            working = self._emit_beam_load(
                emitted, working, 'btm', BeamSet(cfg.btm_beam),
            )

        # Style-change phase. On new machines a family-spanning
        # transition takes the same time as an in-family one, so we
        # collapse both to `is_family_change=False` — the StyleChange
        # weight then doesn't double-charge transitions that aren't
        # actually more expensive on the hardware in question.
        if item != working.current_item:
            is_family_change = (
                (not self._is_new)
                and working.current_item.family != item.family
            )
            working = self._emit_style_change(
                emitted, working, item, is_family_change=is_family_change,
            )
        return working

    def _emit_production_loop(
        self, emitted: list[Activity], working: Status,
        item: 'Greige', lbs: float, jobs: list[Job],
    ) -> None:
        """Emit Knits (and Wastes / BeamLoads) until `lbs` of `item` are
        produced, then append one `Job` of the accumulated rolls to
        `jobs`. The rolls accumulate across every mid-run `BeamLoad`, so
        the single emitted `Job` straddles any beam swaps. The BeamLoads
        emitted here use the same yarn as `item` (the preamble already
        guaranteed that)."""
        cfg = item.configuration
        remaining = lbs
        rolls: list[Roll] = []

        while remaining > _FLOAT_EPS:
            top_capacity = working.top_lbs_remaining / cfg.top_pct
            btm_capacity = working.btm_lbs_remaining / cfg.btm_pct
            producible = min(top_capacity, btm_capacity)

            # All remaining fits in this beam state — final Knit, done.
            if producible >= remaining - _FLOAT_EPS:
                working = self._emit_knit(
                    emitted, working, item, remaining, rolls,
                )
                break

            # Producible < remaining — produce up to runout, then reload.
            # The `_split_roll` partition applies the half-roll rule:
            # the partial counts as a smaller-than-target usable roll
            # (Knit) when at or above `tgt_wt / 2`, else as Waste.
            job_lbs, waste_lbs = _split_roll(producible, item.tgt_wt)
            if job_lbs > 0:
                working = self._emit_knit(
                    emitted, working, item, job_lbs, rolls,
                )
                remaining -= job_lbs
            if waste_lbs > 0:
                working = self._emit_waste(emitted, working, item, waste_lbs)

            working = _clamp_zero_lbs(working)

            # Reload whichever bar(s) exhausted. Natural exhaustion: no
            # TapeOut needed (the bar is already empty).
            if working.top_lbs_remaining == 0.0:
                working = self._emit_beam_load(
                    emitted, working, 'top', BeamSet(cfg.top_beam),
                )
            if working.btm_lbs_remaining == 0.0:
                working = self._emit_beam_load(
                    emitted, working, 'btm', BeamSet(cfg.btm_beam),
                )

        if rolls:
            jobs.append(Job(item=item, rolls=tuple(rolls)))

    # ----- single-activity emission helpers -----

    def _emit_knit(
        self, emitted: list[Activity], working: Status,
        item: 'Greige', lbs: float, rolls: list[Roll],
    ) -> Status:
        """Emit one `Knit` activity for `lbs` of `item` and append the
        rolls it completes to `rolls`. A `Knit` is one uninterrupted run;
        whether it ends a `Job` is the caller's concern (the run-up and
        production-loop helpers own the `rolls` list and package it into a
        `Job`), so this only contributes rolls."""
        rate = item.get_rate_on_mchn(self._id)
        start = working.as_of
        end = self._workcal.offset_work_hours(start, lbs / rate)
        emitted.append(Knit(start=start, end=end, item=item, lbs=lbs))
        rolls.extend(
            _compute_rolls(start, lbs, rate, item.tgt_wt, self._workcal)
        )
        return working.apply_activity(emitted[-1])

    def _emit_waste(
        self, emitted: list[Activity], working: Status,
        item: 'Greige', lbs: float,
    ) -> Status:
        rate = item.get_rate_on_mchn(self._id)
        start = working.as_of
        end = self._workcal.offset_work_hours(start, lbs / rate)
        emitted.append(Waste(start=start, end=end, item=item, lbs=lbs))
        return working.apply_activity(emitted[-1])

    def _emit_tape_out(
        self, emitted: list[Activity], working: Status,
        bars: Literal['top', 'btm', 'both'],
    ) -> Status:
        duration = (TAPE_OUT_BOTH_DURATION if bars == 'both'
                    else TAPE_OUT_SINGLE_DURATION)
        start = working.as_of
        end = self._workcal.offset_work_hours(
            start, duration.total_seconds() / 3600,
        )
        emitted.append(TapeOut(start=start, end=end, bars=bars))
        return working.apply_activity(emitted[-1])

    def _emit_beam_load(
        self, emitted: list[Activity], working: Status,
        bar: Literal['top', 'btm'], beam: BeamSet,
    ) -> Status:
        start = working.as_of
        end = self._workcal.offset_work_hours(
            start, BEAM_LOAD_DURATION.total_seconds() / 3600,
        )
        lbs = fresh_beam_lbs(beam)
        emitted.append(BeamLoad(start=start, end=end, bar=bar,
                                beam=beam, lbs=lbs))
        return working.apply_activity(emitted[-1])

    def _emit_idle(
        self, emitted: list[Activity], working: Status, duration: timedelta,
    ) -> Status:
        start = working.as_of
        end = self._workcal.offset_work_hours(
            start, duration.total_seconds() / 3600,
        )
        emitted.append(Idle(start=start, end=end))
        return working.apply_activity(emitted[-1])

    def _emit_style_change(
        self, emitted: list[Activity], working: Status,
        to_item: 'Greige', is_family_change: bool,
    ) -> Status:
        duration = (self._family_change_duration if is_family_change
                    else self._simple_change_duration)
        start = working.as_of
        end = self._workcal.offset_work_hours(
            start, duration.total_seconds() / 3600,
        )
        emitted.append(StyleChange(
            start=start, end=end,
            from_item=working.current_item, to_item=to_item,
            is_family_change=is_family_change,
        ))
        return working.apply_activity(emitted[-1])


def _split_roll(producible: float, tgt_wt: float) -> tuple[float, float]:
    """Decide how a beam-runout's `producible` lbs of yarn should be
    split between a `Job` and a `Waste` under the half-roll rule.

    The plant ships only whole rolls (~`tgt_wt` lbs each) or half rolls
    (~`tgt_wt / 2` lbs each), with each roll's weight within
    `_ROLL_TOLERANCE * tgt_wt` lbs of its target. Yarn that doesn't fit
    those two discrete sizes is waste.

    Returns `(job_lbs, waste_lbs)`:

    - `job_lbs` is the lbs to emit as a `Job` — N whole rolls of
      `tgt_wt` each, optionally followed by one half-roll of
      `tgt_wt / 2`. For example, `producible=500` with `tgt_wt=700`
      yields one 350-lb half-roll, so `job_lbs = 350`.
    - `waste_lbs` is yarn that doesn't fit in a full or half roll:
      either yarn beyond `tgt_wt / 2` past the last whole roll, or
      yarn below the half-roll tolerance band. For the same example,
      `waste_lbs = 500 - 350 = 150`.

    Float-drift handling: a `producible` within tolerance of either
    `N * tgt_wt` or `N * tgt_wt + tgt_wt / 2` snaps to that target —
    the actual `producible` lbs is preserved in `job_lbs` so mass
    conservation holds (`job_lbs + waste_lbs == producible` always)."""
    half = tgt_wt / 2
    tol_lbs = _ROLL_TOLERANCE * tgt_wt

    n_full = int(producible / tgt_wt)
    remainder = producible - n_full * tgt_wt

    # Remainder close to `tgt_wt` (snap up: treat as N+1 near-full
    # rolls collectively weighing exactly `producible` lbs).
    if tgt_wt - remainder < tol_lbs:
        return producible, 0.0

    # Remainder close to 0 (clean N-whole-roll count + drift). The
    # drift goes to Waste so mass conservation holds and the runout's
    # constraint bar still gets consumed to zero downstream.
    if remainder < tol_lbs:
        return n_full * tgt_wt, remainder

    # Remainder close to `tgt_wt / 2` (half-roll within tolerance).
    if abs(remainder - half) < tol_lbs:
        return producible, 0.0

    # Remainder above the half-roll target: take exactly `tgt_wt / 2`
    # as a half-roll, discard the rest as Waste.
    if remainder > half:
        return n_full * tgt_wt + half, remainder - half

    # Remainder below the half-roll target (minus tolerance): too
    # small for a half-roll, all Waste.
    return n_full * tgt_wt, remainder


def _compute_rolls(
    start: datetime, lbs: float, rate: float, tgt_wt: float,
    workcal: 'WorkCal',
) -> tuple[Roll, ...]:
    """Break a `Knit`'s `lbs` into a sequence of `Roll`s. Each `Roll` is
    either a whole roll (`tgt_wt` lbs, within tolerance) or a half-roll
    (`tgt_wt / 2`, within tolerance). The per-roll lbs sum to exactly
    `lbs` (mass conservation); when the total snaps to a clean N-roll
    count under `_ROLL_TOLERANCE`, the lbs are distributed evenly across
    the N rolls. Completion times respect `workcal`.

    Inputs are expected to come from `_emit_knit`, where `lbs` is already
    shaped by `_split_roll`'s half-roll rule — so a non-snap `lbs` either
    has a clean half-roll partial (`tgt_wt / 2` ± tolerance) or is a
    single sub-tgt_wt final-leg residual."""
    rolls: list[Roll] = []
    cumulative = 0.0

    # Snap to clean N-roll count if close. Distribute lbs equally
    # across the N rolls so the sum exactly matches `lbs` (vs. emitting
    # N rolls of `tgt_wt` each which would over- or under-count by the
    # snap delta).
    n_rolls_exact = lbs / tgt_wt
    n_rolls_rounded = round(n_rolls_exact)
    if abs(n_rolls_rounded - n_rolls_exact) < _ROLL_TOLERANCE:
        if n_rolls_rounded == 0:
            return ()
        roll_lbs = lbs / n_rolls_rounded
        for _ in range(n_rolls_rounded):
            cumulative += roll_lbs
            rolls.append(Roll(
                lbs=roll_lbs,
                completion_time=workcal.offset_work_hours(
                    start, cumulative / rate,
                ),
            ))
        return tuple(rolls)

    # Non-snap: `floor(lbs / tgt_wt)` whole rolls plus one partial.
    # The partial is normally a half-roll (~`tgt_wt / 2`) produced by
    # `_split_roll`'s half-roll fold, but can be a sub-tgt_wt residual
    # in the production loop's final-leg case.
    n_full = int(n_rolls_exact)
    for _ in range(n_full):
        cumulative += tgt_wt
        rolls.append(Roll(
            lbs=tgt_wt,
            completion_time=workcal.offset_work_hours(
                start, cumulative / rate,
            ),
        ))
    residual = lbs - cumulative
    if residual > _FLOAT_EPS:
        cumulative += residual
        rolls.append(Roll(
            lbs=residual,
            completion_time=workcal.offset_work_hours(
                start, cumulative / rate,
            ),
        ))
    return tuple(rolls)


def _clamp_zero_lbs(working: Status) -> Status:
    """Round bars within `_FLOAT_EPS` of zero down to exactly zero. Lets
    downstream code check `lbs_remaining == 0.0` rather than threading an
    epsilon through every comparison."""
    top = 0.0 if working.top_lbs_remaining <= _FLOAT_EPS else working.top_lbs_remaining
    btm = 0.0 if working.btm_lbs_remaining <= _FLOAT_EPS else working.btm_lbs_remaining
    if top == working.top_lbs_remaining and btm == working.btm_lbs_remaining:
        return working
    return replace(working, top_lbs_remaining=top, btm_lbs_remaining=btm)
