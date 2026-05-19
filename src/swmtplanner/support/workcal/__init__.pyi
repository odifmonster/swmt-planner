from .holidays import (
    FlexDate, FixedDate, holidays_from_list, load_holidays,
)
from datetime import date, datetime
from pathlib import Path
from typing import Any

__all__ = [
    'FlexDate', 'FixedDate', 'holidays_from_list', 'load_holidays',
    'WorkCal', 'load_workcal', 'workcal_from_dict',
]


def load_workcal(path: str | Path) -> WorkCal: ...
def workcal_from_dict(
    cfg: dict[str, Any],
    *,
    holidays_base_dir: str | Path | None = ...,
    source: str = ...,
) -> WorkCal: ...

class WorkCal:
    """Convenience class for handling date math across business days/hours.
    Provides methods for offsetting by a number of "work days" and "work hours"."""
    def __init__(self, work_days: list[int], day_start: int, day_end: int,
                 holidays: list[FlexDate | FixedDate], cal_shift: int = 0):
        """Initialize a new work calendar.

        Parameters:
            work_days (list[int]): The working days of the week (monday=0).
            day_start (int): The start of the work day in 24-hour time.
            day_end (int): The end of the work day in 24-hour time.
            holidays (list[FlexDate | FixedDate]): The days of the year to be skipped as holidays.
            cal_shift (int, default 0): Set this parameter to offset day boundaries by a number of hours.
        """
        ...
    @property
    def work_days(self) -> tuple[int, ...]:
        """The working days of the week with monday=0."""
        ...
    @property
    def days_per_week(self) -> int:
        """Number of working days in a week, equivalent to len(cal.work_days)."""
        ...
    @property
    def work_hours(self) -> tuple[int, int]:
        """The start and end of the work day in 24-hour time."""
        ...
    @property
    def hours_per_day(self) -> int:
        """Availabe working hours in a day."""
        ...
    @property
    def holidays(self) -> tuple[FlexDate | FixedDate]: ...
    def is_holiday(self, d: date) -> bool:
        """Reports whether the given date is a holiday in this calendar."""
        ...
    def is_workday(self, d: date) -> bool:
        """Reports whether the given date is a work day in this calendar."""
        ...
    def snap_to_work_date(self, d: date, direction: int = 1) -> date:
        """Snap d to the nearest work date in the direction provided."""
        ...
    def offset_work_days(self, start: date, days: int) -> date:
        """Offset from start by the provided number of days. When days=0 and start
        is not a work day, it will snap forward to the next one."""
        ...
    def offset_work_hours(self, start: datetime, hours: float) -> datetime:
        """Offset from start by the provided amount of hours. Same snapping behavior
        as offset_work_days."""
        ...
    def get_work_hours_between(self, start: datetime, end: datetime) -> float:
        """Get the available work hours between the two datetimes, skipping
        weekends and holidays."""
        ...
    def work_hours_before_weekend(self, start: datetime) -> float:
        """Get the work hours available between the start date and the end of
        that week."""
        ...