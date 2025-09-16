#!/usr/bin/env python

import datetime as dt

from swmtplanner.support import FloatRange, DateRange
from swmtplanner.swmttypes.products import fabric
from swmtplanner.swmttypes.products.fabric.color import Shade
from swmtplanner.swmttypes.schedule import Schedule
from .dyecycle import DyeCycle
from ...materials import DyeLot

_CTRS = {}

def _max_shade(shade1: Shade, shade2: Shade):
    if Shade.BLACK in (shade1, shade2):
        return Shade.BLACK
    if Shade.SOLUTION in (shade1, shade2):
        return Shade.SOLUTION
    if Shade.MEDIUM in (shade1, shade2):
        return Shade.MEDIUM
    if Shade.LIGHT2 in (shade1, shade2):
        return Shade.LIGHT2
    if Shade.LIGHT1 in (shade1, shade2):
        return Shade.LIGHT1
    if Shade.HEAVYSTRIP in (shade1, shade2):
        return Shade.HEAVYSTRIP
    if Shade.STRIP in (shade1, shade2):
        return Shade.STRIP
    return Shade.EMPTY

class JetSched(Schedule, read_only=('jet','n_ports','jss','mss')):

    def __init__(self, jet_id, n_ports, date_rng, days_open = FloatRange(0, 5)):
        if jet_id not in globals()['_CTRS']:
            globals()['_CTRS'][jet_id] = 0
        globals()['_CTRS'][jet_id] += 1
        sched_id = f'{jet_id}|{globals()['_CTRS'][jet_id]}'
        super().__init__('JetSched', sched_id, date_rng, FloatRange(0, 24),
                         days_open, _jet=jet_id, _n_ports=n_ports, _jss=0,
                         _mss=Shade.EMPTY)
        
    @property
    def end(self):
        raw_end = self.date_rng.minval
        if self._jobs:
            raw_end = max(self._jobs[-1].end, raw_end)
        return self.nearest_time_open(raw_end)
    
    @property
    def rem_time(self):
        if self.end >= self.date_rng.maxval:
            return dt.timedelta(seconds=0)
        return self.time_open(DateRange(self.end, self.date_rng.maxval))
        
    def get_prev_lots(self, lots: list[DyeLot]):
        prev = []

        strip_name = lots[0].color.get_needed_strip(self.jss, self.mss)
        if strip_name is not None:
            if strip_name == 'HEAVYSTRIP' and self.n_ports < 4:
                strip_name = 'STRIP'
            strip = fabric.ITEMS[strip_name]
            prev.append(DyeLot.new_strip(strip))
        
        if strip_name is not None and lots[0].color.shade == Shade.LIGHT1:
            prev.append(DyeLot.new_strip(fabric.ITEMS['EMPTY']))
        
        return prev
    
    def expected_end(self, lots: list[DyeLot]):
        prev_lots: list[DyeLot] = self.get_prev_lots(lots)
        start = self.end
        for l in prev_lots:
            start = self.nearest_time_open(start + l.cycle_time)
        start = max(self.nearest_time_open(max(map(lambda l: l.received, lots))),
                    start)
        return self.nearest_time_open(start + lots[0].cycle_time)
    
    def can_add_cycle(self, min_date, cycle_time):
        start = max(self.end_in_schedule(min_date), self.end)
        return start + cycle_time <= self.date_rng.maxval + dt.timedelta(hours=2)
    
    def can_add_lots(self, lots: list[DyeLot], _: dt.timedelta):
        start = self.end
        prev_lots: list[DyeLot] = self.get_prev_lots(lots)

        for l in prev_lots:
            if not self.can_add_cycle(start, l.cycle_time):
                return False
            start = self.nearest_time_open(start + l.cycle_time)

        start = max(self.nearest_time_open(max(map(lambda l: l.received, lots))),
                    start)
        return self.can_add_cycle(start, lots[0].cycle_time)
    
    def add_lots(self, lots: list[DyeLot], _, idx = None):
        start = self.end
        prev_lots: list[DyeLot] = self.get_prev_lots(lots)
        new_jobs: list[DyeCycle] = []

        for l in prev_lots:
            cur_job = DyeCycle([l], start, idx=-1)
            new_jobs.append(cur_job)
            self.add_job(cur_job)
        
        start = max(self.nearest_time_open(max(map(lambda l: l.received, lots))),
                    start)
        cur_job = DyeCycle(lots, start, idx=idx)
        new_jobs.append(cur_job)
        self.add_job(cur_job)

        return new_jobs

    def add_job(self, job: DyeCycle, force = False):
        super().add_job(job, force=force)

        if job.shade in (Shade.STRIP, Shade.HEAVYSTRIP):
            self._jss = 0
            self._mss = job.shade
        else:
            self._jss += 1
            self._mss = _max_shade(self.mss, job.shade)