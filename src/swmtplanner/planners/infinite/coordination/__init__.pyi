from dataclasses import dataclass
from datetime import datetime

from swmtplanner.products import Greige
from swmtplanner.planners.infinite.state import State

__all__ = [
    'OrderKey', 'RegularOrder', 'SafetyOrder', 'ScoringContext',
    'eligible_orders', 'assign_priorities',
]


@dataclass(frozen=True)
class OrderKey:
    item_id: str
    week_idx: int | None


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


@dataclass(frozen=True)
class ScoringContext:
    priorities: dict[OrderKey, int]
    earliest_dp_time: datetime


def eligible_orders(state: State) -> list[RegularOrder | SafetyOrder]: ...
def assign_priorities(state: State) -> dict[OrderKey, int]: ...
