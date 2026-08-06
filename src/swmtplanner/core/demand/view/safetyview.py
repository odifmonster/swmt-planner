#!/usr/bin/env python

from typing import TYPE_CHECKING

from swmtplanner.core.product import Product
from swmtplanner.core.demand.requirement import Safety

from .demandview import DemandView

if TYPE_CHECKING:
    from datetime import datetime, timedelta
    from swmtplanner.core.demand.chunk import Chunk
    from swmtplanner.core.demand.requirement import SafetyOrder


def _days(delta: 'timedelta') -> float:
    return delta.total_seconds() / 86400


class SafetyView[T: Product](DemandView[T]):

    def __init__(self, item: T, orders: 'list[SafetyOrder[T]]',
                 safety_tgt: float, safety_on_hand: float,
                 lead_time: 'timedelta', on_hand: float, today: 'datetime'):
        super().__init__(item, orders)
        self._safety = Safety(item, safety_tgt, safety_on_hand)
        self._lead_time = lead_time
        self._on_hand = on_hand
        self._today = today
        self._carrying = 0.0
        self._drainage = 0.0
        self._excess = 0.0

    @property
    def safety(self) -> 'Safety[T]':
        return self._safety

    @property
    def carrying(self) -> float:
        return self._carrying

    @property
    def drainage(self) -> float:
        return self._drainage

    @property
    def excess(self) -> float:
        return self._excess

    def recompute(self, chunks: 'list[Chunk[T]]') -> None:
        for order in self.orders:
            order.allocated_qty = 0.0
        self._safety.allocated_qty = 0.0
        self._carrying = 0.0
        self._excess = 0.0

        by_due = sorted(self.orders, key=lambda o: o.due_date)
        for chunk in chunks:
            left = chunk.qty
            horizon = chunk.avail_date + self._lead_time

            # (1) near-term demand: unfilled orders due on/before the horizon
            for order in by_due:
                if left <= 0:
                    break
                if order.due_date <= horizon and order.remaining > 0:
                    take = min(left, order.remaining)
                    order.allocated_qty += take
                    left -= take

            # (2) safety
            if left > 0:
                take = min(left, self._safety.remaining)
                self._safety.allocated_qty += take
                left -= take

            # (3) future demand -> carrying (held beyond the lead time)
            for order in by_due:
                if left <= 0:
                    break
                if order.due_date > horizon and order.remaining > 0:
                    take = min(left, order.remaining)
                    order.allocated_qty += take
                    left -= take
                    self._carrying += take * _days(
                        (order.due_date - chunk.avail_date) - self._lead_time)

            # (4) excess
            if left > 0:
                self._excess += left

        self._drainage = self._compute_drainage(chunks)

    def _compute_drainage(self, chunks: 'list[Chunk[T]]') -> float:
        if not self.orders:
            return 0.0
        safety_tgt = self._safety.init_qty
        window_end = max(order.due_date for order in self.orders)

        events = [(self._today, self._on_hand)]
        events += [(max(order.due_date, self._today), -order.init_qty)
                   for order in self.orders]
        events += [(chunk.avail_date, chunk.qty) for chunk in chunks]
        events.sort(key=lambda e: (e[0], 0 if e[1] > 0 else 1))

        total = 0.0
        pool = 0.0
        for (t1, delta), (t2, _) in zip(events, events[1:]):
            pool += delta
            lo = max(t1, self._today)
            hi = min(t2, window_end)
            if hi > lo:
                deficit = max(0.0, min(safety_tgt, safety_tgt - pool))
                total += deficit * _days(hi - lo)
        return total
