#!/usr/bin/env python

import datetime as dt

from swmtplanner.support import FloatRange, DateRange
from swmtplanner.swmttypes.products import fabric, GreigeStyle
from swmtplanner.swmttypes.products.fabric.color import Shade
from swmtplanner.swmttypes.schedule import Schedule
from .dyecycle import DyeCycle, DyeCycleView
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
    
    def can_add_lots(self, new: list[DyeLot] | DyeCycleView, _: dt.timedelta):
        start = self.end
        if type(new) is not list:
            _lots = new.lots
        else:
            _lots = new
        prev_lots: list[DyeLot] = self.get_prev_lots(_lots)

        for l in prev_lots:
            if not self.can_add_cycle(start, l.cycle_time):
                return False
            start = self.nearest_time_open(start + l.cycle_time)

        start = max(self.nearest_time_open(max(map(lambda l: l.received, _lots))),
                    start)
        return self.can_add_cycle(start, _lots[0].cycle_time)
    
    def add_lots(self, new: list[DyeLot] | DyeCycleView, _, idx = None):
        start = self.end
        if type(new) is not list:
            _lots = new.lots

        prev_lots: list[DyeLot] = self.get_prev_lots(_lots)
        new_jobs: list[DyeCycle] = []

        for l in prev_lots:
            cur_job = DyeCycle([l], start, idx=-1)
            new_jobs.append(cur_job)
            self.add_job(cur_job)
        
        start = max(self.nearest_time_open(max(map(lambda l: l.received, _lots))),
                    start)
        if type(new) is not list:
            cur_job = new.copy_lots(start, dt.timedelta(), True, idx=idx)
        else:
            cur_job = DyeCycle(new, start, idx=idx)
            
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

    def get_costs(self, nweeks: int):
        pjobs = self.prod_jobs
        total_ports = max(1, len(pjobs) * self.n_ports)
        cost_port_12_hours = 150

        all_jobs: list[DyeCycleView] = self.jobs

        def is_non_prod(j: DyeCycleView):
            if j.shade in (Shade.STRIP, Shade.HEAVYSTRIP):
                return True
            return not j.moveable and j.shade == Shade.EMPTY
        
        non_prod_jobs = list(filter(is_non_prod, all_jobs))

        strip_cost = 0
        empty_cost = 0
        for j in non_prod_jobs:
            hrs = (j.end - j.start).total_seconds() / 3600
            cur_cost = cost_port_12_hours * self.n_ports * (hrs / 12)
            if j.shade == Shade.EMPTY:
                empty_cost += cur_cost
            else:
                strip_cost += cur_cost
        
        total_lbs = map(lambda j: sum(map(lambda l: l.qty.lbs, j.lots)),
                        pjobs)
        ndays = nweeks * 5
        max_lbs = 36000 * self.n_ports / 39
        over_max = max(0, total_lbs / ndays - max_lbs)
        
        return strip_cost / total_ports, empty_cost, over_max
    
    def freed_greige(self):
        avail: dict[GreigeStyle, list] = {}
        pjobs: list[DyeCycleView] = self.prod_jobs
        for job in pjobs:
            for lot in job.lots:
                if not lot.start is None: continue
                if lot.rawmat not in avail:
                    avail[lot.rawmat] = []
                avail[lot.rawmat] += list(lot.ports)
        return avail