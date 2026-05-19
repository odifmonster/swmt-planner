#!/usr/bin/env python

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from swmtplanner.support import HasID

if TYPE_CHECKING:
    from swmtplanner.demand.rlsitem import RlsItem
    from swmtplanner.schedule import Job

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
    """One week's slice of the raw view's accounting. Carries two
    extra per-order attributes alongside `allocated_lbs` so the
    scheduler can build an operator-facing late-orders report
    directly from the order list (no re-derivation required):

    - `late_lbs`: subset of `allocated_lbs` that came from chunks
      arriving after `week.due_date`.
    - `late_fill_date`: latest chunk-arrival time across the chunks
      that fed `allocated_lbs` — i.e., when the order became whole,
      or (when recompute ends with `remaining_lbs > 0`) the time of
      the last job that made progress on it. `None` when no chunks
      were allocated to this order at all.

    Both are written by `RawView.recompute`."""

    def __init__(self, rls_item: 'RlsItem', week: WeeklyDemand) -> None:
        super().__init__(rls_item, week)
        self._late_lbs: float = 0.0
        self._late_fill_date: datetime | None = None

    @property
    def late_lbs(self) -> float:
        return self._late_lbs

    @late_lbs.setter
    def late_lbs(self, value: float) -> None:
        self._late_lbs = value

    @property
    def late_fill_date(self) -> datetime | None:
        return self._late_fill_date

    @late_fill_date.setter
    def late_fill_date(self, value: datetime | None) -> None:
        self._late_fill_date = value
