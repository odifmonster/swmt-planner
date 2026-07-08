from typing import Any, Callable
from dataclasses import dataclass


__all__ = ['Exactly', 'NotExactly', 'Greater', 'Less', 'InRange', 'Condition']


@dataclass(frozen=True)
class Exactly:
    """Matches values equal to val."""
    val: Any
    def to_func(self) -> Callable[[Any], bool]:
        """A function returning True iff the value equals val."""
        ...


@dataclass(frozen=True)
class NotExactly:
    """Matches values not equal to val."""
    val: Any
    def to_func(self) -> Callable[[Any], bool]:
        """A function returning True iff the value does not equal val."""
        ...


@dataclass(frozen=True)
class Greater:
    """Matches values greater than lo (or >= lo when incl)."""
    lo: Any
    incl: bool = ...
    def to_func(self) -> Callable[[Any], bool]:
        """A function returning True iff the value is greater than lo (>= lo when
        incl)."""
        ...


@dataclass(frozen=True)
class Less:
    """Matches values less than hi (or <= hi when incl)."""
    hi: Any
    incl: bool = ...
    def to_func(self) -> Callable[[Any], bool]:
        """A function returning True iff the value is less than hi (<= hi when
        incl)."""
        ...


@dataclass(frozen=True)
class InRange:
    """Matches values between lo and hi, including lo iff incl_lo and hi iff
    incl_hi."""
    lo: Any
    hi: Any
    incl_lo: bool = ...
    incl_hi: bool = ...
    def to_func(self) -> Callable[[Any], bool]:
        """A function returning True iff the value is within the range."""
        ...


Condition = Exactly | NotExactly | Greater | Less | InRange
