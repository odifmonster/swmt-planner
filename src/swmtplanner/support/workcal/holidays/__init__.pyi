from typing import Any, NamedTuple

__all__ = [
    'FixedDate', 'FlexDate', 'holidays_from_list', 'load_holidays',
]

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

def holidays_from_list(
    holidays: list[Any], source: str = ...,
) -> list[FixedDate | FlexDate]:
    """Builds a list of holidays from an already-parsed list."""
    ...

def load_holidays(path: str) -> list[FixedDate | FlexDate]:
    """Loads a list of holidays from a json file."""
    ...