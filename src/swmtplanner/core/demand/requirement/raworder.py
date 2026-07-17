#!/usr/bin/env python

from bisect import insort
from typing import TYPE_CHECKING

from swmtplanner.core.product import Product

from .order import Order

if TYPE_CHECKING:
    from datetime import datetime, timedelta
    from swmtplanner.core.demand.chunk import Chunk


class RawOrder[T: Product](Order[T]):

    def __init__(self, item: T, init_qty: float, covered_on_hand: float,
                 first_week: tuple[int, int], due_date: 'datetime'):
        super().__init__(item, init_qty, covered_on_hand, first_week, due_date)
        self._on_time = []
        self._late = []

    @property
    def late_fill_date(self) -> 'datetime | None':
        if not self._late:
            return None
        return self._late[-1].avail_date

    @property
    def late_qty(self) -> float:
        return sum((c.qty for c in self._late), 0.0)

    def late_table(self) -> 'list[tuple[timedelta, float]]':
        return [(c.avail_date - self._due_date, c.qty) for c in self._late]

    def clear_chunks(self) -> None:
        self._on_time.clear()
        self._late.clear()

    def add_chunk(self, chunk: 'Chunk[T]') -> None:
        target = (self._on_time if chunk.avail_date <= self._due_date
                  else self._late)
        insort(target, chunk, key=lambda c: c.avail_date)
