#!/usr/bin/env python

from swmtplanner.support import SwmtBase, HasID
from swmtplanner.swmttypes.product import BeamSet

class Machine(SwmtBase, HasID[str],
              read_only=('id','cal','item','top_set','btm_set'),
              priv=('jobs',)):
    
    def __init__(self, name, cal, item, top_rem, btm_rem):
        SwmtBase.__init__(self, _id=name, _cal=cal, _item=item,
                          _top_set=BeamSet(item.top_set, top_rem),
                          _btm_set=BeamSet(item.btm_set, btm_rem),
                          _jobs=[])
    
    @property
    def jobs(self):
        return tuple(self._jobs)
        
    @property
    def last_job_end(self):
        if not self._jobs:
            return self.cal.start
        return self._jobs[-1].end
        
    def next_runout(self):
        start = self.last_job_end
        rate = self.item.get_rate_on(self.id)

        top_lbs = self.top_set.rem_lbs_by(start)
        btm_lbs = self.btm_set.rem_lbs_by(start)

        # Scale remaining lbs by each beam's share of the total fabric weight
        top_hrs = (top_lbs / self.item.top_pct) / rate
        btm_hrs = (btm_lbs / self.item.btm_pct) / rate

        if top_hrs <= btm_hrs:
            return ('top_ro', self.cal.add_work_hrs(start, top_hrs))
        else:
            return ('btm_ro', self.cal.add_work_hrs(start, btm_hrs))
    
    def next_decisions(self):
        return [('job_end', self.last_job_end), self.next_runout()]
    
    def get_runouts(self, start, rolls, apply_changes = False):
        CHANGEOVER_HRS = 3.0
        INIT_LBS = {70: 1800, 75: 1800, 40: 2800, 45: 2800}

        def fresh_beam(spent: BeamSet) -> BeamSet:
            return BeamSet(spent.name, INIT_LBS[spent.denier])

        runouts = []
        rate = self.item.get_rate_on(self.id)
        tgt_wt = self.item.tgt_wt
        current = start

        top_beam = self.top_set
        btm_beam = self.btm_set
        top_rem = self.top_set.rem_lbs_by(start)
        btm_rem = self.btm_set.rem_lbs_by(start)

        while rolls > 0:
            top_hrs = (top_rem / self.item.top_pct) / rate
            btm_hrs = (btm_rem / self.item.btm_pct) / rate
            next_hrs = min(top_hrs, btm_hrs)

            lbs_until_runout = next_hrs * rate
            full_rolls_until_runout = int(lbs_until_runout / tgt_wt)

            if full_rolls_until_runout >= rolls:
                completion_dt = self.cal.add_work_hrs(current, (rolls * tgt_wt) / rate)
                return runouts, completion_dt

            # Credit all full rolls completed before the runout, then run to
            # beam exhaustion (the trailing partial roll is produced but not credited)
            rolls -= full_rolls_until_runout
            runout_hrs = next_hrs

            if top_hrs <= btm_hrs:
                runout_dt = self.cal.add_work_hrs(current, runout_hrs)
                runouts.append(('top', runout_dt))
                current = self.cal.add_work_hrs(runout_dt, CHANGEOVER_HRS)
                top_beam = fresh_beam(top_beam)
                if apply_changes:
                    self._top_set = top_beam
                top_rem = INIT_LBS[self.top_set.denier] * self.item.top_pct
                btm_rem -= lbs_until_runout * self.item.btm_pct
            else:
                runout_dt = self.cal.add_work_hrs(current, runout_hrs)
                runouts.append(('btm', runout_dt))
                current = self.cal.add_work_hrs(runout_dt, CHANGEOVER_HRS)
                btm_beam = fresh_beam(btm_beam)
                if apply_changes:
                    self._btm_set = btm_beam
                btm_rem = INIT_LBS[self.btm_set.denier] * self.item.btm_pct
                top_rem -= lbs_until_runout * self.item.top_pct

        return runouts, current