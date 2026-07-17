#!/usr/bin/env python

from datetime import date
from typing import TYPE_CHECKING

from swmtplanner.core.product import Product

from .requirement import Requirement

if TYPE_CHECKING:
    from datetime import datetime


def _week_offset(first_week: tuple[int, int], due_date: 'datetime') -> int:
    first_monday = date.fromisocalendar(first_week[0], first_week[1], 1)
    iso = due_date.isocalendar()
    due_monday = date.fromisocalendar(iso[0], iso[1], 1)
    return (due_monday - first_monday).days // 7


class Order[T: Product](Requirement[T]):

    def __init__(self, item: T, init_qty: float, covered_on_hand: float,
                 first_week: tuple[int, int], due_date: 'datetime'):
        super().__init__(item, init_qty, covered_on_hand)
        self._due_date = due_date
        self._week_offset = _week_offset(first_week, due_date)

    @property
    def id(self) -> str:
        return (f'P{self._week_offset}-{self._due_date.isoweekday()}'
                f'@{self.item.id}')

    @property
    def week_offset(self) -> int:
        return self._week_offset

    @property
    def due_date(self) -> 'datetime':
        return self._due_date
