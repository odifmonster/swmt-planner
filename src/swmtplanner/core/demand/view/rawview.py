#!/usr/bin/env python

from swmtplanner.core.product import Product
from swmtplanner.core.demand.chunk import Chunk

from .demandview import DemandView


class RawView[T: Product](DemandView[T]):

    late_base = 2.0

    @property
    def lateness(self) -> float:
        return sum(qty * self.late_base ** (lag.total_seconds() / 86400)
                   for o in self.orders
                   for (lag, qty) in o.late_table())

    def recompute(self, chunks: 'list[Chunk[T]]') -> None:
        for order in self.orders:
            order.allocated_qty = 0.0
            order.clear_chunks()

        by_due = sorted(self.orders, key=lambda o: o.due_date)
        i = 0

        for chunk in chunks:
            left = chunk.qty

            while left > 0 and i < len(by_due):
                order = by_due[i]
                need = order.remaining

                if need <= 0:
                    i += 1
                    continue

                take = min(left, need)
                order.allocated_qty += take
                order.add_chunk(Chunk(chunk.item, chunk.avail_date, take))
                
                left -= take
                if take == need:
                    i += 1
