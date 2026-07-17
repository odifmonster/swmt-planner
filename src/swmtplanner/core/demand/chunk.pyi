from dataclasses import dataclass
from datetime import datetime

from swmtplanner.core.product import Product


__all__ = ['Chunk']


@dataclass(frozen=True)
class Chunk[T: Product]:
    """A quantity of product becoming available on a date — the unit of
    scheduled supply fed into an RlsItem."""
    item: T
    avail_date: datetime
    qty: float
