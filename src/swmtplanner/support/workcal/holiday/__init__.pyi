from dataclasses import dataclass
from abc import abstractmethod
from datetime import date


__all__ = ['Holiday', 'FixedDate', 'FlexDate']


@dataclass
class Holiday:
    """Abstract base class for holidays."""
    name: str
    month: int
    @abstractmethod
    def date_in_year(self, year: int) -> date:
        """Get the date this holiday falls on in the given year."""
        ...


@dataclass(frozen=True)
class FixedDate(Holiday):
    """Represents a holiday that falls on a fixed date every year."""
    day: int


@dataclass(frozen=True)
class FlexDate(Holiday):
    """Represents a holiday that falls on the nth weekday of some month."""
    weekday: int
    n: int