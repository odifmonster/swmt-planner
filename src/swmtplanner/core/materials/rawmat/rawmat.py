#!/usr/bin/env python

from typing import TYPE_CHECKING

from swmtplanner.support import HasID

if TYPE_CHECKING:
    from datetime import datetime


class RawMat(HasID[str | int]):

    def __init__(self, id: str | int, sku: str, avail_date: 'datetime', qty: float,
                 unit: str):
        self._id = id
        self._sku = sku
        self._avail_date = avail_date
        self._qty = qty
        self._unit = unit

    @property
    def id(self) -> str | int:
        return self._id

    @property
    def sku(self) -> str:
        return self._sku

    @property
    def avail_date(self) -> 'datetime':
        return self._avail_date

    @property
    def qty(self) -> float:
        return self._qty

    @property
    def unit(self) -> str:
        return self._unit
