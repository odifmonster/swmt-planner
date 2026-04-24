#!/usr/bin/env python

from collections import namedtuple
from datetime import datetime

from swmtplanner.support import SwmtBase, HasID
from swmtplanner.swmttypes.product import BeamSet, Greige
from swmtplanner.swmttypes.demand import Req
from swmtplanner.swmttypes.schedule import Job

_BEAM_LBS: dict[int, float] = {40: 2800, 45: 2800, 70: 1800, 75: 1800}

def _denier_from_name(name: str) -> int:
    return int(name[:2])

Decision = namedtuple('Decision', ['mchn_id', 'kind', 'date'])
Stop = namedtuple('Stop', ['mchn_id', 'reason', 'item', 'start', 'end'])

class Machine(SwmtBase, HasID[str],
              read_only=('id','is_old','cal','top_set','btm_set'),
              priv=('last_item','jobs')):
    
    def __init__(self, name, is_old, cal, item, top_rem, btm_rem):
        SwmtBase.__init__(self, _id=name, _is_old=is_old, _cal=cal, _last_item=item,
                          _top_set=BeamSet(item.top_set, top_rem),
                          _btm_set=BeamSet(item.btm_set, btm_rem),
                          _last_item=item, _jobs=[])
    
    @property
    def jobs(self):
        return tuple(self._jobs)
        
    @property
    def last_job_end(self):
        if not self._jobs:
            return self.cal.start
        return self._jobs[-1].end
    
    @property
    def last_item(self):
        if not self._jobs:
            return self._last_item
        return self._jobs[-1].item
    
    def next_runout(self) -> Decision:
        rate = self.last_item.get_rate_on(self.id)  # lbs/hour total
        top_rate = rate * self.last_item.top_pct     # lbs/hour on top bar
        btm_rate = rate * self.last_item.btm_pct     # lbs/hour on btm bar

        top_hrs = self.top_rem / top_rate
        btm_hrs = self.btm_rem / btm_rate

        top_end = self.cal.add_work_hrs(self.last_job_end, top_hrs)
        btm_end = self.cal.add_work_hrs(self.last_job_end, btm_hrs)

        if top_end <= btm_end:
            return Decision(mchn_id=self.id, kind='TOP_RUNOUT', date=top_end)
        else:
            return Decision(mchn_id=self.id, kind='BTM_RUNOUT', date=btm_end)
    
    def next_decisions(self):
        return [Decision(mchn_id=self.id, kind='JOB_END', date=self.last_job_end),
                self.next_runout()]
    
    def get_stops(
        self,
        item: Greige,
        wait_for_runout: bool = False
    ) -> list[Stop]:
        stops = []
        current = self.last_job_end

        next_ro = self.next_runout()
        if wait_for_runout:
            current = next_ro.date
            top_needs_load = next_ro.kind == 'TOP_RUNOUT'
            btm_needs_load = next_ro.kind == 'BTM_RUNOUT'
        else:
            top_needs_load = next_ro.kind == 'TOP_RUNOUT' and next_ro.date == self.last_job_end
            btm_needs_load = next_ro.kind == 'BTM_RUNOUT' and next_ro.date == self.last_job_end

        # Determine which bars need a tape out
        top_needs_tape = item.top_set != self.top_set.name and not top_needs_load
        btm_needs_tape = item.btm_set != self.btm_set.name and not btm_needs_load

        # Tape outs (sequential)
        if top_needs_tape:
            end = self.cal.add_work_hrs(current, 4.0)
            stops.append(Stop(mchn_id=self.id, reason='TOP_TAPE_OUT', item='N/A',
                            start=current, end=end))
            current = end

        if btm_needs_tape:
            end = self.cal.add_work_hrs(current, 4.0)
            stops.append(Stop(mchn_id=self.id, reason='BTM_TAPE_OUT', item='N/A',
                            start=current, end=end))
            current = end

        # Loads (sequential, only needed after tape out or runout)
        if top_needs_tape or top_needs_load:
            end = self.cal.add_work_hrs(current, 2.0)
            stops.append(Stop(mchn_id=self.id, reason='LOAD_TOP_BAR', item=item.top_set,
                            start=current, end=end))
            current = end

        if btm_needs_tape or btm_needs_load:
            end = self.cal.add_work_hrs(current, 2.0)
            stops.append(Stop(mchn_id=self.id, reason='LOAD_BTM_BAR', item=item.btm_set,
                            start=current, end=end))
            current = end

        # Style/family change — always recorded, but concurrent with tape outs
        # and loads so does not add additional time when those are present
        if item.family != self.last_item.family:
            duration = (1.0 if self.is_old else 0.25) if not (
                top_needs_tape or btm_needs_tape or top_needs_load or btm_needs_load
            ) else 0.0
            end = self.cal.add_work_hrs(current, duration)
            stops.append(Stop(mchn_id=self.id, reason='FAMILY_CHANGE', item=item.id,
                            start=current, end=end))
        elif item != self.last_item:
            duration = 0.25 if not (
                top_needs_tape or btm_needs_tape or top_needs_load or btm_needs_load
            ) else 0.0
            end = self.cal.add_work_hrs(current, duration)
            stops.append(Stop(mchn_id=self.id, reason='STYLE_CHANGE', item=item.id,
                            start=current, end=end))

        return stops

    def get_all_events(
        self,
        item: Greige,
        rolls: int,
        wait_for_runout: bool = False
    ) -> tuple[list[Decision], list[Stop], datetime, datetime]:
        rate = item.get_rate_on(self.id)
        top_rate = rate * item.top_pct
        btm_rate = rate * item.btm_pct
        roll_rate = rate / item.tgt_wt

        runouts = []
        stops = self.get_stops(item, wait_for_runout)

        # Start is the end of the last stop, or last_job_end if no stops
        start = stops[-1].end if stops else self.last_job_end

        # Initialize remaining lbs, accounting for partial consumption
        # of the surviving bar if we waited for a runout
        top_rem = self.top_set.rem_lbs_by(start)
        btm_rem = self.btm_set.rem_lbs_by(start)

        if wait_for_runout:
            next_ro = self.next_runout()
            if next_ro.kind == 'TOP_RUNOUT':
                top_rem = _BEAM_LBS[self.top_set.denier]
                if item.btm_set == self.btm_set.name:
                    btm_rem -= self.cal.get_work_hrs_between(self.last_job_end, next_ro.date) * btm_rate
                else:
                    btm_rem = _BEAM_LBS[self.btm_set.denier]
            else:
                btm_rem = _BEAM_LBS[self.btm_set.denier]
                if item.top_set == self.top_set.name:
                    top_rem -= self.cal.get_work_hrs_between(self.last_job_end, next_ro.date) * top_rate
                else:
                    top_rem = _BEAM_LBS[self.top_set.denier]

        current = start
        rolls_remaining = rolls

        while rolls_remaining > 0:
            hrs_needed = rolls_remaining / roll_rate

            top_hrs = top_rem / top_rate
            btm_hrs = btm_rem / btm_rate

            if top_hrs >= hrs_needed and btm_hrs >= hrs_needed:
                current = self.cal.add_work_hrs(current, hrs_needed)
                break

            if top_hrs <= btm_hrs:
                ro_hrs = top_hrs
                ro_kind = 'TOP_RUNOUT'
                load_reason = 'LOAD_TOP_BAR'
            else:
                ro_hrs = btm_hrs
                ro_kind = 'BTM_RUNOUT'
                load_reason = 'LOAD_BTM_BAR'

            rolls_before_ro = int(ro_hrs * roll_rate)
            rolls_remaining -= rolls_before_ro

            ro_date = self.cal.add_work_hrs(current, ro_hrs)
            runouts.append(Decision(mchn_id=self.id, kind=ro_kind, date=ro_date))

            # Add the beam loading stop
            load_end = self.cal.add_work_hrs(ro_date, 2.0)
            new_beam = item.top_set if load_reason == 'LOAD_TOP_BAR' else item.btm_set
            stops.append(Stop(mchn_id=self.id, reason=load_reason, item=new_beam,
                            start=ro_date, end=load_end))

            current = load_end
            if ro_kind == 'TOP_RUNOUT':
                top_rem = _BEAM_LBS[self.top_set.denier]
                btm_rem -= ro_hrs * btm_rate
            else:
                btm_rem = _BEAM_LBS[self.btm_set.denier]
                top_rem -= ro_hrs * top_rate

        return runouts, stops, start, current
    
    def schedule_job(self, stops: list[Stop], job: Job) -> None:
        # Add pre-job stops to the schedule and update beamsets as needed
        for stop in stops:
            self._sched.append(stop)
            if stop.reason == 'LOAD_TOP_BAR':
                self._top_set = BeamSet(stop.item, _BEAM_LBS[_denier_from_name(stop.item)])
            elif stop.reason == 'LOAD_BTM_BAR':
                self._btm_set = BeamSet(stop.item, _BEAM_LBS[_denier_from_name(stop.item)])

        # Build a timeline of production intervals, broken up by mid-job stops
        interval_start = job.start
        for stop in sorted(job.stops, key=lambda s: s.start):
            if interval_start < stop.start:
                self.top_set.use(job.item, self.id, 'top', interval_start, stop.start)
                self.btm_set.use(job.item, self.id, 'btm', interval_start, stop.start)
            if stop.reason == 'LOAD_TOP_BAR':
                self._top_set = BeamSet(stop.item, _BEAM_LBS[_denier_from_name(stop.item)])
            elif stop.reason == 'LOAD_BTM_BAR':
                self._btm_set = BeamSet(stop.item, _BEAM_LBS[_denier_from_name(stop.item)])
            interval_start = stop.end

        # Log beam usage for the final interval
        if interval_start < job.end:
            self.top_set.use(job.item, self.id, 'top', interval_start, job.end)
            self.btm_set.use(job.item, self.id, 'btm', interval_start, job.end)

        self._sched.append(job)