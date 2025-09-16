#!/usr/bin/env python

import datetime as dt

from swmtplanner.support import SwmtBase, HasID, DateRange

def _floor_day(date: dt.datetime):
    return dt.datetime(date.year, date.month, date.day)

def _ceil_day(date: dt.datetime):
    if date.time() == dt.time.min:
        return date
    return _floor_day(date + dt.timedelta(days=1))

def _ceil_week(date: dt.datetime):
    if date.weekday() == 0:
        return date
    return date + dt.timedelta(days=7-date.weekday())

def _floor_week(date: dt.datetime):
    return date - dt.timedelta(days=date.weekday())

class Schedule(SwmtBase, HasID[str]):
    
    def __init_subclass__(cls, read_only = tuple(), priv = tuple()):
        super().__init_subclass__(
            read_only=('prefix','id','date_rng','hrs_open','days_open')+read_only,
            priv=('jobs',)+priv)
    
    def __init__(self, prefix, sched_id, date_rng, hrs_open, days_open):
        SwmtBase.__init__(self, _prefix=prefix, _id=sched_id, _date_rng=date_rng,
                          _hrs_open=hrs_open, _days_open=days_open, _jobs=[])

    @property
    def end(self):
        raise NotImplementedError()
    
    @property
    def rem_time(self):
        raise NotImplementedError()
    
    @property
    def jobs(self):
        return list(map(lambda j: j.view(), self._jobs))
    
    @property
    def prod_jobs(self):
        return list(map(lambda j: j.view(),
                        filter(lambda j: j.is_product, self._jobs)))
    
    def time_open(self, rng: DateRange):
        rem_time = dt.timedelta()

        hrs_per_day = self.hrs_open.maxval - self.hrs_open.minval
        hrs_per_wk = (self.days_open.maxval + 1 - self.days_open.mi)

        start_dt = rng.minval
        start_day = _ceil_day(start_dt)
        start_week = _ceil_week(start_day)
        if start_day != start_dt and self.days_open.contains(start_dt.weekday()):
            min_day1_start = _floor_day(start_dt) + \
                dt.timedelta(hours=self.hrs_open.minval)
            day1_end = _floor_day(start_dt) + dt.timedelta(hours=self.hrs_open.maxval)
            day1_start = min(day1_end, max(start_dt, min_day1_start))
            rem_time += day1_end - day1_start
        if start_week != start_day and self.days_open.contains(start_day.weekday()):
            min_wk1_start = _floor_week(start_day) + \
                dt.timedelta(days=self.days_open.minval)
            wk1_end = _floor_week(start_day) \
                + dt.timedelta(days=self.days_open.maxval+1)
            wk1_start = min(wk1_end, max(start_day, min_wk1_start))
            days = round((wk1_end - wk1_start).total_seconds() / (3600*24))
            rem_time += dt.timedelta(hours=days*hrs_per_day)
        
        end_dt = rng.maxval
        end_day = _floor_day(end_dt)
        end_week = _floor_week(end_day)
        if end_day != end_dt and self.days_open.contains(end_dt.weekday()):
            max_day2_end = _floor_day(end_dt) + \
                dt.timedelta(hours=self.hrs_open.maxval)
            day2_start = _floor_day(end_dt) + dt.timedelta(hours=self.hrs_open.minval)
            day2_end = max(day2_start, min(end_dt, max_day2_end))
            rem_time += day2_end - day2_start
        if end_week != end_day and self.days_open.contains(end_day.weekday()):
            max_wk2_end = _floor_week(end_day) + \
                dt.timedelta(days=self.days_open.maxval+1)
            wk2_start = _floor_week(end_day) + dt.timedelta(days=self.days_open.minval)
            wk2_end = max(wk2_start, min(end_day, max_wk2_end))
            days = round((wk2_end - wk2_start).total_seconds() / (3600*24))
            rem_time += dt.timedelta(hours=days*hrs_per_day)

        weeks = round((end_week - start_week).total_seconds() / (3600*24*7))
        weeks = max(weeks, 0)
        rem_time += dt.timedelta(hours=weeks*hrs_per_wk)
        return rem_time
    
    def nearest_open_time(self, date: dt.datetime):
        cur_mon = _floor_week(_floor_day(date))
        wk_rng = DateRange(cur_mon + dt.timedelta(days=self.days_open.minval,
                                                  hours=self.hrs_open.minval),
                           cur_mon + dt.timedelta(days=self.days_open.maxval,
                                                  hours=self.hrs_open.maxval))
        if wk_rng.contains(date):
            cur_day = _floor_day(date)
            hrs_rng = DateRange(cur_day + dt.timedelta(hours=self.hrs_open.minval),
                                cur_day + dt.timedelta(hours=self.hrs_open.maxval))
            if hrs_rng.contains(date):
                return date
            if hrs_rng.is_above(date):
                return _floor_day(date) + dt.timedelta(hours=self.hrs_open.minval)
            return _ceil_day(date) + dt.timedelta(hours=self.hrs_open.minval)
        if wk_rng.is_above(date):
            return wk_rng.minval
        return wk_rng.minval + dt.timedelta(weeks=1)
    
    def end_in_schedule(self, start: dt.datetime, cycle_time: dt.timedelta):
        start = self.nearest_open_time(start)

        day1_end = _floor_day(start) + dt.timedelta(hours=self.hrs_open.maxval)
        rem_cycle = cycle_time - (day1_end - start)
        if rem_cycle <= dt.timedelta(seconds=0):
            return start + cycle_time
        
        cycle_time = rem_cycle
        start = self.nearest_open_time(day1_end + dt.timedelta(minutes=1))
        if start == day1_end + dt.timedelta(minutes=1):
            start = day1_end

        total_hrs = cycle_time.total_seconds() / 3600
        hrs_per_day = self.hrs_open.maxval - self.hrs_open.minval

        wk1_end = _floor_week(_floor_day(start)) + \
            dt.timedelta(days=self.days_open.maxval, hours=self.hrs_open.maxval)
        wk1_rem_days = wk1_end.weekday() - start.weekday() + 1
        rem_cycle = cycle_time - (dt.timedelta(hours=hrs_per_day) * wk1_rem_days)
        if rem_cycle <= dt.timedelta(seconds=0):
            rem_hrs = total_hrs % hrs_per_day
            full_days = round((total_hrs - rem_hrs) / hrs_per_day)
            return start + dt.timedelta(days=full_days, hours=rem_hrs)
        
        cycle_time = rem_cycle
        start = self.nearest_open_time(wk1_end + dt.timedelta(minutes=1))
        if start == wk1_end + dt.timedelta(minutes=1):
            start = wk1_end

        total_hrs = cycle_time.total_seconds() / 3600
        days_per_wk = self.days_open.maxval - self.days_open.minval
        hrs_per_wk = days_per_wk * hrs_per_day
        rem_hrs = total_hrs % hrs_per_wk
        full_weeks = round((total_hrs - rem_hrs) / hrs_per_wk)

        return start + dt.timedelta(weeks=full_weeks, hours=rem_hrs)
    
    def can_add_cycle(self, min_date, cycle_time):
        start = max(min_date, self.end)
        start = self.nearest_open_time(start)
        return self.end_in_schedule(start, cycle_time) <= self.date_rng.maxval

    def can_add_lots(self, lots, cycle_time):
        raise NotImplementedError()
    
    def add_lots(self, lots, cycle_time, idx = None):
        raise NotImplementedError()
    
    def add_job(self, job, force = False):
        if not force and job.start - dt.timedelta(minutes=1) > self.end:
            job_start = job.start.strftime('%m-%d %H:%M:%S')
            sched_end = self.end.strftime('%m-%d %H:%M:%S')
            msg = f'Cannot add job with start time {job_start} to schedule'
            msg += f' with end time {sched_end}'
            raise ValueError(msg)
        
        self._jobs.append(job)
    
    def activate(self):
        for job in self._jobs:
            job.activate()

    def deactivate(self):
        for job in self._jobs:
            job.deactivate()