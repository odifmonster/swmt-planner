#!/usr/bin/env python

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TYPE_CHECKING

from swmtplanner.demand.rlsitem import CostComponents

from swmtplanner.planners.infinite.coordination import build_context
from swmtplanner.planners.infinite.costing import CostBreakdown, Costing
from swmtplanner.planners.infinite.state import Move, State

from .candidates import enumerate_candidates

if TYPE_CHECKING:
    from swmtplanner.demand.order import RawOrder
    from swmtplanner.schedule import Activity, Job


@dataclass(frozen=True)
class IterationLogRecord:
    """One row in the verbose iteration audit log (Phase 3). Each row
    represents one scored candidate in one main-loop iteration —
    either the committed move (`role == 'committed'`, `score_rank ==
    0`) or one of the next-lowest-scoring rejected candidates
    (`role == 'rejected'`, `score_rank` ∈ {1, 2, 3}). The eleven
    cost-component fields are the same weighted contributions
    `CostBreakdown` carries; `total_score` equals their sum and
    matches `Costing.score_after_move(state, move, ctx)` for the
    candidate."""
    iteration_idx: int
    role: Literal['committed', 'rejected']
    score_rank: int
    # candidate identity
    item_id: str
    target_type: Literal['regular', 'safety']
    target_week: int | None
    machine_id: str
    machine_is_new: bool
    start_at: Literal['next_job_end', 'next_runout']
    idle_hours: float
    # cost breakdown
    total_score: float
    lateness: float
    drainage: float
    carrying: float
    excess: float
    tape_out_single: float
    tape_out_both: float
    family_change: float
    idle_time: float
    priority: float
    level_loading: float
    old_machine: float


def build_iteration_log_record(
    iteration_idx: int,
    rank: int,
    move: Move,
    breakdown: CostBreakdown,
    state: State,
) -> IterationLogRecord:
    """Assemble one `IterationLogRecord` from a scored candidate.

    `rank` is the candidate's position in the iteration's score
    ordering (0 = lowest score = the committed move; 1, 2, 3 = the
    next-lowest-scoring rejected candidates). `machine_is_new` is
    read from `state.machines[move.machine_id]`, and `idle_hours`
    converts `move.idle_for` to a float for the TSV."""
    machine = state.machines[move.machine_id]
    return IterationLogRecord(
        iteration_idx=iteration_idx,
        role='committed' if rank == 0 else 'rejected',
        score_rank=rank,
        item_id=move.item.id,
        target_type='safety' if move.week_idx is None else 'regular',
        target_week=move.week_idx,
        machine_id=move.machine_id,
        machine_is_new=machine.is_new,
        start_at=move.start_at,
        idle_hours=move.idle_for.total_seconds() / 3600.0,
        total_score=breakdown.total,
        lateness=breakdown.lateness,
        drainage=breakdown.drainage,
        carrying=breakdown.carrying,
        excess=breakdown.excess,
        tape_out_single=breakdown.tape_out_single,
        tape_out_both=breakdown.tape_out_both,
        family_change=breakdown.family_change,
        idle_time=breakdown.idle_time,
        priority=breakdown.priority,
        level_loading=breakdown.level_loading,
        old_machine=breakdown.old_machine,
    )


@dataclass
class PlanReport:
    """Snapshot of a `plan` invocation's output. Bundles the schedules,
    registered jobs, final cost picture, unmet-demand summary, and
    late-order summary so callers can persist or render the result
    without holding the mutable `State` around. The schedules themselves
    also still live on the `Machine` instances inside `state` — this is
    a copy.

    `iteration_log` is the Phase 3 verbose audit trail: a tuple of
    `IterationLogRecord`s when `plan(..., verbose=True)` was called,
    `None` otherwise."""
    schedules: dict[str, tuple['Activity', ...]]
    jobs_by_item: dict[str, tuple['Job', ...]]
    total_score: float
    cost_components_by_item: dict[str, CostComponents]
    unmet_lbs_by_item_week: dict[tuple[str, int], float]
    late_orders: tuple['RawOrder', ...]
    iteration_log: tuple[IterationLogRecord, ...] | None = None


def plan(
    state: State, costing: Costing, *, verbose: bool = False,
) -> PlanReport:
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
    result.

    `verbose` opts into the Phase 3 iteration audit log. When True,
    every candidate is scored with `Costing.cost_breakdown_after_move`,
    the pool is sorted by total score, and the top 4 entries (or all
    of them, if the pool has fewer than 4) become
    `IterationLogRecord`s on `PlanReport.iteration_log`. With
    `verbose=False` (the default) the breakdown method is never
    called and `iteration_log` stays `None` — the hot loop is
    untouched."""
    horizon = _compute_horizon(state)

    move_count = 0
    iteration_log: list[IterationLogRecord] | None = (
        [] if verbose else None
    )

    while True:
        print(f'Total moves committed: {move_count}', end='\r')
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

        # Build the per-iteration scoring context (priorities, earliest
        # DP time, new-machine availability) once before scoring.
        ctx = build_context(state, candidates)

        if verbose:
            # Verbose path: score every candidate with the full
            # breakdown, sort ascending by total score, log the top 4
            # (committed + up to 3 next-lowest rejected).
            scored = sorted(
                (
                    (costing.cost_breakdown_after_move(state, m, ctx), m)
                    for m in candidates
                ),
                key=lambda pair: pair[0].total,
            )
            for rank, (breakdown, move) in enumerate(scored[:4]):
                iteration_log.append(build_iteration_log_record(
                    iteration_idx=move_count,
                    rank=rank,
                    move=move,
                    breakdown=breakdown,
                    state=state,
                ))
            best_move = scored[0][1]
        else:
            # Hot path: scalar score only, pick the min.
            _, best_move = min(
                ((costing.score_after_move(state, m, ctx), m) for m in candidates),
                key=lambda pair: pair[0],
            )
        state.commit_move(best_move)

        move_count += 1

    print()
    return _build_report(state, costing, iteration_log)


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


def _build_report(
    state: State,
    costing: Costing,
    iteration_log: list[IterationLogRecord] | None = None,
) -> PlanReport:
    """Build a `PlanReport` from the (post-loop) state. Snapshots the
    machines' activity tuples and the rls_items' job tuples; reads the
    final score and per-item cost components from the demand views;
    summarizes whatever remaining `safety_view.orders` still have unmet
    demand.

    `iteration_log` is the per-iteration audit trail accumulated by
    the verbose path. Pass `None` for the standard (non-verbose) run;
    pass an accumulated list to attach it to the report as a tuple."""
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
        late_orders=tuple(
            order
            for r in state.rls_items.values()
            for order in r.raw_view.orders
            if order.late_lbs > 0
        ),
        iteration_log=(
            tuple(iteration_log) if iteration_log is not None else None
        ),
    )