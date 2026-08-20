#!/usr/bin/env python

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from swmtplanner.support import HasID, mk_counter
from swmtplanner.core.product import Product

if TYPE_CHECKING:
    from datetime import datetime


_next_id = mk_counter()


@dataclass(frozen=True, eq=False)
class Chunk[T: Product](HasID[int]):

    item: T
    avail_date: 'datetime'
    qty: float
    _id: int = field(default_factory=_next_id)

    @property
    def id(self) -> int:
        return self._id
