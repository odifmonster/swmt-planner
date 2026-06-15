from datetime import timedelta
from typing import Any, Callable, TYPE_CHECKING

from swmtplanner.demand.order import (
    RawOrder, SafetyAwareOrder, WeeklyDemand, Safety,
)

if TYPE_CHECKING:
    from swmtplanner.demand.rlsitem import RlsItem
    from swmtplanner.schedule import Job, Roll

__all__ = ['RawView', 'SafetyAwareView']


class RawView:
    def __init__(self, rls_item: 'RlsItem', weekly_demand: list[WeeklyDemand]) -> None: ...
    @property
    def orders(self) -> tuple[RawOrder, ...]: ...
    @property
    def lateness(self) -> float: ...
    def recompute(
        self, jobs: list['Job'], on_hand: float,
        detail_sink: Callable[..., Any] | None = ...,
    ) -> None: ...


class SafetyAwareView:
    def __init__(self, rls_item: 'RlsItem', weekly_demand: list[WeeklyDemand]) -> None: ...
    @property
    def orders(self) -> tuple[SafetyAwareOrder, ...]: ...
    @property
    def safety(self) -> Safety: ...
    @property
    def roll_order_links(self) -> tuple[tuple['Roll', str], ...]: ...
    @property
    def safety_target(self) -> float: ...
    @property
    def lead_time(self) -> timedelta: ...
    @property
    def safety_pool(self) -> float: ...
    @property
    def excess(self) -> float: ...
    @property
    def carrying(self) -> float: ...
    @property
    def drainage(self) -> float: ...
    def recompute(
        self, jobs: list['Job'], on_hand: float,
        detail_sink: Callable[..., Any] | None = ...,
    ) -> None: ...
