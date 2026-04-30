from typing import NamedTuple

__all__ = ['FixedDate', 'FlexDate', 'HOLIDAYS']

HOLIDAYS: dict[str, FixedDate | FlexDate] = ...

class FixedDate(NamedTuple):
    """Represents a holiday that occurs on the same date every year."""
    month: int
    day: int

class FlexDate(NamedTuple):
    """Represents a holiday that occurs on the nth weekday of some month every year."""
    month: int
    weekday: int
    n: int