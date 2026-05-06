#!/usr/bin/env python

from ...support import HasID
from ...products import Greige
from ...schedule import Job

class RlsItem(HasID[str]):

    def __init__(self, item: Greige, on_hand: float, start_week: int, weekly_use: list[float]):
        self._item = item
        self._on_hand = on_hand
        self._start_week = start_week
        self._weekly_use = weekly_use
        self._jobs: list[Job] = []
        self._recalculate()

    def _recalculate(self):
        total_jobs = sum(j.lbs for j in self._jobs)
        effective_on_hand = self._on_hand + total_jobs

        cum_needed = 0
        cum_added = 0
        self._demand = []
        for amt in self._weekly_use:
            cum_needed += amt
            cur_needed = max(0, cum_needed - effective_on_hand - cum_added)
            self._demand.append(cur_needed)
            cum_added += cur_needed

        self._safety = max(0, self._item.safety - effective_on_hand)

    @property
    def id(self):
        return self._item.id

    @property
    def prefix(self):
        return 'RlsItem'

    @property
    def item(self):
        return self._item

    @property
    def safety(self):
        return self._safety

    def demand(self, week):
        return self._demand[week - self._start_week]

    def assign(self, job: Job):
        if job.item != self.item:
            raise ValueError(f'cannot assign {repr(job)} to {repr(self)}')

        self._jobs.append(job)
        self._recalculate()
