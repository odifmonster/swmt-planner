#!/usr/bin/env python

from swmtplanner.support import HasID
from swmtplanner.core.product import Product


class Requirement[T: Product](HasID[str]):

    def __init__(self, item: T, init_qty: float, covered_on_hand: float):
        self._item = item
        self._init_qty = init_qty
        self._covered_on_hand = covered_on_hand
        self._allocated_qty = 0.0

    @property
    def id(self) -> str:
        raise NotImplementedError(
            'Requirement is abstract; each subclass defines its id format'
        )

    @property
    def item(self) -> T:
        return self._item

    @property
    def init_qty(self) -> float:
        return self._init_qty

    @property
    def covered_on_hand(self) -> float:
        return self._covered_on_hand

    @property
    def allocated_qty(self) -> float:
        return self._allocated_qty

    @allocated_qty.setter
    def allocated_qty(self, value: float) -> None:
        self._allocated_qty = value

    @property
    def remaining(self) -> float:
        return max(0.0, self._init_qty - self._covered_on_hand
                   - self._allocated_qty)
