#!/usr/bin/env python

from typing import TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from typing import Callable, Any


def in_range[T](excl_lo=False, excl_hi=True):
    def func(val: T, rng: tuple[T, T]) -> bool:
        lo, hi = rng
        comp1 = val > lo if excl_lo else val >= lo
        comp2 = val < hi if excl_hi else val <= hi
        return comp1 and comp2
    return func


@dataclass(frozen=True)
class GroupKey:
    op: 'Callable[[Any, Any], bool]'
    value: 'Any'

    def __call__(self, val):
        return self.op(val, self.value)