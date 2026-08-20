from datetime import datetime, timedelta

from swmtplanner.core.product import Product
from swmtplanner.core.demand.chunk import Chunk
from swmtplanner.core.demand.requirement import Safety, SafetyOrder

from .demandview import DemandView


__all__ = ['SafetyView']


class SafetyView[T: Product](DemandView[T]):
    """Inventory-level-maintenance tracking. Distributes the chunks it is given
    across the item's SafetyOrders and against its Safety; the main entry point
    for finished-goods inventory-management reporting."""
    def __init__(self, item: T, orders: list[SafetyOrder[T]], safety_tgt: float,
                 safety_on_hand: float, lead_time: timedelta, on_hand: float,
                 today: datetime) -> None:
        """Builds a Safety from safety_tgt with safety_on_hand as its
        covered_on_hand (the netted safety portion, computed by RlsItem).
        on_hand / today / lead_time back the distribution and drainage
        passes."""
        ...
    @property
    def orders(self) -> tuple[SafetyOrder[T], ...]:
        """The view's orders (supplied as a list, exposed as a tuple)."""
        ...
    @property
    def safety(self) -> Safety[T]:
        """The Safety requirement (pool = safety.allocated_qty; shortfall =
        safety.remaining)."""
        ...
    @property
    def carrying(self) -> float:
        """Early supply for future orders, net of lead time."""
        ...
    @property
    def drainage(self) -> float:
        """Time-integral of the physical pool below the safety target."""
        ...
    @property
    def excess(self) -> float:
        """Scalar quantity produced beyond total demand plus safety."""
        ...
    def recompute(self, chunks: list[Chunk[T]]) \
            -> list[tuple[Chunk[T], int | str]]:
        """Runs both passes over `chunks` (sorted by avail_date). Distribution:
        reset orders/safety/metrics, then per chunk (earliest first) fill
        near-term demand (due <= avail + lead_time) -> top up safety -> future
        demand (accruing carrying) -> excess. Drainage: a separate physical-pool
        event walk (on-hand fill at today, full-init_qty drains, chunk fills),
        integrating the pool's deficit below the safety target (clamped to
        [0, safety_tgt]) over [today, last due date].

        Returns the (chunk, first-fill priority) pairs in chunk order: the
        week_offset of the first order the chunk filled, or 'S' when the first
        quantity taken went to the safety requirement. A chunk that fills
        nothing (pure excess) produces no pair."""
        ...
