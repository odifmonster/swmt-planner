from swmtplanner.core.product import Product

from .demandview import DemandView
from ..chunk import Chunk
from ..requirement import RawOrder


__all__ = ['RawView']


class RawView[T: Product](DemandView[T]):
    """Order-lateness tracking. Distributes the chunks it is given across the
    item's RawOrders; the main entry point for order-fulfillment reporting."""
    late_base: float   # tunable base of the lateness penalty; defaults to 2.0
    @property
    def orders(self) -> tuple[RawOrder[T], ...]:
        """The view's orders (supplied as a list, exposed as a tuple)."""
        ...
    @property
    def lateness(self) -> float:
        """The item's total lateness as a single number: the sum over every late
        chunk/order application of qty * late_base ** days_late, where days_late
        = (avail_date - due_date) in days. Read off the orders' late_table()
        entries."""
        ...
    def recompute(self, chunks: list[Chunk[T]]) -> None:
        """Reset each order (allocated_qty = 0, clear_chunks), then walk `chunks`
        (sorted by avail_date) earliest-first, filling orders in due-date order
        up to each one's remaining. A chunk spanning several orders is split — a
        fresh Chunk of the allocated portion is added to each order (which
        classifies it on-time/late by its own due_date) — and allocated_qty is
        updated in step. Surplus beyond all orders is ignored."""
        ...
