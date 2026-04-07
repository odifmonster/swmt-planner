#!/usr/bin/env python

from datetime import datetime, timedelta

from swmtplanner.support import SwmtBase

class WorkCal(SwmtBase,
              read_only=('wd_start','wd_end','work_days'),
              priv=('holidays','cal_shift')):
    
    def __init__(self, business_hrs, work_days, holidays, cal_shift = 0):
        wd_start, wd_end = business_hrs
        SwmtBase.__init__(self, _wd_start=wd_start, _wd_end=wd_end, _work_days=tuple(work_days),
                          _holidays=set(holidays), _cal_shift=cal_shift)
    
    def _is_workday(self, d):
        return d.weekday() in self.work_days and d not in self._holidays
    
    def _open_time(self, d):
        return datetime(d.year, d.month, d.day) + timedelta(hours=self.wd_start)
    
    def _close_time(self, d):
        return datetime(d.year, d.month, d.day) + timedelta(hours=self.wd_end)
    
    def add_work_hrs(self, start, hrs):
        curtime = start - timedelta(hours=self._cal_shift)
        remhrs = hrs

        if self._is_workday(curtime.date()):
            if curtime < self._open_time(curtime.date()):
                curtime = self._open_time(curtime.date())
            elif curtime >= self._close_time(curtime.date()):
                curtime = self._open_time((curtime + timedelta(days=1)).date())
        else:
            curtime = self._open_time((curtime + timedelta(days=1)).date())
        
        while remhrs > 0:
            while not self._is_workday(curtime.date()):
                curtime = self._open_time((curtime + timedelta(days=1)).date())
            
            avail_today = (self._close_time(curtime.date()) - curtime).total_seconds() / 3600

            if remhrs <= avail_today:
                curtime += timedelta(hours=remhrs)
                remhrs = 0
            else:
                remhrs -= avail_today
                curtime = self._open_time((curtime + timedelta(days=1)).date())
        
        return curtime + timedelta(hours=self._cal_shift)
    
    def get_work_hrs_between(self, start, end):
        total = 0
        curdate = (start - timedelta(hours=self._cal_shift)).date()
        enddate = (end - timedelta(hours=self._cal_shift)).date()

        while curdate <= enddate:
            if self._is_workday(curdate):
                open_dt = self._open_time(curdate)
                close_dt = self._close_time(curdate)

                curstart = max(open_dt, start)
                curend = min(close_dt, end)

                if curend > curstart:
                    total += (curend - curstart).total_seconds()
            
            curdate += timedelta(days=1)
        
        return total / 3600