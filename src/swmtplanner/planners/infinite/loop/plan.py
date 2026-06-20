#!/usr/bin/env python

from dataclasses import dataclass, fields
from datetime import datetime
from typing import TYPE_CHECKING

from swmtplanner.demand.rlsitem import CostComponents, RlsItem

from swmtplanner.planners.infinite.coordination import build_context
from swmtplanner.planners.infinite.costing import Costing
from swmtplanner.planners.infinite.report import (
    demand_dataframe, unmet_demand_dataframe,
)
from swmtplanner.planners.infinite.state import State

from .candidates import enumerate_candidates

if TYPE_CHECKING:
    from swmtplanner.demand.order import RawOrder
    from swmtplanner.schedule import Activity, Job
    from swmtplanner.debuglog import DebugLog
    from swmtplanner.planners.infinite.state import Move


@dataclass
class PlanReport:
    """Snapshot of a `plan` invocation's output. Bundles the schedules,
    registered jobs, final cost picture, unmet-demand summary,
    late-order summary, and the input demand (`rls_items`, which also
    carry each item's post-plan views and `roll_order_links`) so callers
    can persist or render the result without holding the mutable `State`
    around. The schedules themselves also still live on the `Machine`
    instances inside `state` — this is a copy.

    The verbose audit trail is no longer reconstructed onto the report:
    when a run wants it, the planner populates a `DebugLog` live as it runs
    (see `debuglog/DESIGN.md`), so `PlanReport` carries only the finished
    plan snapshot."""
    schedules: dict[str, tuple['Activity', ...]]
    jobs_by_item: dict[str, tuple['Job', ...]]
    total_score: float
    cost_components_by_item: dict[str, CostComponents]
    unmet_lbs_by_item_week: dict[tuple[str, int], float]
    late_orders: tuple['RawOrder', ...]
    rls_items: dict[str, RlsItem]


