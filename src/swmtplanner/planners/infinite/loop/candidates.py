#!/usr/bin/env python

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, TYPE_CHECKING

from swmtplanner.planners.infinite.state import Move, State

if TYPE_CHECKING:
    from swmtplanner.products import Greige


# Float-precision tolerance for snapping the lbs-cap to a clean roll
# boundary. Matches the pattern used in `Machine.producible_lbs_in_week`.
_FLOAT_EPS = 1e-6


@dataclass(frozen=True)
class DecisionPoint:
    """A point in time at which a machine could begin new production.

    Each machine has at most two: `next_job_end` (the schedule tail) and
    `next_runout` (the forward-extrapolated time at which the current
    item's beam(s) would naturally exhaust). They collapse to one when
    they coincide — e.g., when the schedule has just exhausted a beam at
    its tail. The `start_at` value matches the `Machine.plan_production`
    argument of the same name."""
    machine_id: str
    start_at: Literal['next_job_end', 'next_runout']
    time: datetime


@dataclass(frozen=True)
class RegularOrder:
    """The earliest week of unmet demand for an item (per the
    safety-aware view's `remaining_lbs`). `due_date` is used by the
    carrying-avoidance idle calculation when this order is paired with
    a decision point."""
    item: 'Greige'
    week_idx: int
    due_date: datetime
    lbs: float


@dataclass(frozen=True)
class SafetyOrder:
    """A request to top up an item's safety pool to its target. Safety
    fills don't accrue carrying cost in the demand view, so they're not
    subject to carrying-avoidance idle."""
    item: 'Greige'
    lbs: float


def eligible_decision_points(state: State) -> list[DecisionPoint]:
    """Return every machine's in-window decision points
    (`time <= state.window_end`). Deduplicates the case where a
    machine's `next_job_end` and `next_runout` coincide — only the
    `'next_job_end'` entry is emitted in that case, since the two are
    behaviorally identical when there's no current-item run-up to
    perform.

    `next_runout >= next_job_end` always, so a `next_runout` in the
    window implies `next_job_end` is in the window too — no asymmetric
    case to worry about."""
    out: list[DecisionPoint] = []
    for machine_id, machine in state.machines.items():
        job_end = machine.next_job_end
        runout = machine.next_runout
        if job_end <= state.window_end:
            out.append(DecisionPoint(
                machine_id=machine_id,
                start_at='next_job_end',
                time=job_end,
            ))
        if runout != job_end and runout <= state.window_end:
            out.append(DecisionPoint(
                machine_id=machine_id,
                start_at='next_runout',
                time=runout,
            ))
    return out


def eligible_orders(state: State) -> list[RegularOrder | SafetyOrder]:
    """For each `RlsItem`, return up to two eligible orders:

    - One `RegularOrder` for the earliest week with unmet demand, read
      from the safety-aware view. At most one per item per call.
    - One `SafetyOrder` if `safety_view.safety_pool` is below the
      `safety_target`. At most one per item per call.

    Items whose demand is fully met *and* whose safety pool is at-or-
    above target contribute nothing."""
    out: list[RegularOrder | SafetyOrder] = []
    for rls in state.rls_items.values():
        # Regular: earliest safety-aware order with unmet demand. The
        # safety_view.orders tuple is week_idx-ordered by construction.
        for order in rls.safety_view.orders:
            if order.remaining_lbs > 0:
                out.append(RegularOrder(
                    item=rls.item,
                    week_idx=order.week.week_idx,
                    due_date=order.week.due_date,
                    lbs=order.remaining_lbs,
                ))
                break
        # Safety: top-up if pool is below target.
        safety_gap = (
            rls.safety_view.safety_target - rls.safety_view.safety_pool
        )
        if safety_gap > 0:
            out.append(SafetyOrder(item=rls.item, lbs=safety_gap))
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
            # We hand this to `producible_lbs_in_week` as `start`, and
            # use its ISO week as the cap window.
            effective_start = machine.workcal.offset_work_hours(
                dp.time, idle_hours,
            )
            iso_year, iso_week, _ = effective_start.isocalendar()
            producible_cap = machine.producible_lbs_in_week(
                order.item, iso_year, iso_week, start=effective_start,
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
            )

            out.append(Move(
                machine_id=dp.machine_id,
                item=order.item,
                lbs=lbs,
                start_at=dp.start_at,
                idle_for=idle_for,
                plan=plan,
            ))

    return out
