#!/usr/bin/env python

from datetime import date, datetime, time, timedelta

from .holiday import Holiday


class WorkCal:

    def __init__(self, weekdays: list[int], day_start: int, day_end: int,
                 holidays: list[Holiday], cal_shift: int = 0):
        self._weekdays = tuple(weekdays)
        self._weekday_set = frozenset(weekdays)
        self._day_start = day_start
        self._day_end = day_end
        self._holidays = tuple(holidays)
        self._cal_shift = cal_shift

        self._holiday_ords: set[int] = set()
        self._cache_range: tuple[int, int] | None = None

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
    def cal_shift(self) -> int:
        return self._cal_shift

    @property
    def work_days_per_week(self) -> int:
        return len(self._weekdays)

    @property
    def work_hours_per_day(self) -> int:
        return self._day_end - self._day_start

    def _cache_years(self, lo: int, hi: int) -> None:
        for year in range(lo, hi):
            for holiday in self._holidays:
                self._holiday_ords.add(holiday.get_date_in_year(year).toordinal())

    def _ensure_cached(self, year: int) -> None:
        if self._cache_range is None:
            self._cache_years(year, year + 1)
            self._cache_range = (year, year + 1)
            return
        lo, hi = self._cache_range
        if year < lo:
            self._cache_years(year, lo)
            self._cache_range = (year, hi)
        elif year >= hi:
            self._cache_years(hi, year + 1)
            self._cache_range = (lo, year + 1)

    def is_workday(self, date: date) -> bool:
        if date.weekday() not in self._weekday_set:
            return False
        self._ensure_cached(date.year)
        return date.toordinal() not in self._holiday_ords

    def offset_work_days(self, start: date, days: int) -> date:
        step = timedelta(days=1 if days >= 0 else -1)
        while not self.is_workday(start):
            start += step
        remaining = abs(days)
        while remaining > 0:
            start += step
            if self.is_workday(start):
                remaining -= 1
        return start

    def _window(self, d: date) -> tuple[datetime, datetime]:
        midnight = datetime.combine(d, time(0, 0))
        return (midnight + timedelta(hours=self._day_start),
                midnight + timedelta(hours=self._day_end))

    def _next_workday(self, d: date) -> date:
        d += timedelta(days=1)
        while not self.is_workday(d):
            d += timedelta(days=1)
        return d

    def _prev_workday(self, d: date) -> date:
        d -= timedelta(days=1)
        while not self.is_workday(d):
            d -= timedelta(days=1)
        return d

    def _snap_forward(self, a: datetime) -> tuple[datetime, date]:
        d = a.date()
        if self.is_workday(d):
            ws, we = self._window(d)
            if a < ws:
                return ws, d
            if a < we:
                return a, d
        d = self._next_workday(d)
        ws, _ = self._window(d)
        return ws, d

    def _snap_backward(self, a: datetime) -> tuple[datetime, date]:
        d = a.date()
        if self.is_workday(d):
            ws, we = self._window(d)
            if a > we:
                return we, d
            if a > ws:
                return a, d
        d = self._prev_workday(d)
        _, we = self._window(d)
        return we, d

    def offset_work_hours(self, start: datetime, hours: float) -> datetime:
        shift = timedelta(hours=self._cal_shift)
        a = start - shift
        if hours >= 0:
            cur, d = self._snap_forward(a)
            remaining = timedelta(hours=hours)
            while True:
                _, we = self._window(d)
                avail = we - cur
                if remaining <= avail:
                    cur = cur + remaining
                    break
                remaining -= avail
                d = self._next_workday(d)
                cur, _ = self._window(d)
        else:
            cur, d = self._snap_backward(a)
            remaining = timedelta(hours=-hours)
            while True:
                ws, _ = self._window(d)
                avail = cur - ws
                if remaining <= avail:
                    cur = cur - remaining
                    break
                remaining -= avail
                d = self._prev_workday(d)
                _, cur = self._window(d)
        return cur + shift

    def get_work_hours_between(self, start: datetime, end: datetime) -> float:
        if start >= end:
            return 0.0
        shift = timedelta(hours=self._cal_shift)
        a_start = start - shift
        a_end = end - shift
        total = timedelta()
        d = a_start.date()
        while d <= a_end.date():
            if self.is_workday(d):
                ws, we = self._window(d)
                lo = max(ws, a_start)
                hi = min(we, a_end)
                if hi > lo:
                    total += hi - lo
            d += timedelta(days=1)
        return total.total_seconds() / 3600

    def avail_hours_before_weekend(self, start: datetime) -> float:
        shift = timedelta(hours=self._cal_shift)
        d = (start - shift).date()
        week_end = datetime.combine(d + timedelta(days=8 - d.isoweekday()),
                                    time(0, 0))
        return self.get_work_hours_between(start, week_end + shift)
