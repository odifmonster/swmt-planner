#!/usr/bin/env python

from typing import TYPE_CHECKING

from swmtplanner.support import HasID
from ...product import Product

if TYPE_CHECKING:
    from datetime import date


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
