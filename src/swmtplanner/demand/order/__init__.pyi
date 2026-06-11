from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from swmtplanner.support import HasID

if TYPE_CHECKING:
    from swmtplanner.demand.rlsitem import RlsItem
    from swmtplanner.demand.view import SafetyAwareView

__all__ = ['WeeklyDemand', 'Order', 'SafetyAwareOrder', 'RawOrder', 'Safety']

@dataclass(frozen=True)
class WeeklyDemand:
    week_idx: int
    due_date: datetime
    qty_lbs: float

class Order(HasID[str]):
    def __init__(self, rls_item: 'RlsItem', week: WeeklyDemand) -> None: ...
    @property
    def rls_item(self) -> 'RlsItem': ...
    @property
    def week(self) -> WeeklyDemand: ...
    @property
    def allocated_lbs(self) -> float: ...
    @allocated_lbs.setter
    def allocated_lbs(self, value: float) -> None: ...
    @property
    def remaining_lbs(self) -> float: ...
    @property
    def is_fulfilled(self) -> bool: ...

class SafetyAwareOrder(Order): ...

class Safety(HasID[str]):
    def __init__(self, rls_item: 'RlsItem', view: 'SafetyAwareView') -> None: ...
    @property
    def view(self) -> 'SafetyAwareView': ...
    @property
    def remaining_lbs(self) -> float: ...

class RawOrder(Order):
    @property
    def late_lbs(self) -> float: ...
    @late_lbs.setter
    def late_lbs(self, value: float) -> None: ...
    @property
    def late_fill_date(self) -> datetime | None: ...
    @late_fill_date.setter
    def late_fill_date(self, value: datetime | None) -> None: ...
