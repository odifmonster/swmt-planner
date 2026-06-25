from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


__all__ = ['Holiday', 'FixedDate', 'FlexDate', 'load_holidays']


class Holiday(ABC):
    """Abstract base class for a recurring holiday."""
    name: str
    month: int
    @abstractmethod
    def get_date_in_year(self, year: int) -> date:
        """The date on which this holiday falls in the given year."""
        ...


@dataclass(frozen=True)
class FixedDate(Holiday):
    """A holiday that falls on the same calendar date every year (e.g.
    Christmas)."""
    name: str
    month: int
    day: int
    def get_date_in_year(self, year: int) -> date: ...


@dataclass(frozen=True)
class FlexDate(Holiday):
    """A holiday that falls on the nth occurrence of a weekday within its month
    (e.g. Memorial Day). weekday uses 0 = Monday; n is 1-indexed and may be
    negative (n = -1 is the last such weekday of the month)."""
    name: str
    month: int
    weekday: int
    n: int
    def get_date_in_year(self, year: int) -> date: ...


def load_holidays(json_str: str) -> list[Holiday]:
    """Parse a list of holidays from a JSON string. Each holiday is a JSON
    object whose keys are the dataclass fields of the matching Holiday subclass.
    Raises ValueError if the string does not describe a valid list of
    holidays."""
    ...
