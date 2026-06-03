#!/usr/bin/env python

"""Verbose iteration log — record types and the per-candidate factory.

The verbose path of `plan(..., verbose=True)` (Phase 3) produces a small
relational schema of records. `IterationLogRecord` is the headline row,
one per scored candidate; the seven detail record types below carry the
full weighted cost breakdown, per-item demand-cost deltas, per-item
priority attribution, and the candidate's activity plan. Each scored
candidate emits one row in `iteration_log` and `cost_detail` plus
zero-or-more rows in each detail table (zero when the corresponding
cost has no contributing items).

Cross-table joins use a mix of auto-incremented counters and
denormalized identity columns. `cost_id`, `sched_id`, and the five
`*_detail_id`s are auto-incremented counters owned by the loop,
each starting at 1 at the beginning of a verbose run. A
`*_detail_id` on `CostDetailRecord` is `None` when its detail
group has no rows (no non-zero deltas for the demand-side costs;
no higher-priority skipped orders for priority).

Two cross-table keys are *not* fresh counters. `activity_id` on
`ScheduleDetailRecord` is the underlying `Activity`'s stable id
(e.g. `"JOB00001"`), shared with the workbook's `schedule` sheet
so the dashboard can drill from a scheduled activity into its
schedule_detail row. `move_id` appears on both
`IterationLogRecord` and `ScheduleDetailRecord` and always equals
the row's (or the row's candidate's) `cost_id` — the shared
column name is the "backward" join that follows an activity back
to the move that scheduled it, distinct from `cost_id`'s
"forward" role as the FK into `cost_detail`.

The four demand-side detail tables (`LatenessDetailRecord`,
`DrainageDetailRecord`, `CarryingDetailRecord`, `ExcessDetailRecord`)
hold *deltas* vs the iteration's baseline. The priority detail table
(`PriorityDetailRecord`) holds *absolute* per-item contributions — the
baseline has no priority cost to subtract from, and the per-item
attribution exposes which higher-priority orders the move is deferring.

See DESIGN.md's "Verbose iteration log" section for the consumer side
(the eight TSVs the CLI writes)."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Literal, TYPE_CHECKING

from swmtplanner.schedule import (
    Job, Waste, TapeOut, BeamLoad, StyleChange, Idle,
)

from swmtplanner.planners.infinite.costing import CostBreakdown
from swmtplanner.planners.infinite.state import Move, State

if TYPE_CHECKING:
    from swmtplanner.schedule import Activity


# ---- Headline row -------------------------------------------------------

@dataclass(frozen=True)
class IterationLogRecord:
    """One row in the verbose iteration audit log (Phase 3). Each row
    represents one logged candidate in one main-loop iteration.

    The verbose loop logs up to 16 candidates per iteration via a
    two-level group-then-top-k rule (see DESIGN.md): candidates are
    grouped by item, items are ranked by their lowest-scoring
    candidate, and the top 4 items each contribute their top 4
    lowest-scoring candidates. The committed move is always the
    lowest-scoring candidate of the lowest-scoring item; it is the
    only row with `score_rank == 0` and `item_score_rank == 0`, and
    is therefore the only row with `role == 'committed'`. All other
    logged rows are `'rejected'`.

    `score_rank` is the candidate's position across **all** scored
    candidates in the iteration (so values may be sparse — a logged
    runner-up item's top candidate has `item_score_rank == 0` but a
    `score_rank` reflecting how many other candidates outscored it
    globally). `item_score_rank` is the position within the
    candidate's item.

    `total_score` equals `Costing.score_after_move(state, move, ctx)`
    for the candidate and matches `cost_detail[cost_id].total`. The
    full weighted cost breakdown lives in `CostDetailRecord` (joined
    on `cost_id`); the candidate's activity plan lives in
    `ScheduleDetailRecord`s (joined on `sched_id`). Both ids are
    allocated by the loop from independent auto-incrementing
    counters.

    `move_id` is always equal to `cost_id`; it exists as the join
    target for `schedule_detail.move_id` so the dashboard can follow
    a scheduled activity backward to the move that scheduled it
    (same integer value as `cost_id`, distinct column name so the
    operator's mental model of "forward into cost_detail" vs
    "backward to the iteration_log row" stays clear)."""
    iteration_idx: int
    role: Literal['committed', 'rejected']
    score_rank: int
    item_score_rank: int
    # candidate identity
    item_id: str
    target_type: Literal['regular', 'safety']
    target_week: int | None
    machine_id: str
    machine_is_new: bool
    start_at: Literal['next_job_end', 'next_runout']
    idle_hours: float
    # summary + foreign keys into the detail tables
    total_score: float
    cost_id: int                   # forward FK into cost_detail
    move_id: int                   # this row's canonical "move" identity; always equal to cost_id
    sched_id: int                  # forward FK into schedule_detail (1:many on this id)


def build_iteration_log_record(
    iteration_idx: int,
    score_rank: int,
    item_score_rank: int,
    move: Move,
    total_score: float,
    cost_id: int,
    sched_id: int,
    state: State,
) -> IterationLogRecord:
    """Assemble one `IterationLogRecord` from a logged candidate.

    `score_rank` is the candidate's position across all scored
    candidates in the iteration (0 = global lowest = the committed
    move). `item_score_rank` is the candidate's position within its
    item's candidates (0 = item's lowest). `role` is `'committed'`
    iff both ranks are 0 — i.e., this is the global lowest. Other
    logged candidates are `'rejected'`.

    `total_score` is the candidate's score; `cost_id` and `sched_id`
    are the foreign keys into the cost and schedule detail tables —
    both allocated by the caller via independent counters. `move_id`
    on the produced record always equals `cost_id` — it's the
    canonical "move" identity that `ScheduleDetailRecord.move_id`
    joins on. `machine_is_new` is read from
    `state.machines[move.machine_id]`, and `idle_hours` converts
    `move.idle_for` to a float for the TSV."""
    machine = state.machines[move.machine_id]
    return IterationLogRecord(
        iteration_idx=iteration_idx,
        role=(
            'committed' if score_rank == 0 and item_score_rank == 0
            else 'rejected'
        ),
        score_rank=score_rank,
        item_score_rank=item_score_rank,
        item_id=move.item.id,
        target_type='safety' if move.week_idx is None else 'regular',
        target_week=move.week_idx,
        machine_id=move.machine_id,
        machine_is_new=machine.is_new,
        start_at=move.start_at,
        idle_hours=move.idle_for.total_seconds() / 3600.0,
        total_score=total_score,
        cost_id=cost_id,
        move_id=cost_id,           # canonical "move" identity; always == cost_id
        sched_id=sched_id,
    )


# ---- Cost detail (one row per scored candidate) ------------------------

@dataclass(frozen=True)
class CostDetailRecord:
    """One row of `cost_detail.tsv`; one record per scored candidate.

    Carries the full weighted cost breakdown — the same eleven scalars
    `CostBreakdown` exposes — plus integer foreign keys into the five
    per-cost detail tables. A `*_detail_id` is `None` when the
    corresponding cost has no contributing rows for this candidate
    (no non-zero deltas for the four demand-side costs; no
    higher-priority skipped orders for priority).

    `total` equals the sum of the eleven weighted components and
    matches the `total_score` field on the candidate's
    `IterationLogRecord`."""
    cost_id: int
    # weighted scalars (mirror CostBreakdown's totals)
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
    total: float
    # foreign keys into per-cost detail tables
    lateness_detail_id: int | None
    drainage_detail_id: int | None
    carrying_detail_id: int | None
    excess_detail_id: int | None
    priority_detail_id: int | None


# ---- Demand-side per-item delta tables ---------------------------------

@dataclass(frozen=True)
class LatenessDetailRecord:
    """One row of `lateness_detail.tsv`; one record per (candidate, item
    whose weighted lateness contribution would change from the
    iteration's baseline). Rows with `lateness_delta == 0` are not
    emitted. In practice the move only changes its target item's
    demand-side costs, so each detail group typically has at most one
    row."""
    lateness_detail_id: int        # groups all rows from one candidate's lateness deltas
    item_id: str
    lateness_delta: float          # weighted delta: w.lateness × (after.raw_view.lateness − baseline.raw_view.lateness)


@dataclass(frozen=True)
class DrainageDetailRecord:
    """Same shape as `LatenessDetailRecord` but for drainage. See its
    docstring for semantics."""
    drainage_detail_id: int
    item_id: str
    drainage_delta: float


@dataclass(frozen=True)
class CarryingDetailRecord:
    """Same shape as `LatenessDetailRecord` but for carrying. See its
    docstring for semantics."""
    carrying_detail_id: int
    item_id: str
    carrying_delta: float


@dataclass(frozen=True)
class ExcessDetailRecord:
    """Same shape as `LatenessDetailRecord` but for excess. See its
    docstring for semantics."""
    excess_detail_id: int
    item_id: str
    excess_delta: float


# ---- Priority per-item attribution (absolute, not delta) ---------------

@dataclass(frozen=True)
class PriorityDetailRecord:
    """One row of `priority_detail.tsv`; one record per (candidate,
    item whose deferred regular order is higher-priority than this
    move's order). Each item appears at most once per
    `priority_detail_id` because the candidate enumerator picks at
    most one regular order per item per iteration.

    Holds **absolute** weighted contributions, not deltas — priority
    cost is a per-move quantity that doesn't exist in the baseline
    state, so there's nothing to subtract from. The `week_idx` and
    `remaining_lbs` columns turn each row into a full picture of
    *what* is being deferred (not just how much it costs), so an
    operator can see which urgent orders this move is passing over."""
    priority_detail_id: int        # groups all rows from one candidate's priority breakdown
    item_id: str                   # owner of the higher-priority deferred order
    week_idx: int                  # week (0..3) of the deferred order
    remaining_lbs: float           # unfulfilled lbs of the deferred order at evaluation time (O.remaining_lbs)
    priority: float                # absolute weighted contribution: w.priority × remaining_lbs × 2^days_late(O, move)


# ---- Schedule detail (one row per Activity in move.plan) ---------------

@dataclass(frozen=True)
class ScheduleDetailRecord:
    """One row of `schedule_detail.tsv`; one record per `Activity` in a
    candidate's `move.plan`. Rows from the same candidate share a
    `sched_id`.

    `activity_id` is the underlying `Activity.id` string (e.g.
    `"JOB00001"`) — *not* a fresh counter — so it joins directly to
    the same column on the workbook's `schedule` sheet. `move_id`
    is the candidate's `cost_id` stored inline, joining back to
    `iteration_log.move_id`; see the module docstring for the
    cost_id/move_id semantic distinction.

    `description` is a human-readable rendering of the activity and
    its key fields — formatting details are owned by the CLI's TSV
    writer."""
    sched_id: int                  # groups all rows from one candidate's move.plan
    activity_id: str               # the Activity's stable id (e.g. "JOB00001"); shared with the workbook's schedule sheet
    move_id: int                   # FK back to iteration_log.move_id; always equal to the candidate's cost_id
    machine_id: str
    start: datetime
    end: datetime
    description: str


# ---- Counters and accumulators ----------------------------------------

@dataclass(frozen=True)
class IterLogCounters:
    """The eight independent auto-incrementing counter callables that
    allocate foreign-key ids across the verbose iteration-log tables.
    Each callable returns the next integer in its own sequence; the
    sequences are independent (one counter advancing does not advance
    the others). Constructed by the loop at the start of a verbose
    run via `_mk_counter` calls."""
    cost_id: Callable[[], int]
    sched_id: Callable[[], int]
    lateness_detail_id: Callable[[], int]
    drainage_detail_id: Callable[[], int]
    carrying_detail_id: Callable[[], int]
    excess_detail_id: Callable[[], int]
    priority_detail_id: Callable[[], int]


@dataclass
class IterLogAccumulators:
    """Per-table accumulator lists, collected across all iterations of
    a verbose run. Each list becomes one of the eight `PlanReport`
    detail tuples once the loop finishes — the loop initializes one
    instance, hands it to every `build_candidate_records` call, and
    passes it to `_build_report` at termination."""
    iteration_log: list[IterationLogRecord] = field(default_factory=list)
    cost_detail: list[CostDetailRecord] = field(default_factory=list)
    lateness_detail: list[LatenessDetailRecord] = field(default_factory=list)
    drainage_detail: list[DrainageDetailRecord] = field(default_factory=list)
    carrying_detail: list[CarryingDetailRecord] = field(default_factory=list)
    excess_detail: list[ExcessDetailRecord] = field(default_factory=list)
    priority_detail: list[PriorityDetailRecord] = field(default_factory=list)
    schedule_detail: list[ScheduleDetailRecord] = field(default_factory=list)


# ---- Per-candidate factory --------------------------------------------

def build_candidate_records(
    *,
    iteration_idx: int,
    score_rank: int,
    item_score_rank: int,
    move: Move,
    breakdown: CostBreakdown,
    baseline: CostBreakdown,
    state: State,
    accumulators: IterLogAccumulators,
    counters: IterLogCounters,
) -> None:
    """Append the full set of detail records for one logged candidate
    to `accumulators`. Mutates the accumulator lists in place; does
    not return anything.

    `score_rank` is the candidate's position across **all** scored
    candidates in the iteration; `item_score_rank` is its position
    within its item's candidates. `role` is `'committed'` iff both
    are 0. See `IterationLogRecord` for the full ordering semantics.

    Allocates fresh ids from `counters`: `cost_id` and `sched_id` per
    candidate, and a `*_detail_id` for each demand-cost delta group
    or priority group that has at least one contributing row.
    `ScheduleDetailRecord.activity_id` is the underlying `Activity.id`
    string (not a fresh counter), and `move_id` on both the
    `IterationLogRecord` and each `ScheduleDetailRecord` is the
    candidate's `cost_id` (stored inline as the canonical "move"
    identity, not allocated separately). Groups with no contributing
    rows leave their `*_detail_id` on the `CostDetailRecord` as
    `None`.

    Demand-side detail rows are `(after - baseline)` weighted per-item
    deltas, with zero-delta items dropped. Priority detail rows are
    absolute weighted contributions from `breakdown.priority_by_item`
    — the baseline has no priority cost, so there is nothing to
    subtract. Schedule rows mirror `move.plan` one-for-one."""
    cost_id = counters.cost_id()
    sched_id = counters.sched_id()

    # --- Demand-side per-item deltas (lateness / drainage / carrying / excess).
    lateness_detail_id: int | None = None
    lateness_deltas = _demand_deltas(
        breakdown.lateness_by_item, baseline.lateness_by_item,
    )
    if lateness_deltas:
        lateness_detail_id = counters.lateness_detail_id()
        for item_id, delta in lateness_deltas.items():
            accumulators.lateness_detail.append(LatenessDetailRecord(
                lateness_detail_id=lateness_detail_id,
                item_id=item_id,
                lateness_delta=delta,
            ))

    drainage_detail_id: int | None = None
    drainage_deltas = _demand_deltas(
        breakdown.drainage_by_item, baseline.drainage_by_item,
    )
    if drainage_deltas:
        drainage_detail_id = counters.drainage_detail_id()
        for item_id, delta in drainage_deltas.items():
            accumulators.drainage_detail.append(DrainageDetailRecord(
                drainage_detail_id=drainage_detail_id,
                item_id=item_id,
                drainage_delta=delta,
            ))

    carrying_detail_id: int | None = None
    carrying_deltas = _demand_deltas(
        breakdown.carrying_by_item, baseline.carrying_by_item,
    )
    if carrying_deltas:
        carrying_detail_id = counters.carrying_detail_id()
        for item_id, delta in carrying_deltas.items():
            accumulators.carrying_detail.append(CarryingDetailRecord(
                carrying_detail_id=carrying_detail_id,
                item_id=item_id,
                carrying_delta=delta,
            ))

    excess_detail_id: int | None = None
    excess_deltas = _demand_deltas(
        breakdown.excess_by_item, baseline.excess_by_item,
    )
    if excess_deltas:
        excess_detail_id = counters.excess_detail_id()
        for item_id, delta in excess_deltas.items():
            accumulators.excess_detail.append(ExcessDetailRecord(
                excess_detail_id=excess_detail_id,
                item_id=item_id,
                excess_delta=delta,
            ))

    # --- Priority per-item attribution (absolute, not delta).
    priority_detail_id: int | None = None
    if breakdown.priority_by_item:
        priority_detail_id = counters.priority_detail_id()
        for item_id, pc in breakdown.priority_by_item.items():
            accumulators.priority_detail.append(PriorityDetailRecord(
                priority_detail_id=priority_detail_id,
                item_id=item_id,
                week_idx=pc.week_idx,
                remaining_lbs=pc.remaining_lbs,
                priority=pc.priority,
            ))

    # --- Schedule detail: one row per Activity in move.plan.
    for a in move.plan:
        accumulators.schedule_detail.append(ScheduleDetailRecord(
            sched_id=sched_id,
            activity_id=a.id,
            move_id=cost_id,     # canonical "move" identity; always == cost_id
            machine_id=move.machine_id,
            start=a.start,
            end=a.end,
            description=_activity_desc(a),
        ))

    # --- Cost detail: one row per candidate, with FKs into the detail tables.
    accumulators.cost_detail.append(CostDetailRecord(
        cost_id=cost_id,
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
        total=breakdown.total,
        lateness_detail_id=lateness_detail_id,
        drainage_detail_id=drainage_detail_id,
        carrying_detail_id=carrying_detail_id,
        excess_detail_id=excess_detail_id,
        priority_detail_id=priority_detail_id,
    ))

    # --- Iteration-log row, last so cost_id / sched_id are resolved.
    accumulators.iteration_log.append(build_iteration_log_record(
        iteration_idx=iteration_idx,
        score_rank=score_rank,
        item_score_rank=item_score_rank,
        move=move,
        total_score=breakdown.total,
        cost_id=cost_id,
        sched_id=sched_id,
        state=state,
    ))


# ---- Private helpers --------------------------------------------------

def _demand_deltas(
    after: dict[str, float], baseline: dict[str, float],
) -> dict[str, float]:
    """Compute per-item deltas as `after - baseline`, dropping items
    whose delta is zero. Items present in only one dict are treated
    as having 0 contribution in the absent dict."""
    out: dict[str, float] = {}
    for item_id in set(after) | set(baseline):
        v = after.get(item_id, 0.0) - baseline.get(item_id, 0.0)
        if v != 0.0:
            out[item_id] = v
    return out


def _activity_desc(a: 'Activity') -> str:
    """Short text description for `ScheduleDetailRecord.description`.
    Mirrors `report._activity_desc` so the verbose TSV's activity
    descriptions match the headline XLSX schedule sheet."""
    if isinstance(a, (Job, Waste)):
        return a.item.id
    if isinstance(a, BeamLoad):
        return f'{a.beam.id} on {a.bar}'
    if isinstance(a, TapeOut):
        return a.bars
    if isinstance(a, StyleChange):
        return f'from {a.from_item.id} to {a.to_item.id}'
    if isinstance(a, Idle):
        return ''
    return ''


def candidate_sort_key(
    score: float, move: Move,
) -> tuple[float, str, str, int]:
    """Deterministic tie-break sort key for a candidate within an
    iteration. Score ascending, then `item_id`, then `machine_id`,
    then `start_at` with `'next_runout'` ordered before
    `'next_job_end'`. Used by the verbose loop for both the global
    `score_rank` ordering and the within-item `item_score_rank`
    ordering. See DESIGN.md's "Tie-breaking" paragraph in the
    "Verbose iteration log" section."""
    return (
        score,
        move.item.id,
        move.machine_id,
        0 if move.start_at == 'next_runout' else 1,
    )
