from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Literal

from swmtplanner.planners.infinite.costing import CostBreakdown
from swmtplanner.planners.infinite.state import Move, State

__all__ = [
    'IterationLogRecord', 'build_iteration_log_record',
    'CostDetailRecord',
    'LatenessDetailRecord', 'DrainageDetailRecord',
    'CarryingDetailRecord', 'ExcessDetailRecord',
    'PriorityDetailRecord',
    'ScheduleDetailRecord',
    'IterLogCounters', 'IterLogAccumulators',
    'build_candidate_records', 'candidate_sort_key',
]


@dataclass(frozen=True)
class IterationLogRecord:
    iteration_idx: int
    role: Literal['committed', 'rejected']
    score_rank: int
    item_score_rank: int
    item_id: str
    target_type: Literal['regular', 'safety']
    target_week: int | None
    machine_id: str
    machine_is_new: bool
    start_at: Literal['schedule_tail', 'next_runout']
    idle_hours: float
    total_score: float
    cost_id: int
    sched_id: int


def build_iteration_log_record(
    iteration_idx: int,
    score_rank: int,
    item_score_rank: int,
    move: Move,
    total_score: float,
    cost_id: int,
    sched_id: int,
    state: State,
) -> IterationLogRecord: ...


@dataclass(frozen=True)
class CostDetailRecord:
    cost_id: int
    lateness: float
    drainage: float
    carrying: float
    excess: float
    tape_out_single: float
    tape_out_both: float
    style_change: float
    runner_change: float
    pattern_change: float
    idle_time: float
    waste_lbs: float
    priority: float
    level_loading: float
    old_machine: float
    total: float
    lateness_detail_id: int | None
    drainage_detail_id: int | None
    carrying_detail_id: int | None
    excess_detail_id: int | None
    priority_detail_id: int | None


@dataclass(frozen=True)
class LatenessDetailRecord:
    lateness_detail_id: int
    item_id: str
    lateness_delta: float


@dataclass(frozen=True)
class DrainageDetailRecord:
    drainage_detail_id: int
    item_id: str
    drainage_delta: float


@dataclass(frozen=True)
class CarryingDetailRecord:
    carrying_detail_id: int
    item_id: str
    carrying_delta: float


@dataclass(frozen=True)
class ExcessDetailRecord:
    excess_detail_id: int
    item_id: str
    excess_delta: float


@dataclass(frozen=True)
class PriorityDetailRecord:
    priority_detail_id: int
    item_id: str
    week_idx: int
    remaining_lbs: float
    priority: float


@dataclass(frozen=True)
class ScheduleDetailRecord:
    sched_id: int
    activity_id: int
    machine_id: str
    start: datetime
    end: datetime
    description: str


@dataclass(frozen=True)
class IterLogCounters:
    cost_id: Callable[[], int]
    sched_id: Callable[[], int]
    lateness_detail_id: Callable[[], int]
    drainage_detail_id: Callable[[], int]
    carrying_detail_id: Callable[[], int]
    excess_detail_id: Callable[[], int]
    priority_detail_id: Callable[[], int]


@dataclass
class IterLogAccumulators:
    iteration_log: list[IterationLogRecord]
    cost_detail: list[CostDetailRecord]
    lateness_detail: list[LatenessDetailRecord]
    drainage_detail: list[DrainageDetailRecord]
    carrying_detail: list[CarryingDetailRecord]
    excess_detail: list[ExcessDetailRecord]
    priority_detail: list[PriorityDetailRecord]
    schedule_detail: list[ScheduleDetailRecord]


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
) -> None: ...


def candidate_sort_key(
    score: float, move: Move,
) -> tuple[float, str, str, int]: ...
