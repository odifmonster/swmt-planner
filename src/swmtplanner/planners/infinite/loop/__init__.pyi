from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from swmtplanner.products import Greige
from swmtplanner.planners.infinite.state import Move, State

__all__ = [
    'DecisionPoint', 'RegularOrder', 'SafetyOrder',
    'eligible_decision_points', 'eligible_orders', 'enumerate_candidates',
]


@dataclass(frozen=True)
class DecisionPoint:
    machine_id: str
    start_at: Literal['next_job_end', 'next_runout']
    time: datetime


@dataclass(frozen=True)
class RegularOrder:
    item: Greige
    week_idx: int
    due_date: datetime
    lbs: float


@dataclass(frozen=True)
class SafetyOrder:
    item: Greige
    lbs: float


def eligible_decision_points(state: State) -> list[DecisionPoint]: ...
def eligible_orders(state: State) -> list[RegularOrder | SafetyOrder]: ...
def enumerate_candidates(state: State) -> list[Move]: ...
