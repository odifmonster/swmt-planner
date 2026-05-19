from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from swmtplanner.schedule import Activity, Job
from swmtplanner.demand.order import RawOrder
from swmtplanner.demand.rlsitem import CostComponents
from swmtplanner.planners.infinite.costing import CostBreakdown, Costing
from swmtplanner.planners.infinite.state import Move, State
from swmtplanner.planners.infinite.coordination import (
    RegularOrder, SafetyOrder, eligible_orders,
)

__all__ = [
    'DecisionPoint', 'RegularOrder', 'SafetyOrder',
    'eligible_decision_points', 'eligible_orders', 'enumerate_candidates',
    'IterationLogRecord', 'build_iteration_log_record',
    'PlanReport', 'plan',
]


@dataclass(frozen=True)
class DecisionPoint:
    machine_id: str
    start_at: Literal['next_job_end', 'next_runout']
    time: datetime


def eligible_decision_points(state: State) -> list[DecisionPoint]: ...
def enumerate_candidates(state: State) -> list[Move]: ...


@dataclass(frozen=True)
class IterationLogRecord:
    iteration_idx: int
    role: Literal['committed', 'rejected']
    score_rank: int
    item_id: str
    target_type: Literal['regular', 'safety']
    target_week: int | None
    machine_id: str
    machine_is_new: bool
    start_at: Literal['next_job_end', 'next_runout']
    idle_hours: float
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
) -> IterationLogRecord: ...


@dataclass
class PlanReport:
    schedules: dict[str, tuple[Activity, ...]]
    jobs_by_item: dict[str, tuple[Job, ...]]
    total_score: float
    cost_components_by_item: dict[str, CostComponents]
    unmet_lbs_by_item_week: dict[tuple[str, int], float]
    late_orders: tuple[RawOrder, ...]
    iteration_log: tuple[IterationLogRecord, ...] | None = ...


def plan(
    state: State, costing: Costing, *, verbose: bool = ...,
) -> PlanReport: ...
