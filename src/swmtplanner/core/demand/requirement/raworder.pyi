from datetime import datetime, timedelta

from swmtplanner.core.product import Product
from swmtplanner.core.demand.chunk import Chunk

from .order import Order


__all__ = ['RawOrder']


class RawOrder[T: Product](Order[T]):
    """One individual hard-requirement order. Records the chunks the RawView
    allocates to it in two sorted lists — on-time and late — and reports late
    arrivals for supply landing after its due_date."""
    def __init__(self, item: T, init_qty: float, covered_on_hand: float,
                 first_week: tuple[int, int], due_date: datetime) -> None: ...
    @property
    def late_fill_date(self) -> datetime | None:
        """If the order is late, the last date the schedule produces something
        against it; None if it is not late."""
        ...
    @property
    def late_qty(self) -> float:
        """The total quantity arriving after due_date."""
        ...
    def late_table(self) -> list[tuple[timedelta, float]]:
        """Every late chunk as (lag past due_date, quantity) pairs."""
        ...
    def clear_chunks(self) -> None:
        """Empty both chunk lists (called before the view re-distributes)."""
        ...
    def add_chunk(self, chunk: Chunk[T]) -> None:
        """Classify the chunk as on-time (avail_date <= due_date) or late, and
        insert it into the matching list in avail_date order."""
        ...
