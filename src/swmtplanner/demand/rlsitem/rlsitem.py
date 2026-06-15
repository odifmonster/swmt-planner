#!/usr/bin/env python

from dataclasses import dataclass
from typing import TYPE_CHECKING
from datetime import datetime, timedelta
from bisect import bisect_right

from swmtplanner.support import HasID
from swmtplanner.demand.order import WeeklyDemand
from swmtplanner.demand.view import RawView, SafetyAwareView

if TYPE_CHECKING:
    from swmtplanner.products import Greige
    from swmtplanner.schedule import Job

def _due_date(start: 'datetime', idx: int):
    return start + timedelta(weeks=idx)

def _job_completion(job: 'Job') -> datetime:
    """Sort key for the production schedule: a job's final roll's
    `completion_time` (its effective end). A job with no rolls sorts
    first via `datetime.min`."""
    return job.rolls[-1].completion_time if job.rolls else datetime.min

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

        # Snapshot what initial on-hand inventory covers, while the views are
        # primed against the empty job list (jobs=[] + on_hand). Keyed by order
        # id: each regular order -> its allocated_lbs, plus the safety order ->
        # the safety_pool. Immutable; later register_jobs don't change it.
        self._on_hand_coverage: dict[str, float] = {
            o.id: o.allocated_lbs for o in self._safety_view.orders
        }
        self._on_hand_coverage[self._safety_view.safety.id] = (
            self._safety_view.safety_pool
        )

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
        return sum(j.total_lbs for j in self._jobs)

    @property
    def total_demand_lbs(self) -> float:
        return sum(w.qty_lbs for w in self._weekly_demand)

    @property
    def excess_lbs(self) -> float:
        # Fast scalar over the whole job list; the safety view's `excess`
        # tracker is the authoritative penalty quantity.
        return max(0.0, self.scheduled_lbs - self.total_demand_lbs)

    @property
    def on_hand_coverage(self) -> dict[str, float]:
        """Per-order lbs met by initial on-hand inventory alone (no jobs),
        keyed by order id — each regular `Order.id` plus the `Safety.id`.
        Captured at construction from the jobs=`[]` allocation; unaffected by
        later `register_jobs`. Returns a fresh copy."""
        return dict(self._on_hand_coverage)

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

    def register_jobs(self, jobs: list['Job']):
        """Insert each of `jobs` into the internal job list (kept sorted by
        each job's final `roll.completion_time`) then re-run both views'
        `recompute` once. `jobs` may be empty, in which case this just
        re-runs the views against the unchanged job list."""
        for job in jobs:
            idx = bisect_right(
                self._jobs, _job_completion(job), key=_job_completion,
            )
            self._jobs.insert(idx, job)
        self._recompute_views()

    def cost_if(self, jobs: list['Job'], detail_sink=None):
        """Return the `CostComponents` that would result if `jobs` were
        registered, without mutating any state. Empty `jobs` returns the
        current state's cost.

        `detail_sink`, when given, is forwarded to both views' `recompute` so
        they report their per-window cost detail (lateness / drainage /
        carrying / excess) as the hypothetical is evaluated, before the state
        is restored."""
        new_jobs = list(self._jobs)
        for job in jobs:
            idx = bisect_right(
                new_jobs, _job_completion(job), key=_job_completion,
            )
            new_jobs.insert(idx, job)

        self._raw_view.recompute(new_jobs, self._on_hand_lbs, detail_sink)
        self._safety_view.recompute(new_jobs, self._on_hand_lbs, detail_sink)
        res = CostComponents(self._raw_view.lateness,
                             self._safety_view.drainage,
                             self._safety_view.carrying,
                             self._safety_view.excess)
        self._recompute_views()
        return res