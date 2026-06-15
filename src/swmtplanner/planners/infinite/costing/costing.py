#!/usr/bin/env python

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from swmtplanner.schedule import (
    Job, TapeOut, StyleChange, RunnerChange, PatternChange, Idle, Waste,
)

from swmtplanner.planners.infinite.coordination import OrderKey, ScoringContext
from swmtplanner.planners.infinite.report import _activity_desc
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
    mutate `state`. `ctx` is required. When given a `debuglog`, it also
    writes the per-component breakdown to the log's tables (see
    `debuglog/DESIGN.md`); the hot scoring loop skips that bookkeeping."""

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

    def _emit_cost_summary(
        self, debuglog: 'DebugLog', state: State, move: Move,
        ctx: ScoringContext,
    ) -> float:
        """Compute the move's per-component breakdown, write one
        `cost_summary` row per component — keyed `{move_id}_{label}` and linked
        (FK) to the current `iteration_log` row — and return the same total
        `score_after_move` would. Each row carries the component's `raw`
        (unweighted) quantity and weighted `cost`. Also writes the
        `sched_cost_detail`, `inv_cost_detail`, and `priority_detail` leaf
        rows. See debuglog/DESIGN.md."""
        w = self._weights
        move_id = debuglog.get_last_pk_val('iteration_log')

        # Per-window `inv_cost_detail` sink: the demand views report each
        # lateness / drainage / carrying / excess window (with its unweighted
        # `contribution`); we weight it and write the row. Linked to its
        # `cost_summary` parent by `summary_id`; `icost_id` (PK) and `move_id`
        # (FK) auto-fill. The rows for a given label sum to its cost_summary
        # `cost`.
        inv_weight = {
            'lateness': w.lateness, 'drainage': w.drainage,
            'carrying': w.carrying, 'excess': w.excess,
        }

        def inv_sink(label, item_id, days, qty, contribution):
            debuglog.add_row(
                'inv_cost_detail',
                summary_id=f'{move_id}_{label}',
                label=label, item=item_id, days=days, qty=qty,
                weight=inv_weight[label],
                value=inv_weight[label] * contribution,
            )

        # Demand quantities, summed across items — every item runs through
        # cost_if (with no extra jobs for the ones the plan doesn't touch) so
        # its windows are emitted; the returned scalars are the same as the
        # hot path's cost_if / view-tracker mix.
        jobs_by_item: dict[str, list[Job]] = {}
        for job in move.plan.jobs:
            jobs_by_item.setdefault(job.item.id, []).append(job)
        lateness_q = drainage_q = carrying_q = excess_q = 0.0
        for item_id, rls in state.rls_items.items():
            cc = rls.cost_if(jobs_by_item.get(item_id, []), inv_sink)
            lateness_q += cc.lateness
            drainage_q += cc.drainage
            carrying_q += cc.carrying
            excess_q += cc.excess

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
        # work-hour delta, old-machine flag). Passing `debuglog` also emits the
        # per-deferred-order `priority_detail` rows.
        machine = state.machines[move.machine_id]

        # Per-activity schedule breakdown for this candidate's plan.
        self._emit_sched_cost_detail(debuglog, move, machine)

        priority_q = self._priority_raw(move, ctx, debuglog)
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

    def _emit_sched_cost_detail(
        self, debuglog: 'DebugLog', move: Move, machine,
    ) -> None:
        """Write one `sched_cost_detail` row per activity in the move's plan
        (all on `move.machine_id`). Weighted activity types carry their `weight`
        and weighted `cost`; cost-free types (`Knit` / `Doff` / `Hanging` /
        `Threading`) leave both blank (`None`). The `activity_id` PK is the
        activity's own id (globally unique across plans); the `move_id` FK
        auto-links to the current `iteration_log` row. This is a per-candidate
        activity ledger — it links only by `move_id` and does not sum to any
        `cost_summary` row. See debuglog/DESIGN.md."""
        for a in move.plan.activities:
            weight, cost = self._activity_weight_cost(a, machine.workcal)
            debuglog.add_row(
                'sched_cost_detail',
                activity_id=a.id,
                machine=move.machine_id,
                start=a.start,
                end=a.end,
                desc=_activity_desc(a),
                weight=weight,
                cost=cost,
            )

    def _activity_weight_cost(
        self, a: 'Activity', workcal: 'WorkCal',
    ) -> tuple[float | None, float | None]:
        """`(weight, cost)` for one activity. Weighted types return their weight
        and weighted cost (`weight × quantity`); cost-free types return
        `(None, None)` so both cells render blank. A weighted type whose weight
        is `0` still returns `(0.0, 0.0)` — distinguishing a zero-valued cost
        from no cost concept at all. Mirrors `_schedule_penalty_for`'s
        per-activity charge."""
        w = self._weights
        if isinstance(a, TapeOut):
            weight = w.tape_out_both if a.bars == 'both' else w.tape_out_single
            return weight, weight
        if isinstance(a, StyleChange):
            return w.style_change, w.style_change
        if isinstance(a, RunnerChange):
            return w.runner_change, w.runner_change
        if isinstance(a, PatternChange):
            return w.pattern_change, w.pattern_change
        if isinstance(a, Idle):
            hours = workcal.get_work_hours_between(a.start, a.end)
            return w.idle_time, w.idle_time * hours
        if isinstance(a, Waste):
            return w.waste_lbs, w.waste_lbs * a.lbs
        return None, None

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
        debuglog: 'DebugLog | None' = None,
    ) -> float:
        """Unweighted priority quantity: the summed `lbs × 2^days_late`
        opportunity-cost shape over the higher-priority regular orders this
        move defers. For each regular order ranked better than the move's own,
        assume a fill time of `max(due_date + 1 day,
        earliest_dp_excluding[move.machine_id])` (falling back to
        `ctx.earliest_dp_time`). Safety orders are skipped — their miss-cost is
        drainage, not lateness. `_priority_cost` is this times `w.priority`.
        See "Priority cost" in DESIGN.md.

        When `debuglog` is given, one `priority_detail` row is written per
        deferred order (its `cost` is the weighted contribution; the `move_id`
        FK auto-links to the current `iteration_log` row)."""
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
        w_priority = self._weights.priority

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
            contribution = order.lbs * (2.0 ** days_late)
            lateness_lb_days += contribution
            if debuglog is not None:
                debuglog.add_row(
                    'priority_detail',
                    item=key.item_id,
                    week_idx=order.week_idx,
                    remaining_lbs=order.lbs,
                    late_day=days_late,
                    weight=w_priority,
                    cost=w_priority * contribution,
                )

        return lateness_lb_days

    def _priority_cost(
        self, move: Move, ctx: ScoringContext,
    ) -> float:
        """Weighted priority cost: `w.priority × _priority_raw(move, ctx)`."""
        return self._weights.priority * self._priority_raw(move, ctx)

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
