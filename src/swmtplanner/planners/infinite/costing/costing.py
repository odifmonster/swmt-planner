#!/usr/bin/env python

from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING

from swmtplanner.schedule import (
    Job, TapeOut, StyleChange, RunnerChange, PatternChange, Idle, Waste,
)

from swmtplanner.planners.infinite.coordination import OrderKey, ScoringContext
from swmtplanner.planners.infinite.state import Move, State

if TYPE_CHECKING:
    from swmtplanner.schedule import Activity
    from swmtplanner.support import WorkCal
    from swmtplanner.debuglog import DebugLog


@dataclass
class CostWeights:
    """Weights for Phase 1+2 cost scoring. Each component is multiplied
    by its corresponding weight and summed into the state's total score.

    Per-item demand weights apply to the unweighted `CostComponents`
    returned by `RlsItem.cost_if` / the demand views. Per-machine
    schedule weights apply per occurrence (TapeOut, the changeover types),
    per work-hour (Idle), or per lb (Waste). Phase 2 cross-cutting weights apply per move
    being scored — `priority` per rank step, `level_loading` per work-
    hour delta from the earliest decision point, `old_machine` per move
    that targets a legacy machine when a new one is candidate-available
    for the same item. All weights are required; callers must set every
    field explicitly (0 to opt out of a contribution)."""
    # per-item demand weights
    lateness: float
    drainage: float
    carrying: float
    excess: float
    # per-machine schedule weights — per occurrence
    tape_out_single: float
    tape_out_both: float
    # changeover weights, by type (StyleChange = new machine; RunnerChange =
    # legacy within pattern family; PatternChange = legacy cross-family)
    style_change: float
    runner_change: float
    pattern_change: float
    # per-machine schedule weight — per work-hour
    idle_time: float
    # per-machine schedule weight — per lb of discarded Waste
    waste_lbs: float
    # cross-cutting weights (Phase 2)
    priority: float
    level_loading: float
    old_machine: float


@dataclass(frozen=True)
class PriorityContribution:
    """Value type for `CostBreakdown.priority_by_item`. The enclosing
    dict is keyed by `item_id`; at most one entry per item appears
    because the candidate enumerator picks at most one regular order
    per item per iteration, so each item has a unique higher-priority
    counterpart. See DESIGN.md."""
    week_idx: int                 # week (0..3) of the deferred regular order
    remaining_lbs: float          # unfulfilled lbs of the order at evaluation time
    priority: float               # weighted contribution: w.priority × remaining_lbs × 2^days_late(O, move)


@dataclass(frozen=True)
class CostBreakdown:
    """Per-component weighted contributions for a single state. The sum
    of the fourteen scalar fields equals `Costing.score_after_move(state,
    move, ctx)` when produced by `cost_breakdown_after_move`, or
    `Costing.score(state)` when produced by `cost_breakdown(state)`.

    Returned by both `Costing.cost_breakdown(state)` (baseline; per-move
    cross-cutting costs are 0 and `priority_by_item` is empty) and
    `Costing.cost_breakdown_after_move(state, move, ctx)` (post-commit).

    The `*_by_item` dicts hold *absolute* weighted per-item contributions
    for the state the breakdown describes. Only items with a non-zero
    contribution are present. The verbose loop computes per-item deltas
    by subtracting baseline values from post-commit values; this layer
    just exposes the absolute per-item attribution. See DESIGN.md's
    "Verbose iteration log" section for the consumer side."""
    # per-item demand contributions (weighted totals)
    lateness: float
    drainage: float
    carrying: float
    excess: float
    # per-machine schedule contributions
    tape_out_single: float
    tape_out_both: float
    style_change: float
    runner_change: float
    pattern_change: float
    idle_time: float
    waste_lbs: float
    # cross-cutting contributions
    priority: float
    level_loading: float
    old_machine: float
    # absolute per-item breakdowns (only non-zero contributions)
    lateness_by_item: dict[str, float] = field(default_factory=dict)
    drainage_by_item: dict[str, float] = field(default_factory=dict)
    carrying_by_item: dict[str, float] = field(default_factory=dict)
    excess_by_item: dict[str, float] = field(default_factory=dict)
    # per-item priority breakdown — at most one PriorityContribution per item
    priority_by_item: dict[str, PriorityContribution] = field(default_factory=dict)

    @property
    def total(self) -> float:
        return (
            self.lateness + self.drainage + self.carrying + self.excess
            + self.tape_out_single + self.tape_out_both
            + self.style_change + self.runner_change + self.pattern_change
            + self.idle_time + self.waste_lbs
            + self.priority + self.level_loading + self.old_machine
        )


