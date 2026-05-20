#!/usr/bin/env python

import calendar
from dataclasses import dataclass
from abc import abstractmethod
from datetime import date


@dataclass(frozen=True)
class Holiday:
    name: str
    month: int

    @abstractmethod
    def date_in_year(self, year: int) -> date:
        raise NotImplementedError()


@dataclass(frozen=True)
class FixedDate(Holiday):
    day: int

    def date_in_year(self, year):
        return date(year, self.month, self.day)


@dataclass(frozen=True)
class FlexDate(Holiday):
    weekday: int
    n: int

    def date_in_year(self, year):
        if self.n >= 0:
            first = date(year, self.month, 1)
            offset = (self.weekday - first.weekday()) % 7
            day = 1 + offset + (self.n - 1) * 7
        else:
            last_day = calendar.monthrange(year, self.month)[1]
            last_weekday = date(year, self.month, last_day).weekday()
            offset = (last_weekday - self.weekday) % 7
            day = last_day - offset + (self.n + 1) * 7
        return date(year, self.month, day)