#!/usr/bin/env python

from datetime import datetime, timedelta, date
from bisect import bisect_right
from collections import namedtuple

from ...support import HasID
from ...products import Greige
from ...schedule import Job
from ..order import Order

Safety = namedtuple('Safety', ['item', 'lbs'])

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
            
            prev_pairs: list[tuple[float, datetime]] = [(wk0_lbs, due_date)]
            self._orders.append(Order(item, 0, prev_pairs, safety, on_hand))
            
            total_lbs = wk0_lbs
            prev_added = wk0_lbs

            for i, lbs in enumerate(weekly_use):
                if i == 0: continue

                due_date = datetime.fromordinal(start_day + i * 7)
                cur_lbs = max(0, total_lbs + lbs - prev_added - on_hand)
                excess = max(0, on_hand - total_lbs - lbs)
                prev_pairs.append((cur_lbs, due_date))

                cur_order = Order(item, i, prev_pairs, safety, excess)
                
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
    def item(self):
        return self._item
    
    @property
    def orders(self):
        return tuple(self._orders)
    
    @property
    def safety(self):
        if not self._safety is None:
            lbs = self._safety
        else:
            lbs = self._orders[-1].remaining().safety
        return Safety(item=self.item, lbs=lbs)
    
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