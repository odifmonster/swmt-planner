#!/usr/bin/env python

from dataclasses import dataclass
from typing import TYPE_CHECKING
from datetime import timedelta
from bisect import bisect_right

from swmtplanner.support import HasID
from swmtplanner.demand.order import WeeklyDemand
from swmtplanner.demand.view import RawView, SafetyAwareView

if TYPE_CHECKING:
    from datetime import datetime
    from swmtplanner.products import Greige
    from swmtplanner.schedule import Job

def _due_date(start: 'datetime', idx: int):
    return start + timedelta(weeks=idx)

@dataclass(frozen=True)
class CostComponents:
    lateness: float
    drainage: float
    carrying: float
    excess: float

class RlsItem(HasID[str]):

    def __init__(self, item: 'Greige', start_date: 'datetime', on_hand_lbs: float,
                 lead_time: timedelta, weekly_lbs_needed: list[float]):
        self._item = item
        self._id = item.id
        self._start_date = start_date
        self._on_hand_lbs = on_hand_lbs
        self._lead_time = lead_time

        self._weekly_demand = tuple([WeeklyDemand(i, _due_date(start_date, i), lbs)
                               for i, lbs in enumerate(weekly_lbs_needed)])

        self._raw_view = RawView(self, list(self._weekly_demand))
        self._safety_view = SafetyAwareView(self, list(self._weekly_demand))

        self._jobs: list['Job'] = []

        # Prime the views so their orders/cost-trackers reflect on_hand against
        # an empty job list. Without this the views are stale until the first
        # register_job, and cost_if on a fresh RlsItem would observe a state
        # change between its pre- and post-recompute snapshots.
        self._recompute_views()

    @property
    def id(self) -> str:
        return self._id

    @property
    def item(self) -> 'Greige':
        return self._item

    @property
    def start_date(self) -> 'datetime':
        return self._start_date

    @property
    def on_hand_lbs(self) -> float:
        return self._on_hand_lbs

    @property
    def lead_time(self) -> timedelta:
        return self._lead_time

    @property
    def weekly_demand(self) -> tuple[WeeklyDemand, ...]:
        return self._weekly_demand

    @property
    def jobs(self) -> tuple['Job', ...]:
        return tuple(self._jobs)

    @property
    def raw_view(self) -> RawView:
        return self._raw_view

    @property
    def safety_view(self) -> SafetyAwareView:
        return self._safety_view

    # --- Aggregates derived from the views and job list ---

    @property
    def scheduled_lbs(self) -> float:
        return sum(j.lbs for j in self._jobs)

    @property
    def total_demand_lbs(self) -> float:
        return sum(w.qty_lbs for w in self._weekly_demand)

    @property
    def excess_lbs(self) -> float:
        # Fast scalar over the whole job list; the safety view's `excess`
        # tracker is the authoritative penalty quantity.
        return max(0.0, self.scheduled_lbs - self.total_demand_lbs)

    @property
    def replenishment_need_lbs(self) -> float:
        # "What the scheduler still has to place" — every unfilled lb in
        # the safety view's orders plus any gap left in the safety pool.
        order_remaining = sum(o.remaining_lbs for o in self._safety_view.orders)
        safety_shortfall = max(
            0.0, self._safety_view.safety_target - self._safety_view.safety_pool
        )
        return order_remaining + safety_shortfall

    def _recompute_views(self):
        for v in (self._raw_view, self._safety_view):
            v.recompute(self._jobs, self._on_hand_lbs)
    
    def register_job(self, job: 'Job'):
        idx = bisect_right(self._jobs, job.end, key=lambda j: j.end)
        self._jobs.insert(idx, job)
        self._recompute_views()
    
    def cost_if(self, job: 'Job'):
        idx = bisect_right(self._jobs, job.end, key=lambda j: j.end)
        new_jobs = [job]
        if self._jobs:
            new_jobs = self._jobs[:idx] + new_jobs + self._jobs[idx:]
        
        self._raw_view.recompute(new_jobs, self._on_hand_lbs)
        self._safety_view.recompute(new_jobs, self._on_hand_lbs)
        res = CostComponents(self._raw_view.lateness,
                             self._safety_view.drainage,
                             self._safety_view.carrying,
                             self._safety_view.excess)
        self._recompute_views()
        return res