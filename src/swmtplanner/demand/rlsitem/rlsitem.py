#!/usr/bin/env python

from datetime import datetime, timedelta, date
from bisect import bisect_right
from math import ceil

from ...support import HasID
from ...products import Greige
from ...schedule import Job
from ..order import Order

class RlsItem(HasID[str]):
    
    def __init__(self, item: Greige, on_hand: float, weekly_use: list[float], start_day: int):
        self._id = item.id
        self._item = item
        self._start_day = start_day
        self._orders: list[Order] = []

        safety = item.safety

        if weekly_use:
            due_date = datetime.fromordinal(start_day)
            wk0_lbs = weekly_use[0]

            x1 = wk0_lbs - on_hand
            wk0_lbs = max(0, x1)
            on_hand = min(0, x1) * -1

            if x1 < 0 and safety > 0:
                x2 = safety - on_hand
                safety = max(0, x2)
                on_hand = min(0, x2) * -1
            
            self._orders.append(Order(item, due_date, 0, wk0_lbs, 0, due_date - timedelta(weeks=1),
                                      safety, on_hand))
            
            total_lbs = wk0_lbs
            prev_added = wk0_lbs

            for i, lbs in enumerate(weekly_use):
                if i == 0: continue

                due_date = datetime.fromordinal(start_day + i * 7)
                cur_lbs = max(0, total_lbs + lbs - prev_added - on_hand)
                excess = max(0, on_hand - total_lbs - lbs)
                cur_order = Order(item, due_date, i, cur_lbs, prev_added,
                                  datetime.fromordinal(start_day + (i - 1) * 7),
                                  safety, excess)
                
                total_lbs += lbs
                prev_added += cur_lbs
                self._orders.append(cur_order)

            self._safety = None
        else:
            self._safety = max(0, safety - on_hand)
        
        self._jobs: list[Job] = []

    @property
    def id(self):
        return self._id
    
    @property
    def prefix(self):
        return 'RlsItem'
    
    @property
    def orders(self):
        return tuple(self._orders)
    
    @property
    def safety(self):
        if not self._safety is None:
            return self._safety
        return self._orders[-1].remaining().safety
    
    def assign(self, job: Job):
        self._safety
        idx = bisect_right(self._jobs, job.end, key=lambda j: j.end)
        self._jobs.insert(idx, job)
        for o in self._orders:
            o.update(job)
    
    def demand(self, year: int, week: int, by: datetime | None = None):
        monday = date.fromisocalendar(year, week, 1).toordinal()
        day_offset = monday - self._start_day
        if day_offset < 0:
            raise ValueError('provided week is before the start of the current release window')
        wk_offset = day_offset // 7

        if wk_offset >= len(self._orders):
            raise ValueError('provided week is outside the bounds of the current release window')
        
        return self._orders[wk_offset].remaining(by=by)