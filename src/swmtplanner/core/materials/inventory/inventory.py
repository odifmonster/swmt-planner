#!/usr/bin/env python

from typing import TYPE_CHECKING

from .condition import Exactly, Condition
from .group import ValGroup, SortedGroup

if TYPE_CHECKING:
    from ..rawmat import RawMat


class Inventory[T: RawMat]:

    def __init__(self, grouped: list[str], sorted: list[str]):
        self._by_id = {}
        self._groups = {}
        for attr in grouped:
            self._groups[attr] = ValGroup(attr)
        for attr in sorted:
            self._groups[attr] = SortedGroup(attr)

    def add(self, mat: T) -> None:
        if mat.id in self._by_id:
            raise ValueError(f'material with id {mat.id!r} already in inventory')
        self._by_id[mat.id] = mat
        for group in self._groups.values():
            group.add(mat)

    def remove(self, id: str | int) -> T:
        if id not in self._by_id:
            raise KeyError(f'no material with id {id!r} in inventory')
        mat = self._by_id.pop(id)
        for attr, group in self._groups.items():
            group.remove(id, getattr(mat, attr))
        return mat

    def select_where(self, **conditions) -> list[T]:
        if not conditions:
            return list(self._by_id.values())
        result = None
        for attr, val_or_cond in conditions.items():
            group = self._groups.get(attr)
            if group is None:
                raise KeyError(f'no group for attribute {attr!r}')
            cond = (val_or_cond if isinstance(val_or_cond, Condition)
                    else Exactly(val_or_cond))
            matches = group.get_group(cond)
            result = matches if result is None else result & matches
        return list(result)
