from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from swmtplanner.schedule import Activity, Job, PassedOver
from swmtplanner.schedule.capacity import ChangeoverCapacity
from swmtplanner.demand.order import RawOrder
from swmtplanner.demand.rlsitem import CostComponents, RlsItem
from swmtplanner.debuglog import DebugLog
from swmtplanner.planners.infinite.costing import Costing
from swmtplanner.planners.infinite.state import PriorCommit, Move, State
from swmtplanner.planners.infinite.coordination import (
    RegularOrder, SafetyOrder, eligible_orders,
)

__all__ = [
    'DecisionPoint', 'RegularOrder', 'SafetyOrder',
    'eligible_decision_points', 'eligible_orders', 'enumerate_candidates',
    'PlanReport', 'plan', 'build_report', 'recommit_prior',
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
    jobs_by_machine: dict[str, tuple[Job, ...]]
    total_score: float
    cost_components_by_item: dict[str, CostComponents]
    unmet_lbs_by_item_week: dict[tuple[str, int], float]
    late_orders: tuple[RawOrder, ...]
    rls_items: dict[str, RlsItem]
    capacity: ChangeoverCapacity | None = ...
    queue_passed_over: dict[str, tuple[PassedOver, ...]] = ...
    """Per machine, the plant-assigned sets its committed plans passed over
    (`Machine.queue_passed_over`); machines with none are left out."""
    prior: tuple[PriorCommit, ...] = ...
    """The prior plan's jobs, each with its fate in this run."""


def plan(
    state: State, costing: Costing, *, debuglog: DebugLog | None = ...,
    tape_out_report: Path | None = ...,
) -> PlanReport:
    """`tape_out_report`: a text file to which every iteration whose chosen
    move tapes a set out appends its full candidate list with scores."""
    ...


def recommit_prior(state: State) -> int:
    """The pre-pass: recommit every prior job inside the frozen window whose
    order is still urgent and open, in prior start order, each planned with
    the current item's fill; returns how many moves were committed."""
    ...


def build_report(state: State, costing: Costing) -> PlanReport:
    """The `PlanReport` of a state as it stands: the machines' schedules,
    the demand items' jobs and views, the score, what is unmet and late."""
    ...
