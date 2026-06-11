#!/usr/bin/env python

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from swmtplanner.planners.infinite.state import Move, State
from swmtplanner.planners.infinite.coordination import (
    RegularOrder, eligible_orders,
)


# Float-precision tolerance for snapping the lbs-cap to a clean roll
# boundary. Matches the pattern used in `Machine.producible_lbs_in_week`.
_FLOAT_EPS = 1e-6


@dataclass(frozen=True)
class DecisionPoint:
    """A point in time at which a machine could begin new production.

    Each machine has at most two: `schedule_tail` (the schedule tail) and
    `next_runout` (the forward-extrapolated time at which the current
    item's beam(s) would naturally exhaust). They collapse to one when
    they coincide — e.g., when the schedule has just exhausted a beam at
    its tail. The `start_at` value matches the `Machine.plan_production`
    argument of the same name."""
    machine_id: str
    start_at: Literal['schedule_tail', 'next_runout']
    time: datetime


def eligible_decision_points(state: State) -> list[DecisionPoint]:
    """Return every machine's in-window decision points
    (`time <= state.window_end`). Deduplicates the case where a
    machine's `schedule_tail` and `next_runout` coincide — only the
    `'schedule_tail'` entry is emitted in that case, since the two are
    behaviorally identical when there's no current-item run-up to
    perform.

    `next_runout >= schedule_tail` always, so a `next_runout` in the
    window implies `schedule_tail` is in the window too — no asymmetric
    case to worry about."""
    out: list[DecisionPoint] = []
    for machine_id, machine in state.machines.items():
        job_end = machine.schedule_tail
        runout = machine.next_runout
        if job_end <= state.window_end:
            out.append(DecisionPoint(
                machine_id=machine_id,
                start_at='schedule_tail',
                time=job_end,
            ))
        if runout != job_end and runout <= state.window_end:
            out.append(DecisionPoint(
                machine_id=machine_id,
                start_at='next_runout',
                time=runout,
            ))
    return out


def enumerate_candidates(state: State) -> list[Move]:
    """For each combination of (decision point × order) where the
    machine can run the order's item, derive `lbs`, `start_at`,
    `idle_for`, and a cached `plan` from `Machine.plan_production`, then
    bundle the result into a `Move`. Combinations whose producible cap
    collapses to less than one full roll are filtered out — those can't
    place anything and would just clutter the scorer.

    The Move's `plan` is computed once here so the same plan can be
    reused for scoring (via `Costing.score_after_move`) and committing
    (via `State.commit_move`) without re-running `plan_production`."""
    decision_points = eligible_decision_points(state)
    orders = eligible_orders(state)

    out: list[Move] = []
    for dp in decision_points:
        machine = state.machines[dp.machine_id]
        for order in orders:
            if not order.item.can_run_on_mchn(dp.machine_id):
                continue

            # 'next_runout' means "finish the current item, then change to a
            # different one." Pairing it with an order for the machine's
            # *current* item is a no-op changeover that `plan_production`
            # rejects (its same-item guard); the 'schedule_tail' point already
            # covers continuing the current item.
            if (dp.start_at == 'next_runout'
                    and order.item == machine.current_status.current_item):
                continue

            # Carrying-avoidance idle: regular orders idle to a target
            # `due_date - lead_time - margin`, where `margin` (default
            # 24h, configured on `State`) is an allowance under the
            # strict no-carry moment. Computed as **work hours** between
            # the decision point and the target — naturally clamps to 0
            # when the target is already in the past. Safety orders
            # don't idle.
            if isinstance(order, RegularOrder):
                rls = state.rls_items[order.item.id]
                target = (
                    order.due_date - rls.lead_time
                    - state.carrying_avoidance_margin
                )
                idle_hours = machine.workcal.get_work_hours_between(
                    dp.time, target,
                )
            else:
                idle_hours = 0.0
            idle_for = timedelta(hours=idle_hours)

            # Effective production-begin time after any leading idle.
            effective_start = machine.workcal.offset_work_hours(
                dp.time, idle_hours,
            )

            # Cap window: normally `effective_start` through the end
            # of the ISO week containing it. But if that window can't
            # fit even one full roll (e.g., the schedule tail landed
            # late Friday with not enough work hours left for a
            # roll), bump the cap end to the end of the *following*
            # ISO week so a tightly-loaded machine doesn't get
            # artificially excluded from contention. The decision-
            # window mechanism still spreads work across machines.
            producible_cap = _producible_cap_with_bumpup(
                machine, order.item, effective_start,
            )

            # Round min(order_lbs, producible_cap) down to whole rolls.
            # Snap near-integer roll counts up to handle float drift
            # from chained division in the cap calculation.
            lbs_uncapped = min(order.lbs, producible_cap)
            n_rolls_exact = lbs_uncapped / order.item.tgt_wt
            n_rolls_rounded = round(n_rolls_exact)
            if abs(n_rolls_rounded - n_rolls_exact) < _FLOAT_EPS:
                n_rolls = n_rolls_rounded
            else:
                n_rolls = math.floor(n_rolls_exact)
            if n_rolls <= 0:
                continue
            lbs = n_rolls * order.item.tgt_wt

            plan = machine.plan_production(
                order.item, lbs,
                start_at=dp.start_at,
                idle_for=idle_for,
                tgt_order=order.order_id,
            )

            out.append(Move(
                machine_id=dp.machine_id,
                item=order.item,
                lbs=lbs,
                start_at=dp.start_at,
                idle_for=idle_for,
                plan=plan,
                week_idx=(
                    order.week_idx if isinstance(order, RegularOrder)
                    else None
                ),
            ))

    return out


def _end_of_iso_week(t: datetime) -> datetime:
    """End of the ISO week containing `t` — i.e., the start of the
    following ISO week (Monday 00:00). Used as the default right edge
    of the producible-cap window."""
    iso_year, iso_week, _ = t.isocalendar()
    monday = date.fromisocalendar(iso_year, iso_week, 1)
    return datetime(monday.year, monday.month, monday.day) + timedelta(days=7)


def _producible_cap_with_bumpup(
    machine, item, effective_start: datetime,
) -> float:
    """Producible lbs from `effective_start` through the end of its
    ISO week, with one-week bump-up when that window can't fit a
    single roll.

    The default cap window is `[effective_start, end_of_iso_week)`.
    If `producible_lbs_through` returns 0 for that window — i.e., the
    remaining work hours (after preamble) aren't enough to produce
    even one full roll of `item` — we extend the cap end by 7 days
    so the schedule tail doesn't artificially exclude this
    (machine, item) pair from contention. A machine ending its
    schedule late on a Friday should still be able to commit a
    sensible chunk of next week's work; the alternative (returning
    0 here) would force the loop to advance the decision window past
    this machine entirely."""
    current_week_end = _end_of_iso_week(effective_start)
    cap = machine.producible_lbs_through(
        item, end=current_week_end, start=effective_start,
    )
    if cap > 0:
        return cap
    next_week_end = current_week_end + timedelta(days=7)
    return machine.producible_lbs_through(
        item, end=next_week_end, start=effective_start,
    )
