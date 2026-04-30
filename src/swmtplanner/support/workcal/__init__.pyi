from datetime import date, datetime, timedelta

from . import holidays

HOLIDAYS = holidays.HOLIDAYS

__all__ = ['holidays', 'HOLIDAYS', 'WorkCal']

class WorkCal:
    """Convenience class for working with custom business calendars.
    It provides methods for calculating working days and hours, taking
    into account holidays and weekends."""
    def __init__(self, work_days: list[int], day_start: int, day_end: int, holidays: list[str]) -> None:
        ...
    @property
    def work_days(self) -> tuple[int, ...]:
        """All the work days in a week, as integers where Monday is 0 and Sunday is 6."""
        ...
    @property
    def work_days_per_week(self) -> int: ...
    @property
    def work_hours(self) -> tuple[int, int]:
        """The start and end hours of the work day."""
        ...
    @property
    def work_hours_per_day(self) -> int: ...
    @property
    def holidays(self) -> tuple[holidays.FlexDate | holidays.FixedDate]: ...
    def add_work_days(self, start: date, days: int) -> date:
        """Add a given number of work days to the start date. Negative values walk backward."""
        ...
    def add_work_hours(self, start: datetime, hours: float) -> datetime:
        """Add a given number of work hours to the start datetime. Negative values walk backward."""
        ...
    def get_work_hours_between(self, start: datetime, end: datetime) -> float:
        """Get the total available work hours between the start and end datetimes."""