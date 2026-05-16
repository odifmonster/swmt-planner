#!/usr/bin/env python

from datetime import date, datetime, timedelta
from bisect import bisect_left, bisect_right
import math

from .holidays import *

def _get_date_in_year(holiday: FlexDate, year: int) -> date:
    if holiday.n == 0:
        raise ValueError('holiday.n cannot be 0')

    if holiday.n > 0:
        first = date(year, holiday.month, 1)
        day = 1 + (holiday.weekday - first.weekday()) % 7 + 7 * (holiday.n - 1)
    else:
        if holiday.month == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, holiday.month + 1, 1)
        last = date.fromordinal(next_month.toordinal() - 1)
        day = last.day - (last.weekday() - holiday.weekday) % 7 + 7 * (holiday.n + 1)

    return date(year, holiday.month, day)

class WorkCal:

    def __init__(self, work_days, day_start, day_end, holidays, cal_shift = 0):
        self._work_days = tuple(work_days)
        self._day_start = day_start
        self._day_end = day_end
        self._holidays = tuple(holidays)
        self._cal_shift = timedelta(hours=cal_shift)

        self._hday_lo = None
        self._hday_hi = None
        self._holiday_cache = []

    @property
    def work_days(self):
        return self._work_days
    
    @property
    def days_per_week(self):
        return len(self.work_days)
    
    @property
    def work_hours(self):
        return (self._day_start, self._day_end)
    
    @property
    def hours_per_day(self):
        return self._day_end - self._day_start
    
    @property
    def holidays(self):
        return self._holidays

    def _compute_holiday_ordinals(self, start: int, end: int) -> list[int]:
        ret = []
        year_lo = date.fromordinal(start).year
        year_hi = date.fromordinal(end).year + 1
        for year in range(year_lo, year_hi):
            for holiday in self.holidays:
                if isinstance(holiday, FixedDate):
                    cur_date = date(year, holiday.month, holiday.day)
                else:
                    cur_date = _get_date_in_year(holiday, year)
                cur_ord = cur_date.toordinal()
                if cur_date.weekday() in self.work_days and start <= cur_ord < end:
                    ret.insert(bisect_right(ret, cur_ord), cur_ord)
        return ret

    def _get_holiday_ordinals(self, start, end, direction = 1):
        if direction not in (1, -1):
            raise ValueError('direction must be 1 or -1')
        
        if direction == 1:
            if start > end:
                raise ValueError('start must be <= end if direction == 1')
            lo = start
            hi = end
            func = bisect_left
        if direction == -1:
            if start < end:
                raise ValueError('start must be >= end if direction == -1')
            lo = end + 1
            hi = start + 1
            func = bisect_right
    
        if self._hday_lo is None:
            self._holiday_cache = self._compute_holiday_ordinals(lo, hi)
            self._hday_lo = lo
            self._hday_hi = hi
        else:
            if lo < self._hday_lo:
                self._holiday_cache = self._compute_holiday_ordinals(lo, self._hday_lo) + self._holiday_cache
                self._hday_lo = lo
            if hi > self._hday_hi:
                self._holiday_cache += self._compute_holiday_ordinals(self._hday_hi, hi)
                self._hday_hi = hi
        
        start_idx = func(self._holiday_cache, start)
        end_idx = func(self._holiday_cache, end)
        if direction == -1:
            start_idx -= 1
            end_idx -= 1
            if end_idx < 0:
                return self._holiday_cache[start_idx::direction]
        return self._holiday_cache[start_idx:end_idx:direction]
    
    def _work_days_in_week(self, year, week, bound = None, direction = 1):
        lo = date.fromisocalendar(year, week, 1).toordinal()
        hi = lo + 6

        if direction == 1:
            start, end = lo, hi + 1
            if bound is not None:
                start = max(start, bound)
        else:
            start, end = hi, lo - 1
            if bound is not None:
                start = min(start, bound)
        
        holidays = self._get_holiday_ordinals(start, end, direction=direction)
        return tuple(d for d in range(start, end, direction) if (d - 1) % 7 in self.work_days and \
                     d not in holidays)
    
    def is_holiday(self, d: date):
        ordinal = d.toordinal()
        return not bool(self._get_holiday_ordinals(ordinal, ordinal + 1))
    
    def is_work_day(self, d: date):
        if d.weekday() not in self.work_days:
            return False
        ordinal = d.toordinal()
        return not bool(self._get_holiday_ordinals(ordinal, ordinal + 1))
    
    def snap_to_work_date(self, d: date, direction = 1):
        while not self.is_work_day(d):
            d += timedelta(days=direction)
        return d
    
    def offset_work_days(self, start: date, days: int):
        direction = 1 if days >= 0 else -1
        current = self.snap_to_work_date(start, direction=direction)
        for _ in range(abs(days)):
            current = self.snap_to_work_date(current + timedelta(days=direction),
                                             direction=direction)
        return current
    
    def _snap_to_work_datetime(self, dt: datetime, direction: int) -> datetime:
        d = dt.date()
        snapped_d = self.snap_to_work_date(d, direction=direction)
        if snapped_d != d:
            md = datetime(snapped_d.year, snapped_d.month, snapped_d.day)
            boundary = self._day_start if direction == 1 else self._day_end
            return md + timedelta(hours=boundary)
        midnight = datetime(d.year, d.month, d.day)
        h = (dt - midnight).total_seconds() / 3600
        if direction == 1:
            if h < self._day_start:
                return midnight + timedelta(hours=self._day_start)
            if h > self._day_end:
                next_d = self.snap_to_work_date(d + timedelta(days=1), direction=1)
                md = datetime(next_d.year, next_d.month, next_d.day)
                return md + timedelta(hours=self._day_start)
        else:
            if h > self._day_end:
                return midnight + timedelta(hours=self._day_end)
            if h < self._day_start:
                prev_d = self.snap_to_work_date(d - timedelta(days=1), direction=-1)
                md = datetime(prev_d.year, prev_d.month, prev_d.day)
                return md + timedelta(hours=self._day_end)
        return dt

    def get_work_hours_between(self, start: datetime, end: datetime) -> float:
        start -= self._cal_shift
        end -= self._cal_shift
        if end <= start:
            return 0.0
        total = 0.0
        d = start.date()
        end_d = end.date()
        while d <= end_d:
            if self.is_work_day(d):
                day_lo = datetime(d.year, d.month, d.day) + timedelta(hours=self._day_start)
                day_hi = datetime(d.year, d.month, d.day) + timedelta(hours=self._day_end)
                lo = max(start, day_lo)
                hi = min(end, day_hi)
                if lo < hi:
                    total += (hi - lo).total_seconds() / 3600
            d += timedelta(days=1)
        return total

    def offset_work_hours(self, start: datetime, hours: float):
        start -= self._cal_shift
        direction = 1 if hours >= 0 else -1
        current = self._snap_to_work_datetime(start, direction)
        remaining = abs(hours)
        while remaining > 0:
            d = current.date()
            midnight = datetime(d.year, d.month, d.day)
            h = (current - midnight).total_seconds() / 3600
            if direction == 1:
                available = self._day_end - h
                if remaining <= available:
                    return current + timedelta(hours=remaining) - self._cal_shift
                remaining -= available
                next_d = self.snap_to_work_date(d + timedelta(days=1), direction=1)
                current = datetime(next_d.year, next_d.month, next_d.day) \
                    + timedelta(hours=self._day_start)
            else:
                available = h - self._day_start
                if remaining <= available:
                    return current - timedelta(hours=remaining) - self._cal_shift
                remaining -= available
                prev_d = self.snap_to_work_date(d - timedelta(days=1), direction=-1)
                current = datetime(prev_d.year, prev_d.month, prev_d.day) \
                    + timedelta(hours=self._day_end)
        return current + self._cal_shift