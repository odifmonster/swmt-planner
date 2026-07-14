#!/usr/bin/env python

from abc import ABC, abstractmethod
from bisect import bisect_left, bisect_right, insort
from typing import TYPE_CHECKING

from ..condition import Exactly, Greater, Less, InRange

if TYPE_CHECKING:
    from ...rawmat import RawMat
    from ..condition import Condition


def _first(pair):
    return pair[0]


class Group[T: RawMat](ABC):

    def __init__(self, attr: str):
        self._attr = attr

    @property
    def attr(self) -> str:
        return self._attr

    @abstractmethod
    def add(self, mat: T) -> None: ...

    @abstractmethod
    def remove(self, id: str | int, val) -> None: ...

    @abstractmethod
    def get_group(self, cond: 'Condition') -> set[T]: ...


class ValGroup[T: RawMat](Group[T]):

    def __init__(self, attr: str):
        super().__init__(attr)
        self._map = {}

    def add(self, mat: T) -> None:
        self._map.setdefault(getattr(mat, self._attr), set()).add(mat)

    def remove(self, id: str | int, val) -> None:
        bucket = self._map.get(val)
        if bucket is not None:
            for mat in bucket:
                if mat.id == id:
                    bucket.discard(mat)
                    if not bucket:
                        del self._map[val]
                    return
        raise KeyError(
            f'no material with id {id!r} at {self._attr}={val!r} in this group'
        )

    def get_group(self, cond: 'Condition') -> set[T]:
        if isinstance(cond, Exactly):
            return set(self._map.get(cond.val, ()))
        pred = cond.to_func()
        result = set()
        for val, mats in self._map.items():
            if pred(val):
                result |= mats
        return result


class SortedGroup[T: RawMat](Group[T]):

    def __init__(self, attr: str):
        super().__init__(attr)
        # (key, mat) pairs sorted by key; the key is snapshotted at add time so
        # a later external mutation of the attribute is detectable on remove.
        self._sorted = []

    def add(self, mat: T) -> None:
        insort(self._sorted, (getattr(mat, self._attr), mat), key=_first)

    def remove(self, id: str | int, val) -> None:
        lo = bisect_left(self._sorted, val, key=_first)
        hi = bisect_right(self._sorted, val, key=_first)
        for i in range(lo, hi):
            if self._sorted[i][1].id == id:
                del self._sorted[i]
                return
        raise KeyError(
            f'no material with id {id!r} at {self._attr}={val!r} in this group'
        )

    def get_group(self, cond: 'Condition') -> set[T]:
        a = self._sorted
        if isinstance(cond, Exactly):
            lo = bisect_left(a, cond.val, key=_first)
            hi = bisect_right(a, cond.val, key=_first)
            return {pair[1] for pair in a[lo:hi]}
        if isinstance(cond, Greater):
            idx = (bisect_left(a, cond.lo, key=_first) if cond.incl
                   else bisect_right(a, cond.lo, key=_first))
            return {pair[1] for pair in a[idx:]}
        if isinstance(cond, Less):
            idx = (bisect_right(a, cond.hi, key=_first) if cond.incl
                   else bisect_left(a, cond.hi, key=_first))
            return {pair[1] for pair in a[:idx]}
        if isinstance(cond, InRange):
            lo = (bisect_left(a, cond.lo, key=_first) if cond.incl_lo
                  else bisect_right(a, cond.lo, key=_first))
            hi = (bisect_right(a, cond.hi, key=_first) if cond.incl_hi
                  else bisect_left(a, cond.hi, key=_first))
            return {pair[1] for pair in a[lo:hi]}
        pred = cond.to_func()
        return {pair[1] for pair in a if pred(pair[0])}
