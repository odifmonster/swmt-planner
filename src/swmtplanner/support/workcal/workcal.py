#!/usr/bin/env python

from datetime import date, datetime, timedelta

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
    
    def __init__(self, work_days, day_start, day_end, holidays):
        if len(work_days) == 0:
            raise ValueError('work_days cannot be empty')
        if day_start >= day_end:
            raise ValueError('day_start must be before day_end')
        
        self._work_days = tuple(work_days)
        self._work_day_set = frozenset(self._work_days)
        self._day_start = day_start
        self._day_end = day_end
        self._holidays = tuple(HOLIDAYS[name] for name in holidays)
        self._holiday_cache = {}
    
    @property
    def work_days(self):
        return self._work_days
    
    @property
    def work_days_per_week(self):
        return len(self._work_days)
    
    @property
    def work_hours(self):
        return (self._day_start, self._day_end)
    
    @property
    def work_hours_per_day(self):
        return self._day_end - self._day_start
    
    @property
    def holidays(self):
        return self._holidays

    def _holiday_ordinals(self, year: int) -> set[int]:
        try:
            return self._holiday_cache[year]
        except KeyError:
            ordinals = set()
            for holiday in self._holidays:
                if isinstance(holiday, FixedDate):
                    holiday_date = date(year, holiday.month, holiday.day)
                else:
                    holiday_date = _get_date_in_year(holiday, year)
                if holiday_date.weekday() in self._work_day_set:
                    ordinals.add(holiday_date.toordinal())
            self._holiday_cache[year] = ordinals
            return ordinals
    
    def _first_work_day_after(self, start: date):
        """Returns the first work day after the given start date.
        Returns the start date if it is a work day."""
        current = start
        while (current.weekday() not in self._work_day_set
                or current.toordinal() in self._holiday_ordinals(current.year)):
            current += timedelta(days=1)
        return current

    def _first_work_day_before(self, start: date):
        """Returns the first work day before the given start date.
        Returns the start date if it is a work day."""
        current = start
        while (current.weekday() not in self._work_day_set
                or current.toordinal() in self._holiday_ordinals(current.year)):
            current -= timedelta(days=1)
        return current

    def add_work_days(self, start: date, days: int) -> date:
        if days >= 0:
            snap = self._first_work_day_after
            step = timedelta(days=1)
        else:
            snap = self._first_work_day_before
            step = timedelta(days=-1)
        current = snap(start)
        for _ in range(abs(days)):
            current = snap(current + step)
        return current

    def _snap_forward_dt(self, dt: datetime) -> datetime:
        """Snap dt to the first datetime within work hours at or after dt."""
        d = dt.date()
        next_d = self._first_work_day_after(d)
        if next_d != d:
            return datetime(next_d.year, next_d.month, next_d.day) + timedelta(hours=self._day_start)
        midnight = datetime(d.year, d.month, d.day)
        h = (dt - midnight).total_seconds() / 3600
        if h < self._day_start:
            return midnight + timedelta(hours=self._day_start)
        if h > self._day_end:
            next_d = self._first_work_day_after(d + timedelta(days=1))
            return datetime(next_d.year, next_d.month, next_d.day) + timedelta(hours=self._day_start)
        return dt

    def _snap_backward_dt(self, dt: datetime) -> datetime:
        """Snap dt to the last datetime within work hours at or before dt."""
        d = dt.date()
        prev_d = self._first_work_day_before(d)
        if prev_d != d:
            return datetime(prev_d.year, prev_d.month, prev_d.day) + timedelta(hours=self._day_end)
        midnight = datetime(d.year, d.month, d.day)
        h = (dt - midnight).total_seconds() / 3600
        if h > self._day_end:
            return midnight + timedelta(hours=self._day_end)
        if h < self._day_start:
            prev_d = self._first_work_day_before(d - timedelta(days=1))
            return datetime(prev_d.year, prev_d.month, prev_d.day) + timedelta(hours=self._day_end)
        return dt

    def add_work_hours(self, start: datetime, hours: float) -> datetime:
        backward = hours < 0
        remaining = abs(hours)
        current = self._snap_backward_dt(start) if backward else self._snap_forward_dt(start)
        while remaining > 0:
            d = current.date()
            midnight = datetime(d.year, d.month, d.day)
            h = (current - midnight).total_seconds() / 3600
            if backward:
                available = h - self._day_start
                if remaining <= available:
                    return current - timedelta(hours=remaining)
                remaining -= available
                prev_d = self._first_work_day_before(d - timedelta(days=1))
                current = datetime(prev_d.year, prev_d.month, prev_d.day) + timedelta(hours=self._day_end)
            else:
                available = self._day_end - h
                if remaining <= available:
                    return current + timedelta(hours=remaining)
                remaining -= available
                next_d = self._first_work_day_after(d + timedelta(days=1))
                current = datetime(next_d.year, next_d.month, next_d.day) + timedelta(hours=self._day_start)
        return current

    def get_work_hours_between(self, start: datetime, end: datetime) -> float:
        if end <= start:
            return 0.0
        s = self._snap_forward_dt(start)
        e = self._snap_backward_dt(end)
        if e <= s:
            return 0.0

        s_date = s.date()
        e_date = e.date()
        s_h = (s - datetime(s_date.year, s_date.month, s_date.day)).total_seconds() / 3600
        e_h = (e - datetime(e_date.year, e_date.month, e_date.day)).total_seconds() / 3600

        if s_date == e_date:
            return e_h - s_h

        total = (self._day_end - s_h) + (e_h - self._day_start)
        full_day_hours = self._day_end - self._day_start
        current = s_date + timedelta(days=1)
        while current < e_date:
            if (current.weekday() in self._work_day_set
                    and current.toordinal() not in self._holiday_ordinals(current.year)):
                total += full_day_hours
            current += timedelta(days=1)
        return total
