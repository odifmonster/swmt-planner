from datetime import datetime, date

from . import holiday as holiday


__all__ = ['holiday', 'WorkCal']


class WorkCal:
    """Customizable work calendar for date math that skips weekends and holidays.

    Configured at construction with the set of working weekdays, the daily
    business-hours window, the list of observed holidays, and an optional
    calendar-day shift. Immutable after construction.
    """
    def __init__(
        self,
        weekdays: list[int],
        day_start: int,
        day_end: int,
        holidays: list[holiday.Holiday],
        cal_shift: int = 0
    ) -> None:
        """Build a WorkCal.

        `weekdays` and `holidays` are copied at construction; nothing on the
        WorkCal is mutable afterwards.

        `weekdays` uses Python's `date.weekday()` convention (Mon=0..Sun=6).
        `day_start` and `day_end` are integer hours in [0, 24] measured from
        the start of the calendar day; `day_end=24` denotes a day that runs
        to the calendar-day boundary.

        `cal_shift` is an integer hour offset shifting each calendar day's
        start away from real-clock midnight. Negative values shift earlier
        (into the previous evening); positive values shift later. Defaults
        to 0 (calendar days coincide with real days).
        """
        ...
    @property
    def weekdays(self) -> tuple[int, ...]:
        """Working weekdays (Mon=0..Sun=6)."""
        ...
    @property
    def day_start(self) -> int:
        """Hour the business day begins, measured from the calendar-day start."""
        ...
    @property
    def day_end(self) -> int:
        """Hour the business day ends, measured from the calendar-day start."""
        ...
    @property
    def holidays(self) -> tuple[holiday.Holiday, ...]:
        """Holidays observed by this calendar."""
        ...
    @property
    def work_days_per_week(self) -> int:
        """Number of working weekdays per week."""
        ...
    @property
    def work_hours_per_day(self) -> int:
        """Business hours per workday (`day_end - day_start`)."""
        ...
    @property
    def cal_shift(self) -> int:
        """Integer hour offset of each calendar day's start from midnight."""
        ...
    def is_workday(self, d: date) -> bool:
        """Return True iff `d` is a working weekday and not a configured holiday."""
        ...
    def offset_work_days(self, start: date, days: int) -> date:
        """Return the date `days` working days from `start`.

        Sign convention is symmetric: positive advances forward, negative
        walks backward. If `start` itself is a non-workday it is snapped
        onto a workday in the direction of travel before counting; an offset
        of `0` therefore acts as a pure snap-forward.
        """
        ...
    def offset_work_hours(self, start: datetime, hours: float) -> datetime:
        """Return the datetime `hours` working hours from `start`.

        Time outside business hours and outside working days does not count
        toward the offset. Sign convention is symmetric. `start` is snapped
        onto a business boundary in the direction of travel before counting;
        an offset of `0` acts as a pure snap-forward.
        """
        ...
    def get_work_hours_between(self, start: datetime, end: datetime) -> float:
        """Return total working hours falling within the interval `[start, end]`.

        Time outside of business hours is excluded. Returns `0` when
        `start >= end` (the function does not produce signed results).
        """
        ...
    def avail_hours_before_weekend(self, start: datetime) -> float:
        """Return working hours from `start` to the end of the ISO calendar week containing `start`'s calendar date.

        Equivalent to `get_work_hours_between(start, end_of_iso_week)`,
        where end-of-week is the calendar-Sunday/calendar-Monday boundary
        of the ISO week containing `(start - cal_shift).date()`. `start`
        is not snapped: non-working hours within `[start, end_of_week]`
        simply contribute zero. On a Mon-Fri calendar, calling with a
        Saturday or Sunday `start` returns `0`.
        """
        ...
