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
    
    def can_add_cycle(self, min_date, cycle_time):
        start = max(self.end_in_schedule(min_date), self.end)
        return start + cycle_time <= self.date_rng.maxval + dt.timedelta(hours=2)
    
    def can_add_lots(self, lots: list[DyeLot], _: dt.timedelta):
        strip_name = lots[0].color.get_needed_strip(self.jss, self.mss)
        start = self.nearest_time_open(max(map(lambda l: l.received, lots)))
        start = max(self.end, start)

        if strip_name is not None:
            strip = fabric.ITEMS[strip_name]
            if not self.can_add_cycle(start, strip.cycle_time):
                return False
            start = self.nearest_time_open(start + strip.cycle_time)
        
        if lots[0].shade == Shade.LIGHT1 and strip_name is not None:
            empty = fabric.ITEMS['EMPTY']
            if not self.can_add_cycle(start, empty.cycle_time):
                return False
            start = self.nearest_time_open(start + empty.cycle_time)

        return self.nearest_time_open(start + lots[0].cycle_time) \
            <= self.date_rng.maxval + dt.timedelta(hours=2)
    
    def add_lots(self, lots: list[DyeLot], _, idx = None):
        strip_name = lots[0].color.get_needed_strip(self.jss, self.mss)
        start = self.nearest_time_open(max(map(lambda l: l.received, lots)))
        start = max(self.end, start)
        newjobs = []

        if strip_name is not None:
            strip = fabric.ITEMS[strip_name]
            strip_lot = DyeLot.new_strip(strip)
            strip_job = DyeCycle([strip_lot], start, moveable=True,
                                 idx=-1)
            self.add_job(strip_job)
            newjobs.append(strip_job)
            start = self.end

        if lots[0].shade == Shade.LIGHT1 and strip_name is not None:
            empty = fabric.ITEMS['EMPTY']
            empty_lot = DyeLot.new_strip(empty)
            empty_job = DyeCycle([empty_lot], start, moveable=True, idx=-1)
            self.add_job(empty_job)
            newjobs.append(empty_job)
            start = self.end

        newjob = DyeCycle(lots, start, moveable=True, idx=idx)
        self.add_job(newjob)
        newjobs.append(newjob)

        return newjobs

    def add_job(self, job: DyeCycle, force = False):
        super().add_job(job, force=force)

        if job.shade in (Shade.STRIP, Shade.HEAVYSTRIP):
            self._jss = 0
            self._mss = job.shade
        else:
            self._jss += 1
            self._mss = _max_shade(self.mss, job.shade)