from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from swmtplanner.schedule import Activity, Job
from swmtplanner.demand.rlsitem import CostComponents
from swmtplanner.planners.infinite.costing import Costing
from swmtplanner.planners.infinite.state import Move, State
from swmtplanner.planners.infinite.coordination import (
    RegularOrder, SafetyOrder, eligible_orders,
)

__all__ = [
    'DecisionPoint', 'RegularOrder', 'SafetyOrder',
    'eligible_decision_points', 'eligible_orders', 'enumerate_candidates',
    'PlanReport', 'plan',
]


@dataclass(frozen=True)
class DecisionPoint:
    machine_id: str
    start_at: Literal['next_job_end', 'next_runout']
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


def plan(state: State, costing: Costing) -> PlanReport: ...
