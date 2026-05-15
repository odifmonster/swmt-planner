#!/usr/bin/env python

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from swmtplanner.support import HasID

if TYPE_CHECKING:
    from swmtplanner.demand.rlsitem import RlsItem

@dataclass(frozen=True)
class WeeklyDemand:
    week_idx: int
    due_date: datetime
    qty_lbs: float

class Order(HasID[str]):

    def __init__(self, rls_item: 'RlsItem', week: WeeklyDemand) -> None:
        self._id = f'P{week.week_idx}@{rls_item.item.id}'
        self._rls_item = rls_item
        self._week = week
        self._allocated_lbs: float = 0.0

    @property
    def id(self) -> str:
        return self._id

    @property
    def rls_item(self) -> 'RlsItem':
        return self._rls_item

    @property
    def week(self) -> WeeklyDemand:
        return self._week

    @property
    def allocated_lbs(self) -> float:
        return self._allocated_lbs

    @allocated_lbs.setter
    def allocated_lbs(self, value: float) -> None:
        self._allocated_lbs = value

    @property
    def remaining_lbs(self) -> float:
        return max(0.0, self._week.qty_lbs - self._allocated_lbs)

    @property
    def is_fulfilled(self) -> bool:
        return self._allocated_lbs >= self._week.qty_lbs

class SafetyAwareOrder(Order):
    pass

class RawOrder(Order):
    pass
