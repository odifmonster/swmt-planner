#!/usr/bin/env python

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from swmtplanner.schedule import Job, TapeOut, StyleChange, Idle

from swmtplanner.planners.infinite.coordination import OrderKey, ScoringContext
from swmtplanner.planners.infinite.state import Move, State

if TYPE_CHECKING:
    from swmtplanner.schedule import Activity
    from swmtplanner.support import WorkCal


@dataclass
class CostWeights:
    """Weights for Phase 1+2 cost scoring. Each component is multiplied
    by its corresponding weight and summed into the state's total score.

    Per-item demand weights apply to the unweighted `CostComponents`
    returned by `RlsItem.cost_if` / the demand views. Per-machine
    schedule weights apply per occurrence (TapeOut, StyleChange) or per
    work-hour (Idle). Phase 2 cross-cutting weights apply per move
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
    family_change: float
    # per-machine schedule weight — per work-hour
    idle_time: float
    # cross-cutting weights (Phase 2)
    priority: float
    level_loading: float
    old_machine: float


@dataclass(frozen=True)
class CostBreakdown:
    """Per-component weighted contributions for a single
    `score_after_move` evaluation. The sum of the eleven fields equals
    `Costing.score_after_move(state, move, ctx)`. Returned by
    `Costing.cost_breakdown_after_move` and consumed by the verbose
    iteration log (Phase 3)."""
    # per-item demand contributions
    lateness: float
    drainage: float
    carrying: float
    excess: float
    # per-machine schedule contributions
    tape_out_single: float
    tape_out_both: float
    family_change: float
    idle_time: float
    # cross-cutting contributions
    priority: float
    level_loading: float
    old_machine: float

    @property
    def total(self) -> float:
        return (
            self.lateness + self.drainage + self.carrying + self.excess
            + self.tape_out_single + self.tape_out_both
            + self.family_change + self.idle_time
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
    mutate `state`. `ctx` is required."""

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
    ) -> float:
        """Score the state as if `move` were committed. Pure — does not
        mutate `state`. Internally uses `RlsItem.cost_if(jobs)` for the
        item(s) the move's plan touches, and reads the current view
        trackers for everything else. Schedule penalties for the
        affected machine combine its existing activities with the plan's;
        other machines use their current counts. Adds the move's
        cross-cutting contributions (priority, level-loading,
        old-machine) read off `ctx`."""
        # Group plan's Jobs by their item.id. Multiple items can appear
        # in a single plan (the 'next_runout' run-up may add Jobs of the
        # current item ahead of the new item's production).
        jobs_by_item: dict[str, list[Job]] = {}
        for a in move.plan:
            if isinstance(a, Job):
                jobs_by_item.setdefault(a.item.id, []).append(a)

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
                    list(machine.activities) + list(move.plan),
                    machine.workcal,
                )
            else:
                total += self._schedule_penalty(machine)

        # Cross-cutting per-move contributions (Phase 2).
        total += self._cross_cutting_cost(state, move, ctx)
        return total

    def cost_breakdown_after_move(
        self, state: State, move: Move, ctx: ScoringContext,
    ) -> CostBreakdown:
        """Same total as `score_after_move`, returned as one weighted
        scalar per component. Pure — does not mutate `state`. Used by
        the verbose iteration log; the hot loop sticks with the scalar
        `score_after_move` because it avoids the `CostBreakdown`
        allocation."""
        # Demand: aggregate unweighted quantities across rls_items,
        # using cost_if for items touched by move.plan and current
        # views for the rest.
        jobs_by_item: dict[str, list[Job]] = {}
        for a in move.plan:
            if isinstance(a, Job):
                jobs_by_item.setdefault(a.item.id, []).append(a)
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

        # Schedule: aggregate unweighted counts / hours across
        # machines, combining the affected machine's activities with
        # the move's plan.
        tos_q = tob_q = fc_q = it_q = 0.0
        for machine_id, machine in state.machines.items():
            if machine_id == move.machine_id:
                activities = list(machine.activities) + list(move.plan)
            else:
                activities = machine.activities
            for a in activities:
                if isinstance(a, TapeOut):
                    if a.bars == 'both':
                        tob_q += 1
                    else:
                        tos_q += 1
                elif isinstance(a, StyleChange):
                    if a.is_family_change:
                        fc_q += 1
                elif isinstance(a, Idle):
                    it_q += machine.workcal.get_work_hours_between(
                        a.start, a.end,
                    )

        # Cross-cutting.
        move_machine = state.machines[move.machine_id]
        priority_cost = self._priority_cost(move, ctx)
        dp_time = (
            move_machine.next_job_end
            if move.start_at == 'next_job_end'
            else move_machine.next_runout
        )
        work_hours_delta = move_machine.workcal.get_work_hours_between(
            ctx.earliest_dp_time, dp_time,
        )
        old_machine_applies = (
            ctx.new_machine_avail.get(move.item, False)
            and not move_machine.is_new
        )

        w = self._weights
        return CostBreakdown(
            lateness=w.lateness * lateness_q,
            drainage=w.drainage * drainage_q,
            carrying=w.carrying * carrying_q,
            excess=w.excess * excess_q,
            tape_out_single=w.tape_out_single * tos_q,
            tape_out_both=w.tape_out_both * tob_q,
            family_change=w.family_change * fc_q,
            idle_time=w.idle_time * it_q,
            priority=priority_cost,
            level_loading=w.level_loading * work_hours_delta,
            old_machine=(
                w.old_machine if old_machine_applies else 0.0
            ),
        )

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
            machine.next_job_end if move.start_at == 'next_job_end'
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

    def _priority_cost(
        self, move: Move, ctx: ScoringContext,
    ) -> float:
        """Weighted priority cost — an opportunity-cost estimate of
        the lateness this move would incur on higher-priority regular
        orders the planner is deferring. For each regular order with a
        better rank than the move's own, charge the standard
        `lbs × 2^days_late` shape assuming a fill time of
        `max(due_date + 1 day, earliest_dp_excluding[move.machine_id])`
        (falling back to `ctx.earliest_dp_time` when no other machine
        has a candidate). Safety orders are skipped — their miss-cost
        is drainage, not lateness. See "Priority cost" in DESIGN.md."""
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

        return self._weights.priority * lateness_lb_days

    # ---- helpers -------------------------------------------------------

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
                if a.is_family_change:
                    total += w.family_change
            elif isinstance(a, Idle):
                # Idle duration is in work hours (set via
                # workcal.offset_work_hours when the activity was created);
                # extracting that back is what get_work_hours_between does.
                work_hours = workcal.get_work_hours_between(a.start, a.end)
                total += w.idle_time * work_hours
        return total
