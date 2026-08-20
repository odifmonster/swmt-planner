from dataclasses import dataclass
from datetime import datetime

from swmtplanner.support import HasID
from swmtplanner.core.product import Product


__all__ = ['Chunk']


@dataclass(frozen=True, eq=False)
class Chunk[T: Product](HasID[int]):
    """A quantity of product becoming available on a date — the unit of
    scheduled supply fed into an RlsItem. Implements HasID[int]; declared
    eq=False so HasID's id-based eq/hash apply rather than field-wise
    equality — two chunks with identical item/date/qty are still distinct."""
    item: T
    avail_date: datetime
    qty: float
    @property
    def id(self) -> int:
        """A unique auto-incremented int, assigned by the private field's
        default factory (a module-level counter); never passed explicitly."""
        ...
