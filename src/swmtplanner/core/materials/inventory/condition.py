#!/usr/bin/env python

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Callable


@dataclass(frozen=True)
class Exactly:

    val: 'Any'

    def to_func(self) -> 'Callable[[Any], bool]':
        val = self.val
        return lambda x: x == val


@dataclass(frozen=True)
class NotExactly:

    val: 'Any'

    def to_func(self) -> 'Callable[[Any], bool]':
        val = self.val
        return lambda x: x != val


@dataclass(frozen=True)
class Greater:

    lo: 'Any'
    incl: bool = False

    def to_func(self) -> 'Callable[[Any], bool]':
        lo, incl = self.lo, self.incl
        if incl:
            return lambda x: x >= lo
        return lambda x: x > lo


@dataclass(frozen=True)
class Less:

    hi: 'Any'
    incl: bool = False

    def to_func(self) -> 'Callable[[Any], bool]':
        hi, incl = self.hi, self.incl
        if incl:
            return lambda x: x <= hi
        return lambda x: x < hi


@dataclass(frozen=True)
class InRange:

    lo: 'Any'
    hi: 'Any'
    incl_lo: bool = True
    incl_hi: bool = False

    def to_func(self) -> 'Callable[[Any], bool]':
        lo, hi, incl_lo, incl_hi = self.lo, self.hi, self.incl_lo, self.incl_hi
        def check(x):
            lo_ok = x >= lo if incl_lo else x > lo
            hi_ok = x <= hi if incl_hi else x < hi
            return lo_ok and hi_ok
        return check


Condition = Exactly | NotExactly | Greater | Less | InRange
