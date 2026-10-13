from datetime import datetime, timedelta
from typing import Any, Callable, TYPE_CHECKING

from swmtplanner.demand.order import (
    RawOrder, SafetyAwareOrder, WeeklyDemand, Safety,
)

if TYPE_CHECKING:
    from swmtplanner.demand.rlsitem import RlsItem
    from swmtplanner.schedule import Job, Roll

__all__ = ['RawView', 'SafetyAwareView', 'lateness_factor', 'LINEAR_DAYS']

LINEAR_DAYS: float
"""Days past due over which lateness grows linearly (7) before doubling."""

def lateness_factor(days_late: float) -> float:
    """Per-lb lateness multiplier: `days_late` up to `LINEAR_DAYS`, then
    `LINEAR_DAYS × 2 ** (days_late − LINEAR_DAYS)`; 0 when not late."""
    ...


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
