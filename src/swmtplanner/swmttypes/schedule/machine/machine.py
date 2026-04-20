#!/usr/bin/env python

from swmtplanner.support import SwmtBase, HasID
from swmtplanner.swmttypes.product import BeamSet, Greige
from swmtplanner.swmttypes.schedule import Job

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
    
    def get_runouts(self, start, rolls, item, apply_changes = False):
        CHANGEOVER_HRS = 3.0
        TAPEOUT_HRS = 6.0
        INIT_LBS = {70: 1800, 75: 1800, 40: 2800, 45: 2800}

        def denier_from_name(name: str) -> int:
            return int(name[:2])

        def fresh_beam(spent: BeamSet) -> BeamSet:
            return BeamSet(spent.name, INIT_LBS[denier_from_name(spent.name)])

        # Apply any tape-outs or beam changes required before knitting item
        top_beam = self.top_set
        btm_beam = self.btm_set
        current = start

        for change_type, new_beam_name, _ in self.get_tapeouts(item):
            if change_type in ('top_to', 'top_chg'):
                hrs = TAPEOUT_HRS if change_type == 'top_to' else CHANGEOVER_HRS
                current = self.cal.add_work_hrs(current, hrs)
                top_beam = BeamSet(new_beam_name, INIT_LBS[denier_from_name(new_beam_name)])
                if apply_changes:
                    self._top_set = top_beam
            else:  # 'btm_to', 'btm_chg'
                hrs = TAPEOUT_HRS if change_type == 'btm_to' else CHANGEOVER_HRS
                current = self.cal.add_work_hrs(current, hrs)
                btm_beam = BeamSet(new_beam_name, INIT_LBS[denier_from_name(new_beam_name)])
                if apply_changes:
                    self._btm_set = btm_beam

        runouts = []
        rate = item.get_rate_on(self.id)
        tgt_wt = item.tgt_wt
        top_rem = top_beam.rem_lbs_by(current)
        btm_rem = btm_beam.rem_lbs_by(current)

        while rolls > 0:
            top_hrs = (top_rem / item.top_pct) / rate
            btm_hrs = (btm_rem / item.btm_pct) / rate
            next_hrs = min(top_hrs, btm_hrs)

            lbs_until_runout = next_hrs * rate
            full_rolls_until_runout = int(lbs_until_runout / tgt_wt)

            if full_rolls_until_runout >= rolls:
                completion_dt = self.cal.add_work_hrs(current, (rolls * tgt_wt) / rate)
                return runouts, completion_dt

            rolls -= full_rolls_until_runout

            if top_hrs <= btm_hrs:
                runout_dt = self.cal.add_work_hrs(current, next_hrs)
                runouts.append(('top_ro', runout_dt))
                current = self.cal.add_work_hrs(runout_dt, CHANGEOVER_HRS)
                top_beam = fresh_beam(top_beam)
                if apply_changes:
                    self._top_set = top_beam
                top_rem = INIT_LBS[denier_from_name(top_beam.name)] * item.top_pct
                btm_rem -= lbs_until_runout * item.btm_pct
            else:
                runout_dt = self.cal.add_work_hrs(current, next_hrs)
                runouts.append(('btm_ro', runout_dt))
                current = self.cal.add_work_hrs(runout_dt, CHANGEOVER_HRS)
                btm_beam = fresh_beam(btm_beam)
                if apply_changes:
                    self._btm_set = btm_beam
                btm_rem = INIT_LBS[denier_from_name(btm_beam.name)] * item.btm_pct
                top_rem -= lbs_until_runout * item.top_pct

        return runouts, current
    
    def get_tapeouts(self, item: Greige):
        ret = []
        if self.item.top_set != item.top_set:
            suff = 'to' if self.top_set.lbs > 0 else 'chg'
            ret.append(('top_'+suff, item.top_set, self.last_job_end))
        if self.item.btm_set != item.btm_set:
            suff = 'to' if self.btm_set.lbs > 0 else 'chg'
            ret.append(('btm_'+suff, item.btm_set, self.last_job_end))
        return ret

    def add_job(self, item: Greige, rolls: int):
        """
        Creates a new Job for the given item and number of rolls and appends it
        to this machine's schedule.

        item:
            The Greige style to knit.
        rolls:
            The number of usable rolls to produce.

        Returns the newly created Job.
        """
        CHANGEOVER_HRS = 3.0
        TAPEOUT_HRS = 6.0

        # Collect the tape-outs/beam changes needed to start knitting item
        changes = self.get_tapeouts(item)

        # Start from whenever the machine is next free, then offset by changeovers
        current = self.last_job_end
        for change_type, _, _ in changes:
            hrs = TAPEOUT_HRS if change_type in ('top_to', 'btm_to') else CHANGEOVER_HRS
            current = self.cal.add_work_hrs(current, hrs)

        job_start = current

        # Run the simulation with apply_changes=True
        runouts, completion_dt = self.get_runouts(self.last_job_end, rolls, item, apply_changes=True)

        # Calculate lbs consumed from each beam set over the job
        rate = item.get_rate_on(self.id)
        total_hrs = self.cal.get_work_hrs_between(job_start, completion_dt)

        # Add back changeover downtime to get true production hours per beam segment
        changeover_count = len(runouts)
        production_hrs = total_hrs - (changeover_count * CHANGEOVER_HRS)

        total_lbs = production_hrs * rate
        lbs_used_top = total_lbs * item.top_pct
        lbs_used_btm = total_lbs * item.btm_pct
        lbs_prod = rolls * item.tgt_wt

        # end is after the last changeover if the job ends on a runout,
        # otherwise it is the completion datetime
        if runouts:
            last_runout_dt = runouts[-1][1]
            end_dt = self.cal.add_work_hrs(last_runout_dt, CHANGEOVER_HRS)
            # If completion falls after the last changeover the job finished normally
            if completion_dt > end_dt:
                end_dt = completion_dt
        else:
            end_dt = completion_dt

        job = Job(
            item=item,
            start=job_start,
            end=end_dt,
            lbs_used_top=lbs_used_top,
            lbs_used_btm=lbs_used_btm,
            lbs_prod=lbs_prod,
            changes=changes,
            run_outs=[(side, dt) for side, dt in runouts],
        )

        self.jobs.append(job)
        return job