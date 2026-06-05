from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from swmtplanner.schedule import Activity, Job
from swmtplanner.demand.order import RawOrder
from swmtplanner.demand.rlsitem import CostComponents
from swmtplanner.planners.infinite.costing import Costing
from swmtplanner.planners.infinite.iterlog import (
    IterationLogRecord, build_iteration_log_record,
    CostDetailRecord,
    LatenessDetailRecord, DrainageDetailRecord,
    CarryingDetailRecord, ExcessDetailRecord,
    PriorityDetailRecord,
    ScheduleDetailRecord,
)
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
    start_at: Literal['schedule_tail', 'next_runout']
    time: datetime


def eligible_decision_points(state: State) -> list[DecisionPoint]: ...
def enumerate_candidates(state: State) -> list[Move]: ...


@dataclass
class PlanReport:
    schedules: dict[str, tuple[Activity, ...]]
    jobs_by_item: dict[str, tuple[Job, ...]]
    total_score: float
    cost_components_by_item: dict[str, CostComponents]
    unmet_lbs_by_item_week: dict[tuple[str, int], float]
    late_orders: tuple[RawOrder, ...]
    iteration_log: tuple[IterationLogRecord, ...] | None = ...
    cost_detail: tuple[CostDetailRecord, ...] | None = ...
    lateness_detail: tuple[LatenessDetailRecord, ...] | None = ...
    drainage_detail: tuple[DrainageDetailRecord, ...] | None = ...
    carrying_detail: tuple[CarryingDetailRecord, ...] | None = ...
    excess_detail: tuple[ExcessDetailRecord, ...] | None = ...
    priority_detail: tuple[PriorityDetailRecord, ...] | None = ...
    schedule_detail: tuple[ScheduleDetailRecord, ...] | None = ...


def plan(
    state: State, costing: Costing, *, verbose: bool = ...,
) -> PlanReport: ...
