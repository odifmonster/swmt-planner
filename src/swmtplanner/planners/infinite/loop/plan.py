#!/usr/bin/env python

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from swmtplanner.demand.rlsitem import CostComponents

from swmtplanner.planners.infinite.coordination import build_context
from swmtplanner.planners.infinite.costing import CostBreakdown, Costing
from swmtplanner.planners.infinite.iterlog import (
    IterationLogRecord,
    CostDetailRecord,
    LatenessDetailRecord, DrainageDetailRecord,
    CarryingDetailRecord, ExcessDetailRecord,
    PriorityDetailRecord,
    ScheduleDetailRecord,
    IterLogAccumulators, IterLogCounters,
    build_candidate_records, candidate_sort_key,
)
from swmtplanner.planners.infinite.state import Move, State

from .candidates import enumerate_candidates

if TYPE_CHECKING:
    from swmtplanner.demand.order import RawOrder
    from swmtplanner.schedule import Activity, Job


@dataclass
class PlanReport:
    """Snapshot of a `plan` invocation's output. Bundles the schedules,
    registered jobs, final cost picture, unmet-demand summary, and
    late-order summary so callers can persist or render the result
    without holding the mutable `State` around. The schedules themselves
    also still live on the `Machine` instances inside `state` — this is
    a copy.

    The eight `*_log` / `*_detail` tuples make up the Phase 3 verbose
    audit trail. They are populated only when `plan(..., verbose=True)`
    was called; all eight are `None` for a non-verbose run. Cross-table
    joins use the integer ids on `iteration_log` (`cost_id`, `sched_id`)
    and on `cost_detail` (the five `*_detail_id` FKs)."""
    schedules: dict[str, tuple['Activity', ...]]
    jobs_by_item: dict[str, tuple['Job', ...]]
    total_score: float
    cost_components_by_item: dict[str, CostComponents]
    unmet_lbs_by_item_week: dict[tuple[str, int], float]
    late_orders: tuple['RawOrder', ...]
    iteration_log: tuple[IterationLogRecord, ...] | None = None
    cost_detail: tuple[CostDetailRecord, ...] | None = None
    lateness_detail: tuple[LatenessDetailRecord, ...] | None = None
    drainage_detail: tuple[DrainageDetailRecord, ...] | None = None
    carrying_detail: tuple[CarryingDetailRecord, ...] | None = None
    excess_detail: tuple[ExcessDetailRecord, ...] | None = None
    priority_detail: tuple[PriorityDetailRecord, ...] | None = None
    schedule_detail: tuple[ScheduleDetailRecord, ...] | None = None


