from datetime import date, datetime

from .holiday import Holiday


__all__ = ['WorkCal']


class WorkCal:
    """A working calendar: handles date math across working days and hours,
    skipping holidays, non-business hours, and overnight shifts that cross a day
    boundary."""

    def __init__(self, weekdays: list[int], day_start: int, day_end: int,
                 holidays: list[Holiday], cal_shift: int = ...) -> None:
        """Initialize with the working weekday integers (0 = Monday), the
        business-day start and end hours (before applying the calendar shift;
        day_end may be 24), the holidays, and optionally the calendar shift in
        hours (defaults to 0)."""
        ...
    @property
    def weekdays(self) -> tuple[int, ...]:
        """The working days of the week, where 0 = Monday."""
        ...
    @property
    def day_start(self) -> int:
        """The hour the business day starts (before the calendar shift)."""
        ...
    @property
    def day_end(self) -> int:
        """The hour the business day ends (before the calendar shift); may be
        24 for a 24-hour work day."""
        ...
    @property
    def holidays(self) -> tuple[Holiday, ...]:
        """The calendar's holidays."""
        ...
    @property
    def cal_shift(self) -> int:
        """The number of hours the overnight shift is offset from midnight."""
        ...
    @property
    def work_days_per_week(self) -> int:
        """The number of working days in a week."""
        ...
    @property
    def work_hours_per_day(self) -> int:
        """The number of working hours in a day."""
        ...
    def is_workday(self, date: date) -> bool:
        """Whether date is a working day: its weekday is a working day and it is
        not a holiday."""
        ...
    def offset_work_days(self, start: date, days: int) -> date:
        """The date `days` working days from start. Accepts negative days. If
        start is not a working day, snaps in the direction of travel (backward
        for negative days, forward for days >= 0) before applying the offset."""
        ...
    def offset_work_hours(self, start: datetime, hours: float) -> datetime:
        """The datetime `hours` working hours from start, applying the calendar
        shift. Accepts negative hours. If start is not within working hours,
        snaps in the direction of travel (backward for negative hours, forward
        for hours >= 0) before applying the offset."""
        ...
    def get_work_hours_between(self, start: datetime, end: datetime) -> float:
        """The number of working hours between start and end, applying the
        calendar shift. Does not compute negative intervals: returns 0 if
        start >= end."""
        ...
    def avail_hours_before_weekend(self, start: datetime) -> float:
        """The number of working hours remaining between start and the end of
        the ISO calendar week containing start (after adjusting for the calendar
        shift). Returns 0 if start falls on a weekend day at the end of the
        week."""
        ...
