#!/usr/bin/env python

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from swmtplanner.schedule import Fill
from swmtplanner.planners.infinite.state import Move, State
from swmtplanner.planners.infinite.coordination import (
    RegularOrder, eligible_orders, unique_setups,
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
        if (runout != job_end
            and runout <= state.window_end
            and machine.current_status.current_item.id != 'NONE'):
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
    bundle the result into a `Move`. A regular move is sized to the
    item's open demand through the reference week (`_open_demand`), a
    safety move to the safety gap, both capped at the machine's
    producible lbs through the ISO week. Combinations whose producible
    cap collapses to less than one full roll are filtered out — those
    can't place anything and would just clutter the scorer.

    The Move's `plan` is computed once here so the same plan can be
    reused for scoring (via `Costing.score_after_move`) and committing
    (via `State.commit_move`) without re-running `plan_production`."""
    decision_points = eligible_decision_points(state)
    orders = eligible_orders(state)
    unique = unique_setups(state)

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
            # A move that changes the item may wait for a ration slot; it is
            # planned to knit the current item meanwhile, as far as the plant
            # still wants it (see "Filling a slot wait" in DESIGN.md).
            fill = fill_for(state, machine, order.item)

            producible_cap = _producible_cap_with_bumpup(
                machine, order.item, effective_start, state.inventory,
                state.capacity, fill,
            )

            # Open-demand sizing: a regular move is sized to the item's whole
            # open demand (its unmet regular orders through the reference
            # week), not just the one order it targets, whether it changes
            # the machine's item or continues it — so a setup buys the
            # backlog it is paid for, and a machine already on the right
            # yarn brings the same backlog to the comparison. A safety order
            # is its gap. See "Open-demand sizing" in DESIGN.md.
            target_lbs = order.lbs
            batched = False
            if isinstance(order, RegularOrder):
                target_lbs = max(order.lbs, _open_demand(state, order.item))
                # Economic order quantity: a unique-setup item whose open
                # demand is a few rolls is batched up with its later weeks,
                # and the batch is not capped at the week (see "Economic
                # order quantity for unique setups" in DESIGN.md).
                if (order.item.id in unique
                        and target_lbs <= state.eoq_threshold_rolls * order.item.tgt_wt + _FLOAT_EPS):
                    target_lbs = _batched_demand(
                        state, order.item, state.eoq_batch_rolls * order.item.tgt_wt)
                    batched = True

            # Round min(target_lbs, producible_cap) down to whole rolls.
            # Snap near-integer roll counts up to handle float drift
            # from chained division in the cap calculation.
            lbs_uncapped = target_lbs if batched else min(target_lbs, producible_cap)
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
                inventory=state.inventory,
                capacity=state.capacity,
                fill=fill,
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
                # The targeted order's unfulfilled lbs (capped production
                # `lbs` above is separate); carried for the debug log.
                order_remaining_lbs=order.lbs,
            ))

    return out


def fill_for(state: State, machine, item) -> Fill | None:
    """The fill a move changing `machine` to `item` is planned with (see
    "Filling a slot wait" in DESIGN.md): the current item's whole open
    demand — every regular order's remaining lbs, any week, plus its safety
    gap — rounded up to whole rolls, raised against its earliest open
    regular order, else its safety order. None for a move that continues
    the current item, a machine with no item or on an item it cannot run
    (nothing to fill with), an item the run does not have, or one with no
    open demand."""
    cur = machine.current_status.current_item
    if cur.id == 'NONE' or cur == item or not machine.can_run_current_item:
        return None
    rls = state.rls_items.get(cur.id)
    if rls is None:
        return None
    view = rls.safety_view
    open_orders = sorted((o for o in view.orders if o.remaining_lbs > 0),
                         key=lambda o: o.week.week_idx)
    gap = max(0.0, view.safety_target - view.safety_pool)
    total = sum(o.remaining_lbs for o in open_orders) + gap
    if total <= _FLOAT_EPS:
        return None
    tgt = open_orders[0].id if open_orders else view.safety.id
    rolls = math.ceil(total / cur.tgt_wt - _FLOAT_EPS)
    return Fill(rolls=rolls, tgt_order=tgt)


def _open_demand(state: State, item) -> float:
    """The item's open demand: the sum of `remaining_lbs` over its
    safety-view orders with `week_idx <= state.reference_week_idx` — the
    orders `eligible_orders` treats as urgent. A regular move is sized to
    this rather than to the one order it targets (see "Open-demand
    sizing" in DESIGN.md)."""
    rls = state.rls_items[item.id]
    return sum(
        o.remaining_lbs for o in rls.safety_view.orders
        if o.remaining_lbs > 0
        and o.week.week_idx <= state.reference_week_idx
    )


def _batched_demand(state: State, item, at_least: float) -> float:
    """The item's unmet regular demand in week order — the open orders and
    then the later weeks — summed until it reaches `at_least` lbs or every
    order on the schedule is in (the economic order quantity for a
    unique-setup item; see "Move sizing" in DESIGN.md)."""
    rls = state.rls_items[item.id]
    total = 0.0
    for o in sorted(rls.safety_view.orders, key=lambda o: o.week.week_idx):
        if o.remaining_lbs <= 0:
            continue
        total += o.remaining_lbs
        if total >= at_least - _FLOAT_EPS:
            break
    return total


def _end_of_iso_week(t: datetime) -> datetime:
    """End of the ISO week containing `t` — i.e., the start of the
    following ISO week (Monday 00:00). Used as the default right edge
    of the producible-cap window."""
    iso_year, iso_week, _ = t.isocalendar()
    monday = date.fromisocalendar(iso_year, iso_week, 1)
    return datetime(monday.year, monday.month, monday.day) + timedelta(days=7)


def _producible_cap_with_bumpup(
    machine, item, effective_start: datetime, inventory=None, capacity=None,
    fill=None,
) -> float:
    """Producible lbs from `effective_start` through the end of its ISO
    week — or through the end of the *following* week when fewer than
    three work days (`3 × workcal.hours_per_day` work hours) of the
    current week remain at `effective_start`.

    A tail late in the week would otherwise be offered only the week's
    remnant, and the planner was seen committing a single roll of a very
    large order there; sized through the next week the move is a run
    worth its setup. See "Move sizing" in DESIGN.md."""
    current_week_end = _end_of_iso_week(effective_start)
    workcal = machine.workcal
    remaining = workcal.get_work_hours_between(effective_start, current_week_end)
    end = current_week_end
    if remaining < 3 * workcal.hours_per_day:
        end = current_week_end + timedelta(days=7)
    return machine.producible_lbs_through(
        item, end=end, start=effective_start,
        inventory=inventory, capacity=capacity, fill=fill,
    )
