#!/usr/bin/env python

from dataclasses import dataclass
from typing import TYPE_CHECKING

from swmtplanner.schedule import Job, TapeOut, StyleChange, Idle

from swmtplanner.planners.infinite.state import Move, State

if TYPE_CHECKING:
    from swmtplanner.schedule import Activity
    from swmtplanner.support import WorkCal


@dataclass
class CostWeights:
    """Weights for Phase 1 cost scoring. Each component is multiplied by
    its corresponding weight and summed into the state's total score.

    Per-item demand weights apply to the unweighted `CostComponents`
    returned by `RlsItem.cost_if` / the demand views. Per-machine
    schedule weights apply per occurrence (TapeOut, StyleChange) or per
    work-hour (Idle). Phase 2+ will add cross-cutting aggregate
    weights; those are not part of this dataclass yet."""
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


class Costing:
    """Combines per-item demand costs and per-machine schedule penalties
    into a single scalar `score(state)`. The `score_after_move(state,
    move)` variant returns the same number computed against the
    hypothetical post-commit state — pure, no mutation."""

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

    def score_after_move(self, state: State, move: Move) -> float:
        """Score the state as if `move` were committed. Pure — does not
        mutate `state`. Internally uses `RlsItem.cost_if(jobs)` for the
        item(s) the move's plan touches, and reads the current view
        trackers for everything else. Schedule penalties for the
        affected machine combine its existing activities with the plan's;
        other machines use their current counts."""
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
        return total

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
