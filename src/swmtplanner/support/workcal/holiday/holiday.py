#!/usr/bin/env python

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, fields
from datetime import date
from calendar import monthrange


class Holiday(ABC):

    name: str
    month: int

    @abstractmethod
    def get_date_in_year(self, year: int) -> date:
        raise NotImplementedError(
            'implementers of Holiday must provide a \'get_date_in_year\' '
            'implementation'
        )


@dataclass(frozen=True)
class FixedDate(Holiday):

    name: str
    month: int
    day: int

    def get_date_in_year(self, year: int) -> date:
        return date(year, self.month, self.day)


@dataclass(frozen=True)
class FlexDate(Holiday):

    name: str
    month: int
    weekday: int
    n: int

    def get_date_in_year(self, year: int) -> date:
        if self.n > 0:
            first = date(year, self.month, 1)
            offset = (self.weekday - first.weekday()) % 7
            day = 1 + offset + (self.n - 1) * 7
        else:
            last_day = monthrange(year, self.month)[1]
            last = date(year, self.month, last_day)
            offset = (last.weekday() - self.weekday) % 7
            day = last_day - offset + (self.n + 1) * 7
        return date(year, self.month, day)


_HOLIDAY_TYPES: tuple[type[Holiday], ...] = (FixedDate, FlexDate)
_FIELDS_TO_TYPE: dict[frozenset[str], type[Holiday]] = {
    frozenset(f.name for f in fields(cls)): cls for cls in _HOLIDAY_TYPES
}


def load_holidays(json_str: str) -> list[Holiday]:
    data = json.loads(json_str)
    if not isinstance(data, list):
        raise ValueError('holiday JSON must describe a list of holidays')

    holidays: list[Holiday] = []
    for i, obj in enumerate(data):
        if not isinstance(obj, dict):
            raise ValueError(f'holiday at index {i} is not a JSON object')
        cls = _FIELDS_TO_TYPE.get(frozenset(obj.keys()))
        if cls is None:
            raise ValueError(
                f'holiday at index {i} does not match any known holiday type; '
                f'got fields {sorted(obj.keys())}'
            )
        holidays.append(cls(**obj))
    return holidays
