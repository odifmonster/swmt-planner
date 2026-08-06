#!/usr/bin/env python

from typing import TYPE_CHECKING

from swmtplanner.core.product import Product

if TYPE_CHECKING:
    from swmtplanner.core.demand.chunk import Chunk
    from swmtplanner.core.demand.requirement import Order


class DemandView[T: Product]:

    def __init__(self, item: T, orders: 'list[Order[T]]'):
        self._item = item
        self._orders = tuple(orders)

    @property
    def item(self) -> T:
        return self._item

    @property
    def orders(self) -> 'tuple[Order[T], ...]':
        return self._orders

    def recompute(self, chunks: 'list[Chunk[T]]') -> None:
        raise NotImplementedError(
            'DemandView is abstract; concrete views implement recompute'
        )
