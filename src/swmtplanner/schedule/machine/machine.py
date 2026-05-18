#!/usr/bin/env python

import math
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Iterable, Literal, TYPE_CHECKING

from swmtplanner.support import HasID
from swmtplanner.products import BeamSet
from swmtplanner.schedule.activity import (
    Activity, Job, Waste, TapeOut, BeamLoad, StyleChange, Idle,
    BEAM_LOAD_DURATION, TAPE_OUT_SINGLE_DURATION, TAPE_OUT_BOTH_DURATION,
)
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


class Machine(HasID[str]):
    """Single knitting machine. Owns an append-only sequence of activities
    and the derived `Status` after each. `plan_production` produces a list
    of activities to enact a desired production goal — handling the
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
    def next_job_end(self) -> datetime:
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

    def producible_lbs_in_week(
        self, item: 'Greige', year: int, week: int,
        start: datetime | None = None,
    ) -> float:
        """Returns the lbs of `item` the machine could produce within the
        given ISO week (Monday 00:00 to next Monday 00:00).

        `start` is the earliest moment at which production may begin.
        Defaults to `current_status.as_of`. Passing a later datetime (e.g.
        `next_runout`) lets the caller ask "if I delay production until
        this time, how much fits?". `start` may not be earlier than
        `current_status.as_of` (the machine can't time-travel) — raises
        `ValueError` if so.

        Accounts for required changeover preamble, mid-stream beam reloads,
        non-work hours via `workcal`, and rounds the result down to a whole
        multiple of `item.tgt_wt`. Returns 0.0 if the effective start is
        already past `week_end`, if the preamble alone exceeds the window,
        or if the remaining time can't accommodate a full roll.

        Pure: does not mutate any machine state. Implementation re-uses
        `plan_production` by asking for a generous upper bound and tallying
        the lbs of `Job` activities whose execution falls within the
        [week_start, week_end] window."""
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
        if effective_start >= week_end:
            return 0.0

        rate = item.get_rate_on_mchn(self._id)
        # Upper bound on plan_production's lbs argument: max producible if
        # the entire 168 wall-clock hours of the week were work hours at
        # full rate, plus one roll of headroom. plan_production will simply
        # produce more activities than we need; we truncate via the window
        # check below.
        upper_lbs_bound = (
            math.ceil(7 * 24 * rate / item.tgt_wt) * item.tgt_wt
            + item.tgt_wt
        )

        # Bridge: idle from the machine's actual schedule tail (as_of) to
        # the production-begin moment, which is the later of
        # `effective_start` and `week_start`. The bridge is measured in
        # **work hours** so a non-work gap (weekend under a weekday
        # workcal) collapses to zero and `plan_production` picks up at
        # the next work moment naturally.
        bridge_target = max(effective_start, week_start)
        bridge_hours = self._workcal.get_work_hours_between(
            as_of, bridge_target,
        )
        idle_for = timedelta(hours=bridge_hours)
        plan = self.plan_production(
            item, upper_lbs_bound, start_at='next_job_end',
            idle_for=idle_for,
        )

        # Tally lbs of `Job`s for `item` that overlap [week_start, week_end].
        # Activities other than Job (TapeOut, BeamLoad, StyleChange, Waste,
        # Idle) consume time but produce nothing; their effect on production
        # capacity is already reflected in subsequent Jobs' start times.
        total_lbs = 0.0
        for a in plan:
            if a.start >= week_end:
                break
            if not isinstance(a, Job):
                continue
            if a.item != item:
                continue
            if a.end <= week_start:
                continue
            window_start = max(a.start, week_start)
            window_end = min(a.end, week_end)
            hours_in_window = self._workcal.get_work_hours_between(
                window_start, window_end,
            )
            total_lbs += hours_in_window * rate

        # Round down to whole rolls, snapping near-integer rolls (float
        # drift from `min(top_lbs/top_pct, btm_lbs/btm_pct) * rate` chains).
        n_rolls_exact = total_lbs / item.tgt_wt
        n_rolls_rounded = round(n_rolls_exact)
        if abs(n_rolls_rounded - n_rolls_exact) < _FLOAT_EPS:
            n_rolls = n_rolls_rounded
        else:
            n_rolls = math.floor(n_rolls_exact)
        return max(0, n_rolls) * item.tgt_wt

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

    # ----- plan_production --------------------------------------------

    def plan_production(
        self,
        item: 'Greige',
        lbs: float,
        start_at: Literal['next_job_end', 'next_runout'],
        idle_for: timedelta = timedelta(0),
    ) -> list[Activity]:
        """Plan production of `lbs` of `item` on this machine. Pure — does
        not mutate state.

        `idle_for` schedules an explicit `Idle` activity as the **first**
        emitted activity, used to model staff-constrained gaps where the
        machine sits unstaffed during what would otherwise be work hours.
        The entire downstream plan (run-up, preamble, production) needs an
        operator, so Idle precedes everything else.

        Walk (see DESIGN.md for details):
          0. Optional `Idle` (when `idle_for > 0`).
          1. Run-up — `'next_runout'` mode emits Jobs (and a possible
             Waste) of the current item until a beam exhausts;
             `'next_job_end'` mode emits nothing here.
          2. Changeover preamble — per-bar `TapeOut`/`BeamLoad` for any
             bar whose yarn doesn't match the new item, `BeamLoad` only
             for any empty bar, then `StyleChange` if the item differs.
          3. Production loop — Jobs/Waste/BeamLoad cycles until `lbs` are
             complete."""
        if start_at not in ('next_job_end', 'next_runout'):
            raise ValueError(
                f"start_at must be 'next_job_end' or 'next_runout', "
                f'got {start_at!r}'
            )
        if idle_for < timedelta(0):
            raise ValueError(f'idle_for must be non-negative, got {idle_for}')

        emitted: list[Activity] = []
        working = self._current_status

        # 0. Optional idle gap at the head of the plan.
        if idle_for > timedelta(0):
            working = self._emit_idle(emitted, working, idle_for)

        # 1. Run-up (only in 'next_runout' mode).
        if start_at == 'next_runout':
            working = self._emit_run_up(emitted, working)

        # 2. Changeover preamble.
        working = self._emit_preamble(emitted, working, item)

        # 3. Production loop for the new item.
        self._emit_production_loop(emitted, working, item, lbs)
        return emitted

    # ----- private plan_production helpers -----

    def _emit_run_up(self, emitted: list[Activity], working: Status) -> Status:
        """Produce `working.current_item` until a beam exhausts. Emits
        complete-roll `Job`(s) and a `Waste` for any partial. Returns the
        working status after the run-up (at least one beam at 0 lbs)."""
        cur = working.current_item
        cfg = cur.configuration
        producible = min(
            working.top_lbs_remaining / cfg.top_pct,
            working.btm_lbs_remaining / cfg.btm_pct,
        )
        complete_rolls_lbs, partial_lbs = _split_roll(producible, cur.tgt_wt)

        if complete_rolls_lbs > 0:
            working = self._emit_job(emitted, working, cur, complete_rolls_lbs)
        if partial_lbs > 0:
            working = self._emit_waste(emitted, working, cur, partial_lbs)
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
        item: 'Greige', lbs: float,
    ) -> None:
        """Emit Jobs (and Wastes / BeamLoads) until `lbs` of `item` are
        produced. In Phase 2 the BeamLoads emitted here use the same yarn
        as `item` (since the preamble already guaranteed that)."""
        cfg = item.configuration
        remaining = lbs

        while remaining > _FLOAT_EPS:
            top_capacity = working.top_lbs_remaining / cfg.top_pct
            btm_capacity = working.btm_lbs_remaining / cfg.btm_pct
            producible = min(top_capacity, btm_capacity)

            # All remaining fits in this beam state — single Job and done.
            if producible >= remaining - _FLOAT_EPS:
                working = self._emit_job(emitted, working, item, remaining)
                return

            # Producible < remaining — produce up to runout, then reload.
            complete_rolls_lbs, partial_lbs = _split_roll(producible, item.tgt_wt)
            if complete_rolls_lbs > 0:
                working = self._emit_job(emitted, working, item, complete_rolls_lbs)
                remaining -= complete_rolls_lbs
            if partial_lbs > 0:
                working = self._emit_waste(emitted, working, item, partial_lbs)

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

    # ----- single-activity emission helpers -----

    def _emit_job(
        self, emitted: list[Activity], working: Status,
        item: 'Greige', lbs: float,
    ) -> Status:
        rate = item.get_rate_on_mchn(self._id)
        start = working.as_of
        end = self._workcal.offset_work_hours(start, lbs / rate)
        emitted.append(Job(start=start, end=end, item=item, lbs=lbs))
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
    """Split `producible` lbs into (complete_rolls_lbs, partial_lbs). Snaps
    to nearest multiple of `tgt_wt` within `_FLOAT_EPS` to avoid spurious
    partials from float division drift (e.g., 200/0.4 == 499.99…)."""
    n_rolls_exact = producible / tgt_wt
    n_rolls_rounded = round(n_rolls_exact)
    if abs(n_rolls_rounded - n_rolls_exact) < _FLOAT_EPS:
        return n_rolls_rounded * tgt_wt, 0.0
    n_rolls_floor = int(n_rolls_exact)
    complete = n_rolls_floor * tgt_wt
    return complete, producible - complete


def _clamp_zero_lbs(working: Status) -> Status:
    """Round bars within `_FLOAT_EPS` of zero down to exactly zero. Lets
    downstream code check `lbs_remaining == 0.0` rather than threading an
    epsilon through every comparison."""
    top = 0.0 if working.top_lbs_remaining <= _FLOAT_EPS else working.top_lbs_remaining
    btm = 0.0 if working.btm_lbs_remaining <= _FLOAT_EPS else working.btm_lbs_remaining
    if top == working.top_lbs_remaining and btm == working.btm_lbs_remaining:
        return working
    return replace(working, top_lbs_remaining=top, btm_lbs_remaining=btm)
