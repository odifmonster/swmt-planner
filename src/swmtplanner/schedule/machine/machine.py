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


# Runout model (Step 2) — tunable, to be calibrated against real floor
# behavior. A beam is never knit to zero: `_BEAM_FLOOR_LBS` is the residue
# that can't be drawn off, so usable yarn on a bar is
# `bar_lbs - _BEAM_FLOOR_LBS`. The operator also won't knit through a
# near-empty beam: when a bar's usable falls below `_MAX_BEAM_WASTE_LBS`,
# the bar is swapped (its residue discarded as `Waste`) before the next
# roll rather than knit down further. See the Constants section of
# schedule/DESIGN.md.
_BEAM_FLOOR_LBS = 5.0
_MAX_BEAM_WASTE_LBS = 100.0


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
        """Forward-extrapolated time at which the machine would change over
        after running `current_status.current_item` from
        `current_status.as_of`. Matches `plan_production`'s whole-roll
        behavior: the run-up produces whole rolls only, so this is the end of
        the **last whole roll** that finishes above the floor
        (`_BEAM_FLOOR_LBS`) — not the instant a beam first crosses the floor.
        Real greiges always draw from both bars (top_pct, btm_pct > 0), so
        this is always well-defined. When fewer than one whole roll fits
        above the floor (including a bar already at or below it),
        `next_runout == current_status.as_of` — the changeover is
        immediately due."""
        s = self._current_status
        cfg = s.current_item.configuration
        item = s.current_item
        n_rolls = _whole_rolls_before_floor(
            s.top_lbs_remaining, cfg.top_pct,
            s.btm_lbs_remaining, cfg.btm_pct, item.tgt_wt,
        )
        rate = item.get_rate_on_mchn(self._id)
        hours = n_rolls * item.tgt_wt / rate
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
        """Produce `working.current_item` toward a beam runout in **whole
        rolls only** — never starting a roll the current beams can't finish
        above `_BEAM_FLOOR_LBS`, so the machine is never stranded mid-roll at
        the changeover. Emits at most one `Knit` (no `Waste`, no beam work of
        its own) and appends one run-up `Job` of the produced rolls to `jobs`
        (omitted when no whole roll fits). Each bar keeps its leftover usable
        yarn for the preamble to resolve. Returns the working status with
        `current_item` unchanged."""
        cur = working.current_item
        cfg = cur.configuration
        # Whole rolls only — the same stopping point next_runout predicts.
        n_rolls = _whole_rolls_before_floor(
            working.top_lbs_remaining, cfg.top_pct,
            working.btm_lbs_remaining, cfg.btm_pct, cur.tgt_wt,
        )
        if n_rolls <= 0:
            return working

        knit_lbs = n_rolls * cur.tgt_wt
        rate = cur.get_rate_on_mchn(self._id)
        rolls = self._emit_rolls(working.as_of, knit_lbs, rate, cur.tgt_wt)
        working = self._emit_knit(emitted, working, cur, knit_lbs)
        jobs.append(Job(item=cur, rolls=rolls))
        return working

    def _emit_preamble(
        self, emitted: list[Activity], working: Status, item: 'Greige',
    ) -> Status:
        """Changeover preamble. The run-up no longer drains a bar to empty,
        so each bar arrives in one of four states, resolved against the new
        `item`'s yarn and the bar's `usable = bar_lbs - _BEAM_FLOOR_LBS`:

        - Empty / at the floor (`usable <= 0`): `BeamLoad` only.
        - Yarn matches `item`: nothing — the beam and its leftover carry
          over, drawn at the new item's pct (a near-empty match is left for
          the production loop's pre-roll gate to swap).
        - Yarn mismatches, `usable > _MAX_BEAM_WASTE_LBS`: `TapeOut` +
          `BeamLoad` — preserve the worthwhile yarn (the machine reverses
          it; the preserved beam is not tracked in inventory yet).
        - Yarn mismatches, `usable <= _MAX_BEAM_WASTE_LBS`: `Waste` +
          `BeamLoad` — discard the residue (zero-duration unknit drop).

        When both bars need a tape-out, emit a single `TapeOut('both')`
        rather than two singles (cheaper per the duration table); since the
        run-up emits no beam work, this can arise in either mode. After all
        beam work, emit `StyleChange` if `item != current_item`, with
        `is_family_change` set from the family comparison."""
        cfg = item.configuration

        def bar_action(bar_lbs: float, beam: 'BeamSet | None',
                       want_beam: str) -> str:
            """One of 'load' (empty), 'keep' (matching yarn), 'tape'
            (mismatch worth preserving), or 'waste' (mismatch to discard)."""
            usable = bar_lbs - _BEAM_FLOOR_LBS
            if usable <= _FLOAT_EPS:
                return 'load'
            if beam is not None and beam.id == want_beam:
                return 'keep'
            return 'tape' if usable > _MAX_BEAM_WASTE_LBS else 'waste'

        top_action = bar_action(
            working.top_lbs_remaining, working.top_beam, cfg.top_beam,
        )
        btm_action = bar_action(
            working.btm_lbs_remaining, working.btm_beam, cfg.btm_beam,
        )

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
                working.top_lbs_remaining - _BEAM_FLOOR_LBS,
            )
        if btm_action == 'waste':
            working = self._emit_waste(
                emitted, working, 'btm',
                working.btm_lbs_remaining - _BEAM_FLOOR_LBS,
            )

        # Beam-load phase — every bar that wasn't kept gets a fresh beam.
        # Top first, then btm.
        if top_action != 'keep':
            working = self._emit_beam_load(
                emitted, working, 'top', BeamSet(cfg.top_beam),
            )
        if btm_action != 'keep':
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
        """Wind `lbs` of `item` (a whole multiple of `tgt_wt`) as continuous
        production, breaking the run into separate `Knit`s only at beam
        events and recording each completed `Roll` on one straddle-aware
        `Job`. Rolls are always whole `tgt_wt` rolls; a roll that hits a beam
        floor mid-wind continues on the fresh beam, so a single roll can
        span two `Knit`s and a `Job` can span many `BeamLoad`s. BeamLoads
        here use the same yarn as `item` (the preamble guaranteed it). See
        the production-loop walk in DESIGN.md."""
        cfg = item.configuration
        rate = item.get_rate_on_mchn(self._id)
        tgt = item.tgt_wt
        rolls: list[Roll] = []

        rolls_left = round(lbs / tgt)   # whole rolls owed (lbs is a multiple)
        roll_filled = 0.0               # lbs wound on the in-progress roll
        knit = 0.0                      # lbs in the current (unflushed) Knit

        def usable(bar_lbs: float, pct: float) -> float:
            """Live usable yarn on a bar, net of the un-flushed Knit: a bar
            is exhausted at `usable <= 0`, near-empty below
            `_MAX_BEAM_WASTE_LBS`."""
            return bar_lbs - knit * pct - _BEAM_FLOOR_LBS

        def flush() -> None:
            """Emit the open Knit (if any) and reset the accumulator. The
            Knit's start is the current `working.as_of`, unchanged since the
            accumulator opened (nothing else is emitted mid-segment)."""
            nonlocal working, knit
            if knit > _FLOAT_EPS:
                working = self._emit_knit(emitted, working, item, knit)
                knit = 0.0

        def resolve() -> None:
            """Reload any exhausted bar; swap (discarding its residue as
            `Waste`) any near-empty bar. Flushes the open Knit before any
            beam work so the Knit ends at the swap. Checking both bars
            handles the co-swap: when one runs out and the other has also
            fallen below the threshold, both are swapped together."""
            nonlocal working
            for bar, beam_id, pct in (
                ('top', cfg.top_beam, cfg.top_pct),
                ('btm', cfg.btm_beam, cfg.btm_pct),
            ):
                bar_lbs = (working.top_lbs_remaining if bar == 'top'
                           else working.btm_lbs_remaining)
                u = usable(bar_lbs, pct)
                if u <= _FLOAT_EPS:             # exhausted — reload to continue
                    flush()
                    working = self._emit_beam_load(
                        emitted, working, bar, BeamSet(beam_id),
                    )
                elif u < _MAX_BEAM_WASTE_LBS:   # near-empty — swap, discard residue
                    flush()
                    working = self._emit_waste(
                        emitted, working, bar, u,
                    )
                    working = self._emit_beam_load(
                        emitted, working, bar, BeamSet(beam_id),
                    )

        while rolls_left > 0:
            if roll_filled == 0.0:
                resolve()                       # pre-roll max-waste gate
            producible = min(
                usable(working.top_lbs_remaining, cfg.top_pct) / cfg.top_pct,
                usable(working.btm_lbs_remaining, cfg.btm_pct) / cfg.btm_pct,
            )
            step = min(tgt - roll_filled, producible)
            knit += step
            roll_filled += step
            if roll_filled >= tgt - _FLOAT_EPS:  # roll complete
                self._emit_roll(rolls, tgt, working.as_of, knit, rate)
                roll_filled = 0.0
                rolls_left -= 1
            else:                                # a bar hit the floor mid-roll
                resolve()                        # reload it; co-swap the other

        flush()                                  # final Knit

        if rolls:
            jobs.append(Job(item=item, rolls=tuple(rolls)))

    # ----- single-activity emission helpers -----

    def _emit_knit(
        self, emitted: list[Activity], working: Status,
        item: 'Greige', lbs: float,
    ) -> Status:
        """Emit one `Knit` activity for `lbs` of `item`. A `Knit` is one
        uninterrupted run between beam events and may end mid-roll, so it no
        longer derives the rolls it produces — roll tracking is owned by the
        caller (run-up / production loop), which records `Roll`s onto the
        `Job` independently via `_emit_rolls`. See DESIGN.md."""
        rate = item.get_rate_on_mchn(self._id)
        start = working.as_of
        end = self._workcal.offset_work_hours(start, lbs / rate)
        emitted.append(Knit(start=start, end=end, item=item, lbs=lbs))
        return working.apply_activity(emitted[-1])

    def _emit_rolls(
        self, start: datetime, lbs: float, rate: float, tgt_wt: float,
    ) -> tuple[Roll, ...]:
        """Build the `Roll`s completed by a contiguous run of `lbs` at
        `rate` starting at `start`. Per-roll lbs sum to exactly `lbs` (mass
        conservation); when the total snaps to a clean N-roll count under
        `_ROLL_TOLERANCE`, the lbs are spread evenly across the N rolls.
        Completion times respect `workcal`.

        Moved here from the former module-level `_compute_rolls`. The
        trailing partial-roll branch is legacy half-roll handling — dead for
        the whole-roll run-up, and slated for rework when the production
        loop's straddling-roll logic is rewritten."""
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
                    completion_time=self._workcal.offset_work_hours(
                        start, cumulative / rate,
                    ),
                ))
            return tuple(rolls)

        # Non-snap: `floor(lbs / tgt_wt)` whole rolls plus one partial.
        n_full = int(n_rolls_exact)
        for _ in range(n_full):
            cumulative += tgt_wt
            rolls.append(Roll(
                lbs=tgt_wt,
                completion_time=self._workcal.offset_work_hours(
                    start, cumulative / rate,
                ),
            ))
        residual = lbs - cumulative
        if residual > _FLOAT_EPS:
            cumulative += residual
            rolls.append(Roll(
                lbs=residual,
                completion_time=self._workcal.offset_work_hours(
                    start, cumulative / rate,
                ),
            ))
        return tuple(rolls)

    def _emit_roll(
        self, rolls: list[Roll], lbs: float,
        start: datetime, wound: float, rate: float,
    ) -> None:
        """Append one completed `Roll` of `lbs` to `rolls`, accumulating into
        the production loop's straddle-aware roll list. Its completion time
        is the moment the roll's final lb is wound: `wound` lbs into the
        current `Knit` segment that began at `start`, knit at `rate`. For a
        roll that straddles a `BeamLoad`, `start`/`wound` describe the later
        segment that completes it, not the roll's whole span."""
        rolls.append(Roll(
            lbs=lbs,
            completion_time=self._workcal.offset_work_hours(
                start, wound / rate,
            ),
        ))

    def _emit_waste(
        self, emitted: list[Activity], working: Status,
        bar: Literal['top', 'btm'], lbs: float,
    ) -> Status:
        """Emit a zero-duration `Waste` discarding `lbs` of usable residue
        from `bar`. The discarded yarn is the beam currently on that bar
        (read from `working`). The yarn is removed unknit, so the activity
        occupies no machine time (`start == end`); applying it empties the
        named bar (beam -> None, lbs -> 0) so a paired `BeamLoad` can refill
        it."""
        start = working.as_of
        beam = working.top_beam if bar == 'top' else working.btm_beam
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
        end = self._workcal.offset_work_hours(
            start, duration.total_seconds() / 3600,
        )
        top_beam = working.top_beam if bars in ('top', 'both') else None
        btm_beam = working.btm_beam if bars in ('btm', 'both') else None
        emitted.append(TapeOut(start=start, end=end, bars=bars,
                               top_beam=top_beam, btm_beam=btm_beam))
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


def _whole_rolls_before_floor(
    top_lbs: float, top_pct: float,
    btm_lbs: float, btm_pct: float, tgt_wt: float,
) -> int:
    """Whole rolls of an item with these pcts and `tgt_wt` that the given
    bar lbs can finish before either beam reaches `_BEAM_FLOOR_LBS`. Snaps a
    near-integer count to absorb float drift from the usable/pct division,
    then floors; never negative.

    Shared by the run-up and `next_runout` so both stop at exactly the same
    whole-roll boundary. The plant ships only whole rolls, so the runout
    decision point is the end of the last whole roll — not the instant a
    beam first crosses the floor — and the prediction must match the
    activities a `'next_runout'` plan actually emits."""
    usable = min(
        (top_lbs - _BEAM_FLOOR_LBS) / top_pct,
        (btm_lbs - _BEAM_FLOOR_LBS) / btm_pct,
    )
    n_exact = usable / tgt_wt
    n_rounded = round(n_exact)
    if abs(n_rounded - n_exact) < _ROLL_TOLERANCE:
        n = n_rounded
    else:
        n = math.floor(n_exact)
    return max(0, n)
