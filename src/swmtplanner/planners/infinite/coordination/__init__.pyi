from dataclasses import dataclass
from datetime import datetime

from swmtplanner.products import Greige, BeamSetDesc
from swmtplanner.schedule import Machine
from swmtplanner.planners.infinite.state import Move, State

__all__ = [
    'OrderKey', 'RegularOrder', 'SafetyOrder', 'ScoringContext',
    'eligible_orders', 'assign_priorities', 'unique_setups',
    'build_new_machine_avail', 'build_earliest_dp_excluding', 'build_context',
    'build_cheap_sets', 'build_urgent_by_item', 'cheap_set_after', 'holds_yarn', 'item_yarn',
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
    gross_lbs: float
    """The week's demand as loaded (before on-hand); the priority cost
    values predicted lateness as `lbs / gross_lbs`."""
    order_id: str


@dataclass(frozen=True)
class SafetyOrder:
    item: Greige
    lbs: float
    order_id: str


@dataclass(frozen=True)
class ScoringContext:
    priorities: dict[OrderKey, int]
    regular_orders_by_key: dict[OrderKey, RegularOrder]
    earliest_dp_excluding: dict[str, datetime]
    earliest_dp_time: datetime
    new_machine_avail: dict[Greige, bool]
    cheap_sets: dict[str, frozenset[str]] = ...
    """machine_id -> items it can run at its tail with no tape-out and no
    pattern change (recovery cost)."""
    urgent_by_item: dict[str, list[RegularOrder]] = ...
    """item id -> its urgent regular orders with remaining lbs (recovery cost)."""
    recovery_cache: dict = ...



def eligible_orders(state: State) -> list[RegularOrder | SafetyOrder]: ...
def assign_priorities(state: State) -> dict[OrderKey, int]: ...
def unique_setups(state: State) -> set[str]:
    """Ids of the demand items whose top/bottom beam-set pair no other
    demand item shares."""
    ...
def build_new_machine_avail(
    state: State, candidates: list[Move],
) -> dict[Greige, bool]: ...
def build_earliest_dp_excluding(
    state: State, candidates: list[Move],
) -> dict[str, datetime]: ...
def item_yarn(item: Greige) -> tuple[BeamSetDesc, BeamSetDesc]: ...
def holds_yarn(machine: Machine, item: Greige) -> bool:
    """The machine's mounted sets at its tail fit the item's beam descriptions."""
    ...
def cheap_set_after(state: State, machine_id: str, item: Greige) -> frozenset[str]:
    """The machine's cheap set once it runs `item`."""
    ...
def build_cheap_sets(state: State) -> dict[str, frozenset[str]]: ...
def build_urgent_by_item(state: State) -> dict[str, list[RegularOrder]]: ...
def build_context(
    state: State, candidates: list[Move],
) -> ScoringContext: ...
