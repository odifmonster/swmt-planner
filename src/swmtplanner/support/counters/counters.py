#!/usr/bin/env python

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Callable


def mk_counter(start: int = 0):
    ctr = start - 1
    def func():
        nonlocal ctr
        ctr += 1
        return ctr
    return func


class Counters:

    def __init__(self, names: list[str] = [], **kwargs):
        if not names and len(kwargs) == 0:
            raise ValueError(
                'must provide either a list of names or names and '
                'starting values as keyword arguments'
            )
        name_set = set(names)
        if (overlap:=name_set.intersection(kwargs.keys())):
            raise ValueError(
                ', '.join([repr(x) for x in overlap]) + ' appear in both '
                'name list and keywords'
            )
        
        starts: dict[str, int] = dict(kwargs)
        for name in name_set:
            starts[name] = 0

        self._vals: dict[str, int] = {}
        self._ctrs: 'dict[str, Callable[[], int]]' = {
            name: mk_counter(start=start) for name, start in starts.items()
        }
    
    def __call__(self, name: str, advance: bool = True) -> int:
        if name not in self._ctrs:
            raise KeyError(f'no counter {name!r}')
        if name not in self._vals and not advance:
            raise ValueError(f'counter {name!r} not yet started')
        
        if advance:
            self._vals[name] = self._ctrs[name]()
        return self._vals[name]
    
    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._ctrs.keys())