def plan(
    state: State, costing: Costing, *, debuglog: 'DebugLog | None' = None,
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

    `debuglog` is an optional `DebugLog` (its tables already configured by the
    caller — see `run.py`'s `_build_debug_log`). When present, the planner takes
    a debug scoring path that populates the log as it runs: `iteration_log` and
    `cost_summary` (plus the `inv_cost_detail` / `sched_cost_detail` /
    `priority_detail` leaf tables and the per-`Knit` `production` table) are
    written live per candidate, and the post-hoc `demand` / `unmet_demand`
    copies are written once from the finished report. When absent, the hot path
    (scalar score, pick the min) runs and nothing is logged. (The old
    `verbose`-flag audit reconstruction stays divorced; the `PlanReport` detail
    tuples remain `None`.)"""
    horizon = _compute_horizon(state)

    if debuglog is not None:
        _emit_run_configs(debuglog, state, costing)

    move_count = 0

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

        if debuglog is None:
            # Hot path: scalar score only, pick the min.
            _, best_move = min(
                ((costing.score_after_move(state, m, ctx), m)
                 for m in candidates),
                key=lambda pair: pair[0],
            )
        else:
            # Debug path: record this iteration's window/reference-week state
            # (parent of the iteration_log rows), then score and rank the full
            # candidate list, writing each to `iteration_log` (and, via
            # score_after_move, `cost_summary`).
            debuglog.add_row(
                'iteration_states', iteration_idx=move_count,
                window_end=state.window_end,
                reference_week=state.reference_week_idx,
            )
            best_move = _log_iteration(
                debuglog, state, costing, ctx, candidates, move_count,
            )
        state.commit_move(best_move)

        move_count += 1

    print()
    report = _build_report(state, costing)
    if debuglog is not None:
        _emit_demand_tables(debuglog, report)
    return report


def _targeted_order_id(move: 'Move') -> str | None:
    """The id of the order this move targets — its new-item `Job`'s
    `tgt_order`. (A `'next_runout'` run-up `Job`, if present, carries `None`;
    the new-item `Job` carries the order id.)"""
    return next(
        (job.tgt_order for job in move.plan.jobs if job.tgt_order is not None),
        None,
    )


def _log_iteration(
    debuglog: 'DebugLog', state: State, costing: Costing,
    ctx, candidates: list['Move'], iteration_idx: int,
) -> 'Move':
    """Score and rank every candidate, writing one `iteration_log` row each,
    and return the committed move (lowest total cost). The known-at-emit fields
    are written by `add_row` (which mints `move_id`); `rank` / `role` /
    `total_cost` are patched in via `update_row` once the candidates are sorted.
    Each candidate's `iteration_log` row is minted first (via `add_row`), then
    `score_after_move` is called *with* the log so its `cost_summary` rows link
    to that row's `move_id` (read back via `get_last_pk_val`)."""
    scored: list[tuple[float, object, 'Move']] = []
    for move in candidates:
        move_id = debuglog.add_row(
            'iteration_log',
            iteration_idx=iteration_idx,
            order_id=_targeted_order_id(move),
            order_remaining_lbs=move.order_remaining_lbs,
            machine=move.machine_id,
            decision_point=move.start_at,
        )
        _emit_production(debuglog, move)
        total = costing.score_after_move(state, move, ctx, debuglog=debuglog)
        scored.append((total, move_id, move))

    # Lowest total cost first; the committed move is rank 0. A stable sort
    # keeps the first-encountered candidate ahead on ties, matching the
    # hot path's `min`.
    scored.sort(key=lambda s: s[0])
    for rank, (total, move_id, move) in enumerate(scored):
        debuglog.update_row(
            'iteration_log', move_id,
            rank=rank,
            total_cost=total,
            role='committed' if rank == 0 else 'rejected',
        )
    return scored[0][2]


# State tuning knobs recorded in `run_configs` (kind='state'): the timedelta
# ones are stored in hours, the rest as their scalar value.
_STATE_CFG_HOURS = (
    'window_advance_amount', 'carrying_avoidance_margin',
    'planning_horizon_buffer',
)
_STATE_CFG_SCALAR = (
    'candidate_threshold', 'reference_week_idx', 'reference_advance_amount',
    'reference_threshold',
)


def _emit_run_configs(
    debuglog: 'DebugLog', state: State, costing: Costing,
) -> None:
    """Write this run's configuration to `run_configs` once, before the loop:
    one `kind='cost'` row per `CostWeights` field, and one `kind='state'` row per
    tuneable `State` knob (timedelta knobs recorded in **hours**). The
    `(kind, label)` pair is the table's composite primary key."""
    weights = costing.weights
    for f in fields(weights):
        debuglog.add_row(
            'run_configs', kind='cost', label=f.name,
            value=float(getattr(weights, f.name)),
        )
    for label in _STATE_CFG_SCALAR:
        debuglog.add_row(
            'run_configs', kind='state', label=label,
            value=float(getattr(state, label)),
        )
    for label in _STATE_CFG_HOURS:
        td = getattr(state, label)
        debuglog.add_row(
            'run_configs', kind='state', label=label,
            value=td.total_seconds() / 3600.0,
        )


def _emit_production(debuglog: 'DebugLog', move: 'Move') -> None:
    """Write one `production` row per `Knit` across the move's plan jobs
    (`move.plan.jobs` → `Roll.knits`), spanning the candidate's whole plan
    whether or not it is committed. `roll_id` is synthesized as
    `f'{job_id}_{roll_index}'` (a `Roll` has no id of its own), so a roll
    straddling a beam swap has its two knits sharing one `roll_id`. The
    `knit_id` PK is the `Knit`'s own id (globally unique across plans); the
    `move_id` FK auto-links to the current `iteration_log` row. See
    debuglog/DESIGN.md."""
    for job in move.plan.jobs:
        for roll_idx, roll in enumerate(job.rolls):
            roll_id = f'{job.id}_{roll_idx}'
            for knit in roll.knits:
                debuglog.add_row(
                    'production',
                    knit_id=knit.id,
                    roll_id=roll_id,
                    job_id=job.id,
                    item=knit.item.id,
                    start=knit.start,
                    end=knit.end,
                    lbs=knit.lbs,
                )


def _emit_demand_tables(debuglog: 'DebugLog', report: PlanReport) -> None:
    """Populate the two post-hoc output tables from the finished `report` —
    faithful copies of the regular Excel output's `demand` / `unmet_demand`
    sheets, built via `report.py`'s dataframe builders so they match the
    regular output column-for-column. Unlike the loop-populated tables these
    are snapshots of the final plan, so they are written once after the loop.
    `demand`'s `order_id` is its (non-auto) primary key — unique per
    order/safety across items; `unmet_demand` is key-less. The
    `iteration_log.order_id → demand.order_id` FK resolves now that `demand`
    exists (FK existence isn't checked at insert, so building it last is fine).
    """
    for row in demand_dataframe(report).itertuples(index=False):
        debuglog.add_row(
            'demand',
            order_id=row.order_id,
            item=row.item,
            due_date=row.due_date,
            demand=row.demand,
            covered_on_hand=row.covered_on_hand,
            remaining=row.remaining,
        )
    for row in unmet_demand_dataframe(report).itertuples(index=False):
        debuglog.add_row(
            'unmet_demand',
            item=row.item,
            week_idx=row.week_idx,
            unmet_lbs=row.unmet_lbs,
        )


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
        late_orders=tuple(
            order
            for r in state.rls_items.values()
            for order in r.raw_view.orders
            if order.late_lbs > 0
        ),
        rls_items=dict(state.rls_items),
    )