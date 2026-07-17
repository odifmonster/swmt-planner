#!/usr/bin/env python

from dataclasses import dataclass
from typing import TYPE_CHECKING

from swmtplanner.core.product import Product

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True)
class Chunk[T: Product]:

    item: T
    avail_date: 'datetime'
    qty: float
