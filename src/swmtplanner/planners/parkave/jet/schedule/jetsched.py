#!/usr/bin/env python

import datetime as dt

from swmtplanner.support import FloatRange, DateRange
from swmtplanner.swmttypes.products.fabric.color import Shade
from swmtplanner.swmttypes.schedule import Schedule

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

class JetSched(Schedule, read_only=('jet','n_ports','jss','mss','current')):

    def __init__(self, jet_id, n_ports, date_rng, days_open = FloatRange(0, 5)):
        if jet_id not in globals()['_CTRS']:
            globals()['_CTRS'][jet_id] = 0
        globals()['_CTRS'][jet_id] += 1
        sched_id = globals()['_CTRS'][jet_id]
        super().__init__('JetSChed', sched_id, date_rng, FloatRange(0, 24),
                         days_open, _jet=jet_id, _n_ports=n_ports, _jss=0,
                         _mss=Shade.EMPTY, _current=False)
        
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
    
    def can_add_lots(self, lots, cycle_time: dt.timedelta):
        pass