class Costing:
    """Combines per-item demand costs, per-machine schedule penalties,
    and (Phase 2) per-move cross-cutting costs into a single scalar.

    `score(state)` returns the state-only portion — per-item demand +
    per-machine schedule. There is no ctx parameter: the cross-cutting
    costs are inherently per-move and only apply during candidate
    evaluation, not when scoring a post-loop final state.

    `score_after_move(state, move, ctx)` returns the same per-item +
    per-machine portion computed against the hypothetical post-commit
    state, *plus* the move's cross-cutting contributions read off
    `ctx` (priority, level-loading, old-machine). Pure — does not
    mutate `state`. `ctx` is required.

    `cost_breakdown(state)` and `cost_breakdown_after_move(state, move,
    ctx)` mirror the two `score*` methods but return a `CostBreakdown`
    record — fourteen weighted scalars plus per-item dicts for the four
    demand-side costs and for priority. Used by the verbose iteration
    log; the hot scoring loop stays on the scalar `score*` methods."""

    def __init__(self, weights: CostWeights) -> None:
        self._weights = weights

    @property
    def weights(self) -> CostWeights:
        return self._weights

    def score(self, state: State) -> float:
        """Score the current state — weighted sum of per-item demand
        costs (read from the rls_items' views as-is) and per-machine
        schedule penalties (counted off each machine's committed
        activities)."""
        total = 0.0
        for rls in state.rls_items.values():
            total += self._weighted_demand(
                rls.raw_view.lateness,
                rls.safety_view.drainage,
                rls.safety_view.carrying,
                rls.safety_view.excess,
            )
        for machine in state.machines.values():
            total += self._schedule_penalty(machine)
        return total

    def score_after_move(
        self, state: State, move: Move, ctx: ScoringContext,
        debuglog: 'DebugLog | None' = None,
    ) -> float:
        """Score the state as if `move` were committed. Pure — does not
        mutate `state`. Internally uses `RlsItem.cost_if(jobs)` for the
        item(s) the move's plan touches, and reads the current view
        trackers for everything else. Schedule penalties for the
        affected machine combine its existing activities with the plan's;
        other machines use their current counts. Adds the move's
        cross-cutting contributions (priority, level-loading,
        old-machine) read off `ctx`.

        When `debuglog` is given, the per-component breakdown is written to its
        `cost_summary` table (one row per weighted component, tagged with the
        current `iteration_log` `move_id`) and the same total is returned. The
        hot path (no `debuglog`) skips that bookkeeping."""
        if debuglog is not None:
            return self._emit_cost_summary(debuglog, state, move, ctx)

        # Group the plan's Job records by their item.id. A single plan
        # can carry Jobs for more than one item (the 'next_runout' run-up
        # adds a Job of the current item ahead of the new item's).
        jobs_by_item: dict[str, list[Job]] = {}
        for job in move.plan.jobs:
            jobs_by_item.setdefault(job.item.id, []).append(job)

        total = 0.0
        # Demand: cost_if for items touched by the plan, current for the rest.
        for item_id, rls in state.rls_items.items():
            if item_id in jobs_by_item:
                cc = rls.cost_if(jobs_by_item[item_id])
                total += self._weighted_demand(
                    cc.lateness, cc.drainage, cc.carrying, cc.excess,
                )
            else:
                total += self._weighted_demand(
                    rls.raw_view.lateness,
                    rls.safety_view.drainage,
                    rls.safety_view.carrying,
                    rls.safety_view.excess,
                )

        # Schedule: combined activities for the affected machine, current
        # for the rest.
        for machine_id, machine in state.machines.items():
            if machine_id == move.machine_id:
                total += self._schedule_penalty_for(
                    list(machine.activities) + list(move.plan.activities),
                    machine.workcal,
                )
            else:
                total += self._schedule_penalty(machine)

        # Cross-cutting per-move contributions (Phase 2).
        total += self._cross_cutting_cost(state, move, ctx)
        return total

    def cost_breakdown(self, state: State) -> CostBreakdown:
        """Baseline breakdown of `state` with no move applied. Total
        equals `score(state)`. Per-move cross-cutting costs
        (`priority`, `level_loading`, `old_machine`) are 0 and
        `priority_by_item` is empty, because those costs only exist
        relative to a candidate move. Used by the verbose iteration
        log as the baseline against which `cost_breakdown_after_move`'s
        per-item dicts are diffed. Pure — does not mutate `state`."""
        w = self._weights
        lateness_by_item: dict[str, float] = {}
        drainage_by_item: dict[str, float] = {}
        carrying_by_item: dict[str, float] = {}
        excess_by_item: dict[str, float] = {}
        lateness_q = drainage_q = carrying_q = excess_q = 0.0
        for item_id, rls in state.rls_items.items():
            l = rls.raw_view.lateness
            d = rls.safety_view.drainage
            c = rls.safety_view.carrying
            e = rls.safety_view.excess
            lateness_q += l
            drainage_q += d
            carrying_q += c
            excess_q += e
            self._record_demand_item(
                item_id, l, d, c, e,
                lateness_by_item, drainage_by_item,
                carrying_by_item, excess_by_item,
            )

        tos_q = tob_q = sc_q = rc_q = pc_q = it_q = wl_q = 0.0
        for machine in state.machines.values():
            stos, stob, ssc, src, spc, sit, swl = \
                self._schedule_quantities_for(
                    machine.activities, machine.workcal,
                )
            tos_q += stos
            tob_q += stob
            sc_q += ssc
            rc_q += src
            pc_q += spc
            it_q += sit
            wl_q += swl

        return CostBreakdown(
            lateness=w.lateness * lateness_q,
            drainage=w.drainage * drainage_q,
            carrying=w.carrying * carrying_q,
            excess=w.excess * excess_q,
            tape_out_single=w.tape_out_single * tos_q,
            tape_out_both=w.tape_out_both * tob_q,
            style_change=w.style_change * sc_q,
            runner_change=w.runner_change * rc_q,
            pattern_change=w.pattern_change * pc_q,
            idle_time=w.idle_time * it_q,
            waste_lbs=w.waste_lbs * wl_q,
            priority=0.0,
            level_loading=0.0,
            old_machine=0.0,
            lateness_by_item=lateness_by_item,
            drainage_by_item=drainage_by_item,
            carrying_by_item=carrying_by_item,
            excess_by_item=excess_by_item,
            priority_by_item={},
        )

    def cost_breakdown_after_move(
        self, state: State, move: Move, ctx: ScoringContext,
    ) -> CostBreakdown:
        """Same total as `score_after_move`, returned as one weighted
        scalar per component plus absolute per-item dicts for the four
        demand-side costs and for priority. Pure — does not mutate
        `state`. Used by the verbose iteration log; the hot loop sticks
        with the scalar `score_after_move` because it avoids the
        `CostBreakdown` allocation and the per-item dict bookkeeping."""
        w = self._weights

        # Demand: per-item weighted contributions. cost_if for items
        # touched by move.plan, current views for the rest.
        jobs_by_item: dict[str, list[Job]] = {}
        for job in move.plan.jobs:
            jobs_by_item.setdefault(job.item.id, []).append(job)
        lateness_by_item: dict[str, float] = {}
        drainage_by_item: dict[str, float] = {}
        carrying_by_item: dict[str, float] = {}
        excess_by_item: dict[str, float] = {}
        lateness_q = drainage_q = carrying_q = excess_q = 0.0
        for item_id, rls in state.rls_items.items():
            if item_id in jobs_by_item:
                cc = rls.cost_if(jobs_by_item[item_id])
                l = cc.lateness
                d = cc.drainage
                c = cc.carrying
                e = cc.excess
            else:
                l = rls.raw_view.lateness
                d = rls.safety_view.drainage
                c = rls.safety_view.carrying
                e = rls.safety_view.excess
            lateness_q += l
            drainage_q += d
            carrying_q += c
            excess_q += e
            self._record_demand_item(
                item_id, l, d, c, e,
                lateness_by_item, drainage_by_item,
                carrying_by_item, excess_by_item,
            )

        # Schedule: combine the affected machine's activities with the
        # move's plan; use existing activities for the rest.
        tos_q = tob_q = sc_q = rc_q = pc_q = it_q = wl_q = 0.0
        for machine_id, machine in state.machines.items():
            if machine_id == move.machine_id:
                activities = list(machine.activities) + list(move.plan.activities)
            else:
                activities = machine.activities
            stos, stob, ssc, src, spc, sit, swl = \
                self._schedule_quantities_for(
                    activities, machine.workcal,
                )
            tos_q += stos
            tob_q += stob
            sc_q += ssc
            rc_q += src
            pc_q += spc
            it_q += sit
            wl_q += swl

        # Cross-cutting.
        move_machine = state.machines[move.machine_id]
        priority_cost, priority_by_item = self._priority_breakdown(move, ctx)
        dp_time = (
            move_machine.schedule_tail
            if move.start_at == 'schedule_tail'
            else move_machine.next_runout
        )
        work_hours_delta = move_machine.workcal.get_work_hours_between(
            ctx.earliest_dp_time, dp_time,
        )
        old_machine_applies = (
            ctx.new_machine_avail.get(move.item, False)
            and not move_machine.is_new
        )

        return CostBreakdown(
            lateness=w.lateness * lateness_q,
            drainage=w.drainage * drainage_q,
            carrying=w.carrying * carrying_q,
            excess=w.excess * excess_q,
            tape_out_single=w.tape_out_single * tos_q,
            tape_out_both=w.tape_out_both * tob_q,
            style_change=w.style_change * sc_q,
            runner_change=w.runner_change * rc_q,
            pattern_change=w.pattern_change * pc_q,
            idle_time=w.idle_time * it_q,
            waste_lbs=w.waste_lbs * wl_q,
            priority=priority_cost,
            level_loading=w.level_loading * work_hours_delta,
            old_machine=(
                w.old_machine if old_machine_applies else 0.0
            ),
            lateness_by_item=lateness_by_item,
            drainage_by_item=drainage_by_item,
            carrying_by_item=carrying_by_item,
            excess_by_item=excess_by_item,
            priority_by_item=priority_by_item,
        )

    def _emit_cost_summary(
        self, debuglog: 'DebugLog', state: State, move: Move,
        ctx: ScoringContext,
    ) -> float:
        """Compute the move's per-component breakdown, write one
        `cost_summary` row per component — keyed `{move_id}_{label}` and linked
        (FK) to the current `iteration_log` row — and return the same total
        `score_after_move` would. Each row carries the component's `raw`
        (unweighted) quantity and weighted `cost`. See debuglog/DESIGN.md."""
        w = self._weights

        # Demand quantities, summed across items (cost_if for the items the
        # plan touches, current view trackers for the rest).
        jobs_by_item: dict[str, list[Job]] = {}
        for job in move.plan.jobs:
            jobs_by_item.setdefault(job.item.id, []).append(job)
        lateness_q = drainage_q = carrying_q = excess_q = 0.0
        for item_id, rls in state.rls_items.items():
            if item_id in jobs_by_item:
                cc = rls.cost_if(jobs_by_item[item_id])
                lateness_q += cc.lateness
                drainage_q += cc.drainage
                carrying_q += cc.carrying
                excess_q += cc.excess
            else:
                lateness_q += rls.raw_view.lateness
                drainage_q += rls.safety_view.drainage
                carrying_q += rls.safety_view.carrying
                excess_q += rls.safety_view.excess

        # Schedule quantities, summed across machines (the affected machine
        # combines its committed activities with the plan's).
        tos_q = tob_q = sc_q = rc_q = pc_q = it_q = wl_q = 0.0
        for machine_id, machine in state.machines.items():
            if machine_id == move.machine_id:
                activities = (
                    list(machine.activities) + list(move.plan.activities)
                )
            else:
                activities = machine.activities
            stos, stob, ssc, src, spc, sit, swl = \
                self._schedule_quantities_for(activities, machine.workcal)
            tos_q += stos
            tob_q += stob
            sc_q += ssc
            rc_q += src
            pc_q += spc
            it_q += sit
            wl_q += swl

        # Cross-cutting quantities (priority opportunity-cost, level-loading
        # work-hour delta, old-machine flag).
        machine = state.machines[move.machine_id]
        priority_q = self._priority_raw(move, ctx)
        dp_time = (
            machine.schedule_tail if move.start_at == 'schedule_tail'
            else machine.next_runout
        )
        level_q = machine.workcal.get_work_hours_between(
            ctx.earliest_dp_time, dp_time,
        )
        old_q = 1.0 if (
            ctx.new_machine_avail.get(move.item, False) and not machine.is_new
        ) else 0.0

        # (label, kind, raw quantity, weight) for all fourteen components.
        components = [
            ('lateness', 'inventory', lateness_q, w.lateness),
            ('drainage', 'inventory', drainage_q, w.drainage),
            ('carrying', 'inventory', carrying_q, w.carrying),
            ('excess', 'inventory', excess_q, w.excess),
            ('tape_out_single', 'schedule', tos_q, w.tape_out_single),
            ('tape_out_both', 'schedule', tob_q, w.tape_out_both),
            ('style_change', 'schedule', sc_q, w.style_change),
            ('runner_change', 'schedule', rc_q, w.runner_change),
            ('pattern_change', 'schedule', pc_q, w.pattern_change),
            ('idle_time', 'schedule', it_q, w.idle_time),
            ('waste_lbs', 'schedule', wl_q, w.waste_lbs),
            ('priority', 'other', priority_q, w.priority),
            ('level_loading', 'other', level_q, w.level_loading),
            ('old_machine', 'other', old_q, w.old_machine),
        ]

        move_id = debuglog.get_last_pk_val('iteration_log')
        total = 0.0
        for label, kind, raw, weight in components:
            cost = weight * raw
            total += cost
            debuglog.add_row(
                'cost_summary',
                summary_id=f'{move_id}_{label}',
                label=label, kind=kind, raw=raw, cost=cost,
            )
        return total

    # ---- helpers -------------------------------------------------------

    def _cross_cutting_cost(
        self, state: State, move: Move, ctx: ScoringContext,
    ) -> float:
        """Per-move cross-cutting cost: predicted-lateness priority
        sum, level-loading work-hour delta × w.level_loading, and the
        flat old-machine penalty when applicable."""
        w = self._weights
        machine = state.machines[move.machine_id]

        priority_cost = self._priority_cost(move, ctx)

        # Level-loading: work hours between the iteration's earliest DP
        # and this move's DP (pre-idle).
        dp_time = (
            machine.schedule_tail if move.start_at == 'schedule_tail'
            else machine.next_runout
        )
        level_loading_cost = w.level_loading * machine.workcal.get_work_hours_between(
            ctx.earliest_dp_time, dp_time,
        )

        # Old-machine: flat penalty when scheduling a legacy machine
        # while at least one new-machine candidate exists for this item.
        if (ctx.new_machine_avail.get(move.item, False)
                and not machine.is_new):
            old_machine_cost = w.old_machine
        else:
            old_machine_cost = 0.0

        return priority_cost + level_loading_cost + old_machine_cost

    def _priority_raw(
        self, move: Move, ctx: ScoringContext,
    ) -> float:
        """Unweighted priority quantity: the summed `lbs × 2^days_late`
        opportunity-cost shape over the higher-priority regular orders this
        move defers. For each regular order ranked better than the move's own,
        assume a fill time of `max(due_date + 1 day,
        earliest_dp_excluding[move.machine_id])` (falling back to
        `ctx.earliest_dp_time`). Safety orders are skipped — their miss-cost is
        drainage, not lateness. `_priority_cost` is this times `w.priority`.
        See "Priority cost" in DESIGN.md."""
        move_key = OrderKey(
            item_id=move.item.id, week_idx=move.week_idx,
        )
        move_rank = ctx.priorities.get(move_key)
        if move_rank is None:
            # Hand-built moves in tests may not correspond to any
            # eligible order; no anchor for "higher priority than".
            return 0.0

        other_dp = ctx.earliest_dp_excluding.get(
            move.machine_id, ctx.earliest_dp_time,
        )
        one_day = timedelta(days=1)

        lateness_lb_days = 0.0
        for key, rank in ctx.priorities.items():
            if rank >= move_rank:
                continue
            order = ctx.regular_orders_by_key.get(key)
            if order is None:
                # Safety order — skipped (regulars-only scope).
                continue
            fill_time = max(order.due_date + one_day, other_dp)
            days_late = (fill_time - order.due_date) / one_day
            lateness_lb_days += order.lbs * (2.0 ** days_late)

        return lateness_lb_days

    def _priority_cost(
        self, move: Move, ctx: ScoringContext,
    ) -> float:
        """Weighted priority cost: `w.priority × _priority_raw(move, ctx)`."""
        return self._weights.priority * self._priority_raw(move, ctx)

    def _priority_breakdown(
        self, move: Move, ctx: ScoringContext,
    ) -> tuple[float, dict[str, PriorityContribution]]:
        """Same computation as `_priority_cost`, plus a per-item dict
        mapping each item with a higher-priority deferred regular order
        to a `PriorityContribution` carrying its `week_idx`,
        `remaining_lbs`, and weighted contribution. Each item appears
        at most once: the candidate enumerator picks at most one
        regular order per item per iteration, so each item's
        higher-priority counterpart is unique. Used by the verbose
        path; the hot loop stays on the scalar `_priority_cost`."""
        move_key = OrderKey(
            item_id=move.item.id, week_idx=move.week_idx,
        )
        move_rank = ctx.priorities.get(move_key)
        if move_rank is None:
            return 0.0, {}

        other_dp = ctx.earliest_dp_excluding.get(
            move.machine_id, ctx.earliest_dp_time,
        )
        one_day = timedelta(days=1)
        w_priority = self._weights.priority

        total = 0.0
        by_item: dict[str, PriorityContribution] = {}
        for key, rank in ctx.priorities.items():
            if rank >= move_rank:
                continue
            order = ctx.regular_orders_by_key.get(key)
            if order is None:
                continue
            fill_time = max(order.due_date + one_day, other_dp)
            days_late = (fill_time - order.due_date) / one_day
            contribution = w_priority * order.lbs * (2.0 ** days_late)
            total += contribution
            by_item[key.item_id] = PriorityContribution(
                week_idx=order.week_idx,
                remaining_lbs=order.lbs,
                priority=contribution,
            )
        return total, by_item

    # ---- helpers -------------------------------------------------------

    def _record_demand_item(
        self, item_id: str,
        lateness: float, drainage: float, carrying: float, excess: float,
        lateness_by_item: dict[str, float],
        drainage_by_item: dict[str, float],
        carrying_by_item: dict[str, float],
        excess_by_item: dict[str, float],
    ) -> None:
        """Append weighted per-item contributions to the four demand
        dicts, skipping any whose weighted value is zero (so only items
        with a non-zero contribution appear in the breakdown)."""
        w = self._weights
        if (v := w.lateness * lateness) != 0.0:
            lateness_by_item[item_id] = v
        if (v := w.drainage * drainage) != 0.0:
            drainage_by_item[item_id] = v
        if (v := w.carrying * carrying) != 0.0:
            carrying_by_item[item_id] = v
        if (v := w.excess * excess) != 0.0:
            excess_by_item[item_id] = v

    def _schedule_quantities_for(
        self, activities, workcal: 'WorkCal',
    ) -> tuple[float, float, float, float, float, float, float]:
        """Unweighted (tape_out_single, tape_out_both, style_change,
        runner_change, pattern_change, idle_hours, waste_lbs)
        counts/hours/lbs for a sequence of activities. Mirrors
        `_schedule_penalty_for` but returns the seven quantities separately
        so the breakdown methods can apply the weights themselves."""
        tos_q = tob_q = sc_q = rc_q = pc_q = it_q = wl_q = 0.0
        for a in activities:
            if isinstance(a, TapeOut):
                if a.bars == 'both':
                    tob_q += 1
                else:
                    tos_q += 1
            elif isinstance(a, StyleChange):
                sc_q += 1
            elif isinstance(a, RunnerChange):
                rc_q += 1
            elif isinstance(a, PatternChange):
                pc_q += 1
            elif isinstance(a, Idle):
                it_q += workcal.get_work_hours_between(a.start, a.end)
            elif isinstance(a, Waste):
                wl_q += a.lbs
        return tos_q, tob_q, sc_q, rc_q, pc_q, it_q, wl_q

    def _weighted_demand(
        self, lateness: float, drainage: float,
        carrying: float, excess: float,
    ) -> float:
        w = self._weights
        return (w.lateness * lateness
                + w.drainage * drainage
                + w.carrying * carrying
                + w.excess * excess)

    def _schedule_penalty(self, machine) -> float:
        return self._schedule_penalty_for(machine.activities, machine.workcal)

    def _schedule_penalty_for(
        self, activities, workcal: 'WorkCal',
    ) -> float:
        w = self._weights
        total = 0.0
        for a in activities:
            if isinstance(a, TapeOut):
                total += (w.tape_out_both if a.bars == 'both'
                          else w.tape_out_single)
            elif isinstance(a, StyleChange):
                total += w.style_change
            elif isinstance(a, RunnerChange):
                total += w.runner_change
            elif isinstance(a, PatternChange):
                total += w.pattern_change
            elif isinstance(a, Idle):
                # Idle duration is in work hours (set via
                # workcal.offset_work_hours when the activity was created);
                # extracting that back is what get_work_hours_between does.
                work_hours = workcal.get_work_hours_between(a.start, a.end)
                total += w.idle_time * work_hours
            elif isinstance(a, Waste):
                # Zero-duration; the per-lb charge is its only contribution.
                total += w.waste_lbs * a.lbs
        return total
