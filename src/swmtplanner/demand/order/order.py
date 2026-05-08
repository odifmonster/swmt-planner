#!/usr/bin/env python

from collections import namedtuple
from datetime import datetime, timedelta
from bisect import bisect_right

from ...support import Observer, HasID
from ...products import Greige
from ...schedule import Job

DemandQty = namedtuple('DemandQty', ['cumulative', 'regular', 'safety', 'excess'])

class Order(HasID[str], Observer[Job]):
    
    def __init__(self, item: Greige, due_date: datetime, priority: int, cur_lbs: float,
                 prev_lbs: float, prev_due: datetime, safety: float, excess: float):
        self._id = f'P{priority}@{item.id}'
        self._item = item
        self._due_date = due_date
        self._total_lbs = cur_lbs + prev_lbs
        self._prev_lbs = prev_lbs
        self._prev_due = prev_due
        self._safety = safety

        self._lbs_remaining = DemandQty(cumulative=self._total_lbs,
                                        safety=safety,
                                        regular=cur_lbs,
                                        excess=excess)
        self._init_lbs_remaining = self._lbs_remaining

        self._jobs: list[Job] = []
        self._demand_cache: dict[datetime, DemandQty] = {}

    def _lbs_produced_by(self, d: datetime):
        return sum(j.lbs for j in filter(lambda j: j.end <= d, self._jobs))

    def _get_safety_use(self, by: datetime):
        cap = min(by, self._prev_due)
        rem_on_hand = max(0, self._lbs_produced_by(cap) - self._prev_lbs)
        return min(rem_on_hand, self._safety)

    def _calc_rem_by(self, by: datetime):
        on_hand = self._lbs_produced_by(by)
        sfty_use = self._get_safety_use(by)
        prev_added = max(0, self._prev_lbs - on_hand)
        cum_lbs = max(0, self._total_lbs + sfty_use - on_hand)
        reg_lbs = max(0, self._total_lbs + sfty_use - on_hand - prev_added)
        excess = max(0, on_hand - self._total_lbs - sfty_use)
        return DemandQty(cumulative=cum_lbs, regular=reg_lbs, safety=self._safety-sfty_use,
                         excess=excess)
    
    def _recalculate(self):
        for d in self._demand_cache.keys():
            self._demand_cache[d] = self._calc_rem_by(d)
        
        if not self._jobs:
            self._lbs_remaining = self._init_lbs_remaining
        else:
            last_date = self._jobs[-1].end
            self._lbs_remaining = self._calc_rem_by(last_date)
    
    @property
    def id(self):
        return self._id
    
    @property
    def prefix(self):
        return 'Order'
    
    @property
    def item(self):
        return self._item
    
    @property
    def due_date(self):
        return self._due_date
    
    def update(self, value):
        idx = bisect_right(self._jobs, value.end, key=lambda j: j.end)
        self._jobs.insert(idx, value)
        self._recalculate()
    
    def remaining(self, by: datetime | None = None):
        if by is None:
            return self._lbs_remaining

        if by not in self._demand_cache:
            self._demand_cache[by] = self._calc_rem_by(by)

        return self._demand_cache[by]

    def late_table(self) -> list[tuple[timedelta, float]]:
        result: list[tuple[timedelta, float]] = []
        cum = 0.0
        for job in self._jobs:
            if cum >= self._total_lbs:
                break
            cum_after = cum + job.lbs
            lo = max(cum, self._prev_lbs)
            hi = min(cum_after, self._total_lbs)
            contribution = hi - lo
            if contribution > 0 and job.end > self._due_date:
                result.append((job.end - self._due_date, contribution))
            cum = cum_after
        return result