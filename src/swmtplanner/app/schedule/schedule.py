#!/usr/bin/env python

import datetime as dt

from swmtplanner.support import SwmtBase, HasID, FloatRange, DateRange

def _round_up_to_week(date: dt.datetime, hrs_open: FloatRange,
                      days_open: FloatRange):
    if date.weekday() == days_open.minval:
        first_hour = dt.datetime(date.year, date.month, date.day, hour=hrs_open.minval)
        if date - dt.timedelta(minutes=1) > first_hour:
            date += dt.timedelta(days=1)
    
    days_til = days_open.minval - date.weekday()
    if days_til < 0:
        days_til += 7

    first_date = date + dt.timedelta(days=days_til)
    first_date = dt.datetime(first_date.year, first_date.month, first_date.day,
                             hour=hrs_open.minval)
    
    return first_date

def _round_down_to_week(date: dt.datetime, hrs_open: FloatRange,
                        days_open: FloatRange):
    if date.weekday() == days_open.maxval:
        last_hour = dt.datetime(date.year, date.month, date.day, hour=hrs_open.maxval)
        if date + dt.timedelta(minutes=1) < last_hour:
            date -= dt.timedelta(days=1)
    
    days_since = date.weekday() - days_open.maxval
    if days_since < 0:
        days_since += 7

    last_date = date - dt.timedelta(days=days_since)
    last_date = dt.datetime(last_date.year, last_date.month, last_date.day,
                            hour=hrs_open.maxval)
    
    return last_date

def _round_up_to_day(date: dt.datetime, hrs_open: FloatRange,
                     days_open: FloatRange):
    if not days_open.contains(date.weekday()):
        return _round_up_to_week(date, hrs_open, days_open)
    
    first_hour = dt.datetime(date.year, date.month, date.day,
                             hour=hrs_open.minval)
    if date.weekday() == days_open.maxval and \
        date - dt.timedelta(minutes=1) > first_hour:
        return _round_up_to_week(date, hrs_open, days_open)
    
    if date - dt.timedelta(minutes=1) > first_hour:
        first_hour += dt.timedelta(hours=24)
    
    return first_hour

def _round_down_to_day(date: dt.datetime, hrs_open: FloatRange,
                       days_open: FloatRange):
    if not days_open.contains(date.weekday()):
        return _round_down_to_week(date, hrs_open, days_open)
    
    last_hour = dt.datetime(date.year, date.month, date.day,
                            hour=hrs_open.maxval)
    if date.weekday() == days_open.minval and \
        date + dt.timedelta(minutes=1) < last_hour:
        return _round_down_to_week(date, hrs_open, days_open)
    
    if date + dt.timedelta(minutes=1) < last_hour:
        last_hour -= dt.timedelta(hours=24)
    
    return last_hour

