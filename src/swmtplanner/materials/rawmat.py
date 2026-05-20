#!/usr/bin/env python

import math
from typing import TYPE_CHECKING, Literal

from swmtplanner.support import HasID
from .product import Product, Greige

if TYPE_CHECKING:
    from datetime import date


RollSize = Literal['partial', 'half', 'small', 'full', 'large']


SIZE_PARTIAL_MAX = 0.4
SIZE_HALF_MAX = 0.6
SIZE_SMALL_MAX = 0.95
SIZE_FULL_MAX = 1.05


def _compute_roll_size(qty: float, tgt: float) -> RollSize:
    ratio = qty / tgt
    if ratio < SIZE_PARTIAL_MAX:
        return 'partial'
    if ratio < SIZE_HALF_MAX:
        return 'half'
    if ratio < SIZE_SMALL_MAX:
        return 'small'
    if ratio <= SIZE_FULL_MAX:
        return 'full'
    return 'large'


def _later_avail(a: 'date | None', b: 'date | None') -> 'date | None':
    if a is None and b is None:
        return None
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


class RawMat(HasID[str]):

    def __init__(
        self,
        id_: str,
        product: Product,
        qty: float,
        avail_date: 'date | None',
    ) -> None:
        self._id = id_
        self._product = product
        self._qty = qty
        self._avail_date = avail_date

    @property
    def id(self) -> str:
        return self._id

    @property
    def product(self) -> Product:
        return self._product

    @property
    def qty(self) -> float:
        return self._qty

    @property
    def avail_date(self) -> 'date | None':
        return self._avail_date


class GreigeRoll(RawMat):

    def __init__(
        self,
        id_: str,
        product: Greige,
        qty: float,
        avail_date: 'date | None',
        plant: str,
        item_variant: str,
        yarn_merge: str,
    ) -> None:
        super().__init__(id_, product, qty, avail_date)
        self._plant = plant
        self._item_variant = item_variant
        self._yarn_merge = yarn_merge
        self._size = _compute_roll_size(qty, product.roll_tgt_wt)

    @property
    def product(self) -> Greige:
        return self._product  # type: ignore[return-value]

    @property
    def plant(self) -> str:
        return self._plant

    @property
    def item_variant(self) -> str:
        return self._item_variant

    @property
    def yarn_merge(self) -> str:
        return self._yarn_merge

    @property
    def size(self) -> RollSize:
        return self._size

    def split(self, lbs1: float, lbs2: float) -> 'tuple[GreigeRoll, GreigeRoll]':
        if not math.isclose(lbs1 + lbs2, self._qty):
            raise ValueError(
                f'split weights {lbs1} + {lbs2} = {lbs1 + lbs2} do not match '
                f'roll qty {self._qty}'
            )
        roll_a = GreigeRoll(
            self._id + 'A',
            self.product,
            lbs1,
            self._avail_date,
            self._plant,
            self._item_variant,
            self._yarn_merge,
        )
        roll_b = GreigeRoll(
            self._id + 'B',
            self.product,
            lbs2,
            self._avail_date,
            self._plant,
            self._item_variant,
            self._yarn_merge,
        )
        return roll_a, roll_b

    def combine(self, roll: 'GreigeRoll') -> 'GreigeRoll':
        if self._plant != roll._plant:
            raise ValueError(
                f'cannot combine rolls from different plants: '
                f'{self._plant!r} vs {roll._plant!r}'
            )
        if self.product.id != roll.product.id:
            raise ValueError(
                f'cannot combine rolls of different greige items: '
                f'{self.product.id!r} vs {roll.product.id!r}'
            )
        variant = (
            self._item_variant
            if self._item_variant == roll._item_variant
            else self._item_variant + roll._item_variant
        )
        merge = (
            self._yarn_merge
            if self._yarn_merge == roll._yarn_merge
            else self._yarn_merge + roll._yarn_merge
        )
        return GreigeRoll(
            self._id + roll._id,
            self.product,
            self._qty + roll._qty,
            _later_avail(self._avail_date, roll._avail_date),
            self._plant,
            variant,
            merge,
        )
