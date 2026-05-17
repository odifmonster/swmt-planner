#!/usr/bin/env python

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from swmtplanner.demand.rlsitem import CostComponents

from swmtplanner.planners.infinite.costing import Costing
from swmtplanner.planners.infinite.state import State

from .candidates import enumerate_candidates

if TYPE_CHECKING:
    from swmtplanner.schedule import Activity, Job


@dataclass
class PlanReport:
    """Snapshot of a `plan` invocation's output. Bundles the schedules,
    registered jobs, final cost picture, and unmet-demand summary so
    callers can persist or render the result without holding the
    mutable `State` around. The schedules themselves also still live on
    the `Machine` instances inside `state` — this is a copy."""
    schedules: dict[str, tuple['Activity', ...]]
    jobs_by_item: dict[str, tuple['Job', ...]]
    total_score: float
    cost_components_by_item: dict[str, CostComponents]
    unmet_lbs_by_item_week: dict[tuple[str, int], float]


def plan(state: State, costing: Costing) -> PlanReport:
    """Greedy planner. Iterates enumerate → score → commit-lowest,
    advancing the decision window as needed to keep the candidate pool
    at or above `state.candidate_threshold` (up to a horizon computed
    from the rls_items' latest due_date plus
    `state.planning_horizon_buffer`).

    Terminates only when no candidates remain — even after advancing
    the window to the horizon. The greedy commits *every* move that's
    available; there is no "best must improve" check, because committing
    demand reliably is more important than minimizing the score at any
    one iteration. The score serves only as a tie-breaker among
    eligible candidates within an iteration.

    Mutates `state` in place (each chosen move is committed via
    `state.commit_move`) and returns a `PlanReport` summarizing the
    result."""
    horizon = _compute_horizon(state)

    while True:
        candidates = enumerate_candidates(state)
        # Advance the window as needed: when below threshold AND the
        # window hasn't reached the horizon, ask for more decisions.
        while (
            len(candidates) < state.candidate_threshold
            and state.window_end < horizon
        ):
            state.advance_window()
            candidates = enumerate_candidates(state)

        # Terminate when nothing more is eligible — even after the
        # window has been pushed to the horizon.
        if not candidates:
            break

        # Pick the lowest-scoring candidate (score is the tie-breaker)
        # and commit. No "must improve" check.
        _, best_move = min(
            ((costing.score_after_move(state, m), m) for m in candidates),
            key=lambda pair: pair[0],
        )
        state.commit_move(best_move)

    return _build_report(state, costing)


def _compute_horizon(state: State) -> datetime:
    """The right-edge cutoff for window advancement. Defined as the
    latest `due_date` across all rls_items plus
    `state.planning_horizon_buffer`. Falls back to
    `start_date + planning_horizon_buffer` when no rls_items are
    present (an unusual case — included for robustness)."""
    if not state.rls_items:
        return state.start_date + state.planning_horizon_buffer
    latest_due = max(
        order.week.due_date
        for rls in state.rls_items.values()
        for order in rls.safety_view.orders
    )
    return latest_due + state.planning_horizon_buffer


def _build_report(state: State, costing: Costing) -> PlanReport:
    """Build a `PlanReport` from the (post-loop) state. Snapshots the
    machines' activity tuples and the rls_items' job tuples; reads the
    final score and per-item cost components from the demand views;
    summarizes whatever remaining `safety_view.orders` still have unmet
    demand."""
    return PlanReport(
        schedules={
            m_id: m.activities for m_id, m in state.machines.items()
        },
        jobs_by_item={
            item_id: r.jobs for item_id, r in state.rls_items.items()
        },
        total_score=costing.score(state),
        cost_components_by_item={
            item_id: CostComponents(
                lateness=r.raw_view.lateness,
                drainage=r.safety_view.drainage,
                carrying=r.safety_view.carrying,
                excess=r.safety_view.excess,
            )
            for item_id, r in state.rls_items.items()
        },
        unmet_lbs_by_item_week={
            (item_id, order.week.week_idx): order.remaining_lbs
            for item_id, r in state.rls_items.items()
            for order in r.safety_view.orders
            if order.remaining_lbs > 0
        },
    )
