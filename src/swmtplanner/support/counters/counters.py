#!/usr/bin/env python


from typing import Callable, TypedDict


def _mk_counter():
    ctr = 0
    def func():
        nonlocal ctr
        ctr += 1
        return ctr
    return func


class _CounterEntry(TypedDict):
    cur: int
    func: Callable[[], int]


class Counters:

    def __init__(self, names = []):
        self._map: dict[str, _CounterEntry] = \
            { name: { 'cur': 0, 'func': _mk_counter() } for name in names }
    
    def __call__(self, ctr_name: str) -> int:
        if ctr_name not in self._map:
            raise KeyError(f'object has no counter named \'{ctr_name}\'')
        return self._map[ctr_name]['cur']
    
    @property
    def ctr_names(self):
        return tuple(self._map.keys())
    
    def advance(self, ctr_name: str) -> int:
        if ctr_name not in self._map:
            raise KeyError(f'object has no counter named \'{ctr_name}\'')
        
        entry = self._map[ctr_name]
        entry['cur'] = entry['func']()
        return entry['cur']
    
    def add_counter(self, ctr_name: str) -> None:
        if ctr_name in self._map:
            raise KeyError(f'counter with name \'{ctr_name}\' already exists')
        self._map[ctr_name] = { 'cur': 0, 'func': _mk_counter() }