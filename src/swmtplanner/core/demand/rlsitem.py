#!/usr/bin/env python

from bisect import insort
from typing import TYPE_CHECKING

from swmtplanner.core.product import Product
from swmtplanner.core.demand.requirement import RawOrder, SafetyOrder
from swmtplanner.core.demand.view import RawView, SafetyView

if TYPE_CHECKING:
    from datetime import datetime, timedelta
    from swmtplanner.core.demand.chunk import Chunk


def _net_raw_reqs(reqs: 'list[tuple[float, datetime]]',
                  on_hand: float) -> 'list[tuple[datetime, float, float]]':
    remaining = on_hand
    netted = []
    for qty, due_date in sorted(reqs, key=lambda r: r[1]):
        covered = min(remaining, qty)
        remaining -= covered
        netted.append((due_date, qty, covered))
    return netted


def _net_safety_reqs(
        reqs: 'list[tuple[float, datetime]]', on_hand: float,
        safety_tgt: float, lead_time: 'timedelta', today: 'datetime'
) -> 'tuple[list[tuple[datetime, float, float]], float]':
    horizon = today + lead_time
    by_due = sorted(reqs, key=lambda r: r[1])
    remaining = on_hand
    netted = []

    # near-term demand: orders due through the horizon (today + lead_time)
    for qty, due_date in by_due:
        if due_date > horizon:
            continue
        covered = min(remaining, qty)
        remaining -= covered
        netted.append((due_date, qty, covered))

    # safety
    safety_covered = min(remaining, safety_tgt)
    remaining -= safety_covered

    # future demand
    for qty, due_date in by_due:
        if due_date <= horizon:
            continue
        covered = min(remaining, qty)
        remaining -= covered
        netted.append((due_date, qty, covered))

    return netted, safety_covered


class RlsItem[T: Product]:

    def __init__(self, item: T, lead_time: 'timedelta', on_hand: float,
                 safety_tgt: float, start_week: tuple[int, int],
                 today: 'datetime',
                 due_reqs: 'list[tuple[float, datetime]]'):
        self._item = item
        self._lead_time = lead_time
        self._safety_tgt = safety_tgt
        self._today = today
        self._init_on_hand = on_hand
        self._chunks = []

        raw_netted = _net_raw_reqs(due_reqs, on_hand)
        raw_orders = [RawOrder(item, qty, covered, start_week, due_date)
                      for due_date, qty, covered in raw_netted]
        self._raw_view = RawView(item, raw_orders)

        safety_netted, safety_on_hand = _net_safety_reqs(
            due_reqs, on_hand, safety_tgt, lead_time, today)
        safety_orders = [SafetyOrder(item, qty, covered, start_week, due_date)
                         for due_date, qty, covered in safety_netted]
        self._safety_view = SafetyView(item, safety_orders, safety_tgt,
                                       safety_on_hand, lead_time, on_hand, today)

    @property
    def item(self) -> T:
        return self._item

    @property
    def raw_view(self) -> 'RawView[T]':
        return self._raw_view

    @property
    def safety_view(self) -> 'SafetyView[T]':
        return self._safety_view

    @property
    def lead_time(self) -> 'timedelta':
        return self._lead_time

    @property
    def safety_tgt(self) -> float:
        return self._safety_tgt

    @property
    def today(self) -> 'datetime':
        return self._today

    @property
    def init_on_hand(self) -> float:
        return self._init_on_hand

    def register_chunk(self, chunk: 'Chunk[T]') -> None:
        insort(self._chunks, chunk, key=lambda c: c.avail_date)

    def register_chunks(self, chunks: 'list[Chunk[T]]') -> None:
        for chunk in chunks:
            self.register_chunk(chunk)

    def register_job(self, job) -> None:
        raise NotImplementedError(
            'register_job is planner-specific; implement it in a subclass'
        )

    def recompute(self) -> None:
        self._raw_view.recompute(self._chunks)
        self._safety_view.recompute(self._chunks)
