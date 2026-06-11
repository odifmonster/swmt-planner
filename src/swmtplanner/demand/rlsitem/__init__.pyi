from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from swmtplanner.support import HasID
from swmtplanner.demand.order import WeeklyDemand
from swmtplanner.demand.view import RawView, SafetyAwareView

if TYPE_CHECKING:
    from swmtplanner.products import Greige
    from swmtplanner.schedule import Job

__all__ = ['RlsItem', 'CostComponents']


@dataclass(frozen=True)
class CostComponents:
    lateness: float
    drainage: float
    carrying: float
    excess: float


class RlsItem(HasID[str]):
    def __init__(
        self,
        item: 'Greige',
        start_date: datetime,
        on_hand_lbs: float,
        lead_time: timedelta,
        weekly_lbs_needed: list[float],
    ) -> None: ...
    @property
    def item(self) -> 'Greige': ...
    @property
    def start_date(self) -> datetime: ...
    @property
    def on_hand_lbs(self) -> float: ...
    @property
    def lead_time(self) -> timedelta: ...
    @property
    def weekly_demand(self) -> tuple[WeeklyDemand, ...]: ...
    @property
    def jobs(self) -> tuple['Job', ...]: ...
    @property
    def raw_view(self) -> RawView: ...
    @property
    def safety_view(self) -> SafetyAwareView: ...
    @property
    def scheduled_lbs(self) -> float: ...
    @property
    def total_demand_lbs(self) -> float: ...
    @property
    def excess_lbs(self) -> float: ...
    @property
    def on_hand_coverage(self) -> dict[str, float]: ...
    @property
    def replenishment_need_lbs(self) -> float: ...
    def register_jobs(self, jobs: list['Job']) -> None: ...
    def cost_if(self, jobs: list['Job']) -> CostComponents: ...
