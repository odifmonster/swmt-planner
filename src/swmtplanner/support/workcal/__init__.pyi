from typing import Sequence
from datetime import datetime, date

__all__ = ['WorkCal']

class WorkCal:
    """
    A class for defining custom business calendars and performing datetime
    calculations with them.
    """
    def __init__(self, business_hrs: tuple[int, int], work_days: Sequence[int],
                 start: datetime, holidays: Sequence[date], cal_shift: float = ...) -> None:
        """
        Initialize a new WorkCal object.

          business_hrs:
            A 2-tuple representing the start and end of the business day as
            integers (0-24).
          work_days:
            A sequence of integers corresponding to the working days of the
            week where Monday=0.
          start:
            The date and time this working calendar starts.
          holidays:
            A sequence of dates corresponding to non-working holidays.
          cal_shift (default=0):
            For 24-hour days only. A float representing the number of hours to
            "shift" this calendar from standard day boundaries. For example,
            if the first shift of the day starts at 11pm, you should pass in -1
            here.
        """
        ...
    @property
    def wd_start(self) -> int:
        """The hour when the work day starts (0-24)."""
        ...
    @property
    def wd_end(self) -> int:
        """The hour when the work day ends (0-24)."""
        ...
    @property
    def work_days(self) -> tuple[int, ...]:
        """The business days as integers (Monday=0)."""
        ...
    def add_work_hrs(self, start: datetime, hrs: float) -> datetime:
        """
        Convert a duration in working hours to a real end datetime.

          start:
            The start datetime of the working interval.
          hrs:
            The number of working hours in the interval.
        
        Returns the end datetime of the provided working interval.
        """
        ...
    def get_work_hrs_between(self, start: datetime, end: datetime) -> float:
        """
        Calculate the available working hours between two datetimes.

          start:
            The start datetime.
          end:
            The end datetime.
        
        Returns the available working hours as a float.
        """
        ...