from typing import NamedTuple

__all__ = ['FixedDate', 'FlexDate', 'load_holidays']

class FixedDate(NamedTuple):
    """Represents a holiday that occurs on the same date every year."""
    name: str
    month: int
    day: int

class FlexDate(NamedTuple):
    """Represents a holiday that occurs on the nth weekday of some month every year."""
    name: str
    month: int
    weekday: int
    n: int

def load_holidays(path: str) -> list[FixedDate | FlexDate]:
    """Loads a list of holidays from a json file."""
    ...