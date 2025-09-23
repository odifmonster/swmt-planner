#!/usr/bin/env python

import datetime as dt

from swmtplanner.support import SwmtBase, HasID, FloatRange
from .schedule import JetSched, DyeCycle, DyeCycleView

class Jet(SwmtBase, HasID[str],
          read_only=('prefix','id','n_ports','load_rng',
                     'date_rng','days_open'),
          priv=('sched',)):
    
    def __init__(self, id, n_ports, load_rng, date_rng,
                 days_open = FloatRange(0, 5)):
        init_sched = JetSched(id, n_ports, date_rng, days_open=days_open)
        SwmtBase.__init__(self, _prefix='Jet', _id=id, _n_ports=n_ports,
                          _load_rng=load_rng, _date_rng=date_rng,
                          _days_open=days_open, _sched=init_sched)
    
    def _get_next_item1(self, frozen, moveable, newidx, curidx, cursched):
        if curidx == newidx:
            return 'new job'
        if not frozen:
            return moveable.pop(0)
        if not moveable:
            return frozen.pop(0)
        
        if frozen[0].start <= moveable[0].start or \
            cursched.expected_end(moveable[0].lots) > frozen[0].min_date:
            return frozen.pop(0)
        return moveable.pop(0)
    
    def _get_next_item2(self, frozen, moveable, cursched):
        if not frozen:
            return moveable.pop(0)
        if not moveable:
            return frozen.pop(0)
        
        if frozen[0].start <= moveable[0].start or \
            cursched.expected_end(moveable[0].lots) > frozen[0].min_date:
            return frozen.pop(0)
        return moveable.pop(0)
        
    @property
    def jobs(self):
        return self._sched.jobs
    
    @property
    def prod_jobs(self):
        return self._sched.prod_jobs
    
    def get_start_idx(self, due_date: dt.datetime):
        pjobs = self.prod_jobs
        i = len(pjobs)
        while i > 0:
            prev_end = self._sched.nearest_time_open(pjobs[i-1].end)
            if prev_end + dt.timedelta(weeks=3) < due_date:
                break
            i -= 1
        return i
    
    def try_modify(self, idx: int, lots = None):
        pjobs = self.prod_jobs
        if lots is None:
            if idx < 0 or idx >= len(pjobs):
                raise IndexError(f'Index {idx} out of bounds for schedule with' + \
                                 f' {len(pjobs)} jobs')
            if not pjobs[idx].moveable:
                raise ValueError(f'Job at index {idx} ({repr(pjobs[idx])}) is not moveable')
            pjobs = pjobs[:idx] + pjobs[idx+1:]

        frozen = list(filter(lambda j: not j.moveable, pjobs))
        moveable = list(filter(lambda j: j.moveable, pjobs))

        curidx = 0
        newsched = JetSched(self.id, self.n_ports, self.date_rng, days_open=self.days_open)
        newjobs = []
        kicked = []
        if lots is None:
            kicked.append(pjobs[idx])

        while moveable and frozen:
            if lots is not None:
                nxt_item = self._get_next_item1(frozen, moveable, idx, curidx,
                                                newsched)
            else:
                nxt_item = self._get_next_item2(frozen, moveable, newsched)
            if type(nxt_item) is str:
                if type(lots) is not list:
                    lots2 = lots.lots
                else:
                    lots2 = lots
                if not newsched.can_add_lots(lots2):
                    return None, [], []
                
                newjobs += newsched.add_lots(lots, dt.timedelta(), idx=idx)
            elif not nxt_item.moveable:
                if not newsched.can_add_lots(nxt_item.lots):
                    return None, [], []
                newsched.add_job(nxt_item, force=True)
            else:
                if not newsched.can_add_lots(nxt_item.lots):
                    kicked.append(nxt_item)
                else:
                    prev_lots = newsched.get_prev_lots(nxt_item.lots)
                    start = newsched.end
                    for l in prev_lots:
                        newjob = DyeCycle([l], start, idx=-1)
                        newjobs.append(newjob)
                        newsched.add_job(newjob, force=True)
                        start = newsched.end
                    newjob = nxt_item.copy_lots(start, nxt_item.cycle_time, True)
                    newjobs.append(newjob)
            
            curidx += 1

        if curidx == idx and lots is not None:
            if not newsched.can_add_lots(lots):
                return None, [], []
            newjobs += newsched.add_lots(lots, dt.timedelta(), idx=idx)
        
        return newsched, newjobs, kicked
    
    def set_sched(self, newsched: JetSched):
        self._sched.deactivate()
        temp = self._sched
        newsched.activate()
        self._sched = newsched
        return temp