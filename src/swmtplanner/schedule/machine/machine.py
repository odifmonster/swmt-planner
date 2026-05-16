#!/usr/bin/env python

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Iterable, Literal, TYPE_CHECKING

from swmtplanner.support import HasID
from swmtplanner.products import BeamSet
from swmtplanner.schedule.activity import (
    Activity, Job, Waste, BeamLoad, StyleChange, Idle,
    BEAM_LOAD_DURATION,
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
_FLOAT_EPS = 1e-2


class Machine(HasID[str]):
    """Single knitting machine. Owns an append-only sequence of activities
    and the derived `Status` after each. Plan-time queries
    (`plan_production`) currently only support same-yarn / same-family
    transitions; Phase 3 will lift that restriction."""

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
    ) -> None:
        self._id = id
        self._workcal = workcal
        self._simple_change_duration = simple_change_duration
        self._family_change_duration = family_change_duration
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

    # ----- plan_production (Phase 2: same yarn + same family only) -----

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

        Phase 2 restriction: `item` must share top yarn id, btm yarn id,
        and family with the current item. Yarn/family-changing transitions
        raise `NotImplementedError` until Phase 3.

        See DESIGN.md for the full walk; this implementation follows the
        Phase 2 subset (no `TapeOut` / cross-yarn `BeamLoad` in the
        preamble; `StyleChange` is always the simple variant)."""
        cur = self._current_status.current_item
        cur_cfg = cur.configuration
        new_cfg = item.configuration
        if (new_cfg.top_beam != cur_cfg.top_beam
                or new_cfg.btm_beam != cur_cfg.btm_beam
                or item.family != cur.family):
            raise NotImplementedError(
                'plan_production currently only supports items that share '
                'top yarn, btm yarn, and family with the current item; got '
                f'{item.id!r} (top={new_cfg.top_beam!r}, '
                f'btm={new_cfg.btm_beam!r}, family={item.family!r}) against '
                f'current {cur.id!r} (top={cur_cfg.top_beam!r}, '
                f'btm={cur_cfg.btm_beam!r}, family={cur.family!r})'
            )

        if start_at not in ('next_job_end', 'next_runout'):
            raise ValueError(
                f"start_at must be 'next_job_end' or 'next_runout', "
                f'got {start_at!r}'
            )
        if idle_for < timedelta(0):
            raise ValueError(f'idle_for must be non-negative, got {idle_for}')

        emitted: list[Activity] = []
        working = self._current_status

        # Optional idle gap at the head of the plan.
        if idle_for > timedelta(0):
            working = self._emit_idle(emitted, working, idle_for)

        # Phase 1: run-up (only in 'next_runout' mode).
        if start_at == 'next_runout':
            working = self._emit_run_up(emitted, working)

        # Phase 2: changeover preamble. Phase 2 means same yarn, so the only
        # beam work is a BeamLoad for any naturally exhausted bar (i.e., the
        # post-runout case). Then a simple StyleChange if the item differs.
        working = self._emit_phase2_preamble(emitted, working, item)

        # Phase 3: production loop for the new item.
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

    def _emit_phase2_preamble(
        self, emitted: list[Activity], working: Status, item: 'Greige',
    ) -> Status:
        """Phase 2 preamble: BeamLoad any empty bar (same yarn as current
        item), then StyleChange if needed. No TapeOuts — the Phase 2
        restriction guarantees yarn does not change, so threaded yarn is
        already correct for `item`."""
        cfg = item.configuration
        if working.top_lbs_remaining <= _FLOAT_EPS:
            working = self._emit_beam_load(
                emitted, working, 'top', BeamSet(cfg.top_beam),
            )
        if working.btm_lbs_remaining <= _FLOAT_EPS:
            working = self._emit_beam_load(
                emitted, working, 'btm', BeamSet(cfg.btm_beam),
            )
        if item != working.current_item:
            working = self._emit_style_change(
                emitted, working, item, is_family_change=False,
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
