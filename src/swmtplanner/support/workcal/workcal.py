#!/usr/bin/env python

from typing import TYPE_CHECKING
from datetime import datetime, time, timedelta

from .holiday import Holiday

if TYPE_CHECKING:
    from datetime import date


class WorkCal:
    def __init__(
        self,
        weekdays: list[int],
        day_start: int,
        day_end: int,
        holidays: list[Holiday],
        cal_shift: int = 0
    ) -> None:
        self._weekdays = tuple(weekdays)
        self._day_start = day_start
        self._day_end = day_end
        self._holidays = tuple(holidays)
        self._cal_shift = cal_shift
        self._shift_dt = timedelta(hours=cal_shift)

        self._cache_lo = None
        self._cache_hi = None
        self._holiday_cache: set[int] = set()

    @property
    def weekdays(self) -> tuple[int, ...]:
        return self._weekdays

    @property
    def day_start(self) -> int:
        return self._day_start

    @property
    def day_end(self) -> int:
        return self._day_end

    @property
    def holidays(self) -> tuple[Holiday, ...]:
        return self._holidays

    @property
    def work_days_per_week(self) -> int:
        return len(self._weekdays)

    @property
    def work_hours_per_day(self) -> int:
        return self._day_end - self._day_start
    
    @property
    def cal_shift(self) -> int:
        return self._cal_shift
    
    def _compute_holiday_ordinals(self, year: int):
        return [ h.date_in_year(year).toordinal() for h in self._holidays ]
    
    def _update_holiday_ordinals(self, year: int):
        if self._cache_lo is None or self._cache_hi is None:
            self._cache_lo = year
            self._cache_hi = year + 1
            self._holiday_cache.update(self._compute_holiday_ordinals(year))
            return
        
        if self._cache_lo <= year and year < self._cache_hi:
            return
        
        if year < self._cache_lo:
            rng_lo = year
            rng_hi = self._cache_lo
            self._cache_lo = year
        else:
            rng_lo = self._cache_hi
            rng_hi = year + 1
            self._cache_hi = rng_hi
        
        for year in range(rng_lo, rng_hi):
            self._holiday_cache.update(self._compute_holiday_ordinals(year))
    
    def is_workday(self, d: 'date'):
        self._update_holiday_ordinals(d.year)
        return d.weekday() in self.weekdays and not d.toordinal() in self._holiday_cache

    def offset_work_days(self, start: 'date', days: int) -> 'date':
        step = timedelta(days=1 if days >= 0 else -1)
        current = start
        while not self.is_workday(current):
            current += step
        remaining = abs(days)
        while remaining > 0:
            current += step
            if self.is_workday(current):
                remaining -= 1
        return current

    def _day_start_dt(self, d: 'date') -> datetime:
        return datetime.combine(d, time()) + timedelta(hours=self._day_start)

    def _day_end_dt(self, d: 'date') -> datetime:
        return datetime.combine(d, time()) + timedelta(hours=self._day_end)

    def _next_workday(self, d: 'date') -> 'date':
        d += timedelta(days=1)
        while not self.is_workday(d):
            d += timedelta(days=1)
        return d

    def _prev_workday(self, d: 'date') -> 'date':
        d -= timedelta(days=1)
        while not self.is_workday(d):
            d -= timedelta(days=1)
        return d

    def _snap_to_business(self, dt: datetime, forward: bool) -> datetime:
        if self.is_workday(dt.date()):
            ds = self._day_start_dt(dt.date())
            de = self._day_end_dt(dt.date())
            if forward:
                if dt < ds:
                    return ds
                if dt < de:
                    return dt
            else:
                if dt > de:
                    return de
                if dt > ds:
                    return dt
        if forward:
            return self._day_start_dt(self._next_workday(dt.date()))
        return self._day_end_dt(self._prev_workday(dt.date()))

    def offset_work_hours(self, start: datetime, hours: float) -> datetime:
        start -= self._shift_dt
        forward = hours >= 0
        current = self._snap_to_business(start, forward)
        # Track the workday `current` belongs to. Normally that's `current.date()`,
        # but when `day_end == 24` the day_end_dt of workday wd equals midnight of
        # wd+1, so a backward-snapped `current` at that boundary has .date() = wd+1.
        if not forward and self._day_end == 24 and current.time() == time(0):
            wd = current.date() - timedelta(days=1)
        else:
            wd = current.date()
        remaining = abs(hours)
        while remaining > 0:
            if forward:
                de = self._day_end_dt(wd)
                avail = (de - current).total_seconds() / 3600
                if remaining <= avail:
                    return current + timedelta(hours=remaining) + self._shift_dt
                remaining -= avail
                wd = self._next_workday(wd)
                current = self._day_start_dt(wd)
            else:
                ds = self._day_start_dt(wd)
                avail = (current - ds).total_seconds() / 3600
                if remaining <= avail:
                    return current - timedelta(hours=remaining) + self._shift_dt
                remaining -= avail
                wd = self._prev_workday(wd)
                current = self._day_end_dt(wd)
        return current + self._shift_dt

    def get_work_hours_between(self, start: datetime, end: datetime) -> float:
        if start >= end:
            return 0.0
        start -= self._shift_dt
        end -= self._shift_dt
        total = 0.0
        d = start.date()
        end_date = end.date()
        while d <= end_date:
            if self.is_workday(d):
                lo = max(start, self._day_start_dt(d))
                hi = min(end, self._day_end_dt(d))
                if hi > lo:
                    total += (hi - lo).total_seconds() / 3600
            d += timedelta(days=1)
        return total

    def avail_hours_before_weekend(self, start: datetime) -> float:
        cal_date = (start - self._shift_dt).date()
        end_cal_date = cal_date + timedelta(days=8 - cal_date.isoweekday())
        end_real = datetime.combine(end_cal_date, time()) + self._shift_dt
        return self.get_work_hours_between(start, end_real)