def _total_time_open(date_rng: DateRange, hrs_open: FloatRange, days_open: FloatRange):
    first_week1 = _round_up_to_week(date_rng.minval, hrs_open, days_open)
    first_week2 = _round_down_to_week(first_week1, hrs_open, days_open)
    first_week2 = dt.datetime(first_week2.year, first_week2.month, first_week2.day,
                              hour=hrs_open.minval)

    last_week1 = _round_down_to_week(date_rng.maxval, hrs_open, days_open)
    last_week2 = _round_up_to_week(last_week1, hrs_open, days_open)

    full_weeks = 0
    if last_week2 > first_week1:
        diff = last_week2 - first_week1
        full_weeks = round(diff.total_seconds() / (3600*24*7))

    first_day1 = _round_up_to_day(date_rng.minval, hrs_open, days_open)
    last_day1 = _round_down_to_day(date_rng.maxval, hrs_open, days_open)
    full_days = 0
    if first_week2 > first_day1:
        diff = first_week2 - first_day1
        full_days += round(diff.total_seconds() / (3600*24))
    
    if last_day1 > last_week2:
        diff = last_day1 - last_week2
        full_days += round(diff.total_seconds() / (3600*24))
    
    hrs_per_day = hrs_open.maxval - hrs_open.minval
    days_per_week = days_open.maxval - days_open.minval + 1
    total_hrs = full_weeks * days_per_week * hrs_per_day + full_days * hrs_per_day

    if days_open.contains(date_rng.minval.weekday()):
        date = dt.datetime(date_rng.minval.year,
                           date_rng.minval.month,
                           date_rng.minval.day)
        cur_hrs = DateRange(date + dt.timedelta(hours=hrs_open.minval),
                            date + dt.timedelta(hours=hrs_open.maxval))
        if cur_hrs.contains(date_rng.minval):
            diff = cur_hrs.maxval - date_rng.minval
            total_hrs += diff.total_seconds() / 3600
    if days_open.contains(date_rng.maxval.weekday()):
        date = dt.datetime(date_rng.maxval.year,
                           date_rng.maxval.month,
                           date_rng.maxval.day)
        cur_hrs = DateRange(date + dt.timedelta(hours=hrs_open.minval),
                            date + dt.timedelta(hours=hrs_open.maxval))
        if cur_hrs.contains(date_rng.maxval):
            diff = date_rng.maxval - cur_hrs.minval
            total_hrs += diff.total_seconds() / 3600
    
    return dt.timedelta(hours=total_hrs)

class Schedule(SwmtBase, HasID[str],
               read_only=('prefix','id','date_rng','hrs_open','days_open'),
               priv=('jobs',)):
    
    def __init__(self, prefix, sched_id, date_rng, hrs_open, days_open):
        SwmtBase.__init__(self, _prefix=prefix, _id=sched_id, _date_rng=date_rng,
                          _hrs_open=hrs_open, _days_open=days_open, _jobs=[])
        
    def _end_in_schedule(self, end_raw: dt.datetime):
        if not self.days_open.contains(end_raw.weekday()):
            return _round_up_to_week(end_raw, self.hrs_open, self.days_open)
        cur_date = dt.datetime(end_raw.year, end_raw.month, end_raw.day)
        cur_hrs = DateRange(cur_date + dt.timedelta(hours=self.hrs_open.minval),
                            cur_date + dt.timedelta(hours=self.hrs_open.maxval))
        if not cur_hrs.contains(end_raw):
            return _round_up_to_day(end_raw, self.hrs_open, self.days_open)
        return end_raw
        
    @property
    def end(self):
        end_raw = self.date_rng.minval
        if self._jobs:
            end_raw = max(end_raw, self._jobs[-1].end)
        return self._end_in_schedule(end_raw)
    
    @property
    def rem_time(self):
        rem_rng = DateRange(self.end, self.date_rng.maxval)
        return _total_time_open(rem_rng, self.hrs_open, self.days_open)
    
    @property
    def jobs(self):
        return list(map(lambda j: j.view(), self._jobs))
    
    @property
    def prod_jobs(self):
        return list(map(lambda j: j.view(),
                        filter(lambda j: j.is_product, self._jobs)))
    
    def can_insert_cycle(self, min_date, cycle_time, idx: int):
        rng_min = max(min_date, self.date_rng.minval)
        rng_max = self.date_rng.maxval

        jobs = self.prod_jobs
        if idx < len(jobs):
            if idx > 0 and jobs[idx-1].end > rng_min:
                rng_min = self._end_in_schedule(jobs[idx-1].end)
            if not jobs[idx].moveable:
                rng_max = jobs[idx].start

        if rng_max <= rng_min:
            return False
        
        return _total_time_open(DateRange(rng_min, rng_max), self.hrs_open,
                                self.days_open) + dt.timedelta(minutes=1) >= cycle_time

    def can_insert_lots(self, lots, cycle_time, idx):
        raise NotImplementedError()
    
    def insert_lots(self, lots, cycle_time, idx):
        raise NotImplementedError()
    
    def activate(self):
        for job in self._jobs:
            job.activate()

    def deactivate(self):
        for job in self._jobs:
            job.deactivate()