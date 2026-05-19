from dataclasses import dataclass
from datetime import datetime

from swmtplanner.products import Greige
from swmtplanner.planners.infinite.state import Move, State

__all__ = [
    'OrderKey', 'RegularOrder', 'SafetyOrder', 'ScoringContext',
    'eligible_orders', 'assign_priorities',
    'build_new_machine_avail', 'build_earliest_dp_excluding', 'build_context',
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
    regular_orders_by_key: dict[OrderKey, RegularOrder]
    earliest_dp_excluding: dict[str, datetime]
    earliest_dp_time: datetime
    new_machine_avail: dict[Greige, bool]


def eligible_orders(state: State) -> list[RegularOrder | SafetyOrder]: ...
def assign_priorities(state: State) -> dict[OrderKey, int]: ...
def build_new_machine_avail(
    state: State, candidates: list[Move],
) -> dict[Greige, bool]: ...
def build_earliest_dp_excluding(
    state: State, candidates: list[Move],
) -> dict[str, datetime]: ...
def build_context(
    state: State, candidates: list[Move],
) -> ScoringContext: ...
