#!/usr/bin/env python

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from swmtplanner.support import HasID, mk_counter

if TYPE_CHECKING:
    from datetime import datetime


_next_idx = mk_counter()


@dataclass(frozen=True, eq=False)
class Activity(HasID[str]):

    start: 'datetime'
    end: 'datetime'
    _idx: int = field(default_factory=_next_idx, kw_only=True)

    @property
    def id(self) -> str:
        return f'{type(self).__name__.upper()}{self._idx:08d}'


@dataclass(frozen=True, eq=False)
class Idle(Activity):
    pass