def _mk_counter():
    ctr = 0
    def func():
        nonlocal ctr
        ctr += 1
        return ctr
    return func


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
    every candidate is scored with `Costing.cost_breakdown_after_move`
    and a two-level group-then-top-k rule selects up to 16 candidates
    to log per iteration: candidates are grouped by item, items are
    ranked by their lowest-scoring candidate (tie-broken by
    `item_id`), the top 4 items are picked, and each of those items
    contributes its top 4 lowest-scoring candidates (tie-broken by
    `candidate_sort_key`). The committed move is always the
    lowest-scoring candidate of the lowest-scoring item — it is the
    very first row of the iteration block and the only one with
    `role == 'committed'`. Each iteration also captures a baseline
    `CostBreakdown` via `Costing.cost_breakdown(state)`, against
    which the demand-side detail deltas are computed. With
    `verbose=False` (the default) neither breakdown method is called
    and all eight tuples stay `None` — the hot loop is untouched."""
    horizon = _compute_horizon(state)

    move_count = 0
    # Verbose: bundle the eight independent id counters (`_mk_counter`
    # returns a fresh sequence-of-ints closure each call) and a single
    # accumulator container that `build_candidate_records` mutates per
    # candidate.
    accumulators: IterLogAccumulators | None = (
        IterLogAccumulators() if verbose else None
    )
    counters: IterLogCounters | None = (
        IterLogCounters(
            cost_id=_mk_counter(),
            sched_id=_mk_counter(),
            lateness_detail_id=_mk_counter(),
            drainage_detail_id=_mk_counter(),
            carrying_detail_id=_mk_counter(),
            excess_detail_id=_mk_counter(),
            priority_detail_id=_mk_counter(),
        ) if verbose else None
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
            # Verbose path: capture the iteration's baseline once,
            # score every candidate with the full breakdown, then
            # apply the two-level group-then-top-k rule (top 4 items
            # by best score; top 4 candidates per item) to pick up to
            # 16 rows to log. See DESIGN.md "Verbose iteration log".
            baseline = costing.cost_breakdown(state)
            scored = [
                (costing.cost_breakdown_after_move(state, m, ctx), m)
                for m in candidates
            ]
            # Global ordering — drives the score_rank field, the
            # committed-move pick, and the item-grouping insertion
            # order. Ties broken deterministically by
            # candidate_sort_key (item_id → machine_id → start_at
            # with next_runout first).
            scored_sorted = sorted(
                scored,
                key=lambda pair: candidate_sort_key(
                    pair[0].total, pair[1],
                ),
            )
            score_rank_by_id = {
                id(m): i for i, (_, m) in enumerate(scored_sorted)
            }
            # Group by item, preserving the global order so each
            # item's list is already in within-item rank order.
            by_item: dict[
                str, list[tuple[CostBreakdown, Move]]
            ] = {}
            for breakdown, move in scored_sorted:
                by_item.setdefault(move.item.id, []).append(
                    (breakdown, move),
                )
            # Rank items by their best (= first) candidate's score;
            # tie-break by item_id ascending.
            items_in_order = sorted(
                by_item.items(),
                key=lambda kv: (kv[1][0][0].total, kv[0]),
            )
            # Emit records for the top 4 items × top 4 candidates.
            for item_id, item_candidates in items_in_order[:4]:
                for isr, (breakdown, move) in enumerate(
                    item_candidates[:4],
                ):
                    build_candidate_records(
                        iteration_idx=move_count,
                        score_rank=score_rank_by_id[id(move)],
                        item_score_rank=isr,
                        move=move,
                        breakdown=breakdown,
                        baseline=baseline,
                        state=state,
                        accumulators=accumulators,
                        counters=counters,
                    )
            # The committed move is always the global lowest, which
            # is also the top-ranked item's top-ranked candidate.
            best_move = scored_sorted[0][1]
        else:
            # Hot path: scalar score only, pick the min.
            _, best_move = min(
                ((costing.score_after_move(state, m, ctx), m) for m in candidates),
                key=lambda pair: pair[0],
            )
        state.commit_move(best_move)

        move_count += 1

    print()
    return _build_report(state, costing, accumulators)


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
    accumulators: IterLogAccumulators | None = None,
) -> PlanReport:
    """Build a `PlanReport` from the (post-loop) state. Snapshots the
    machines' activity tuples and the rls_items' job tuples; reads the
    final score and per-item cost components from the demand views;
    summarizes whatever remaining `safety_view.orders` still have unmet
    demand.

    `accumulators` is the verbose-path bundle of per-table lists. Pass
    `None` for the standard (non-verbose) run; pass the populated
    bundle to attach all eight verbose tuples to the report."""
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
            tuple(accumulators.iteration_log)
            if accumulators is not None else None
        ),
        cost_detail=(
            tuple(accumulators.cost_detail)
            if accumulators is not None else None
        ),
        lateness_detail=(
            tuple(accumulators.lateness_detail)
            if accumulators is not None else None
        ),
        drainage_detail=(
            tuple(accumulators.drainage_detail)
            if accumulators is not None else None
        ),
        carrying_detail=(
            tuple(accumulators.carrying_detail)
            if accumulators is not None else None
        ),
        excess_detail=(
            tuple(accumulators.excess_detail)
            if accumulators is not None else None
        ),
        priority_detail=(
            tuple(accumulators.priority_detail)
            if accumulators is not None else None
        ),
        schedule_detail=(
            tuple(accumulators.schedule_detail)
            if accumulators is not None else None
        ),
    )