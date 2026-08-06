from swmtplanner.core.product import Product
from swmtplanner.core.demand.chunk import Chunk
from swmtplanner.core.demand.requirement import Order


__all__ = ['DemandView']


class DemandView[T: Product]:
    """Abstract base for the two views. Holds the item and its orders; it does
    not store chunks — recompute receives the full chunk list each call. `item`
    and `orders` are supplied at construction (`orders` as a list, exposed as a
    tuple). recompute is subclass-specific (raises NotImplementedError on the
    base)."""
    def __init__(self, item: T, orders: list[Order[T]]) -> None: ...
    @property
    def item(self) -> T:
        """The product style this view is for."""
        ...
    @property
    def orders(self) -> tuple[Order[T], ...]:
        """The view's orders (supplied as a list, exposed as a tuple)."""
        ...
    def recompute(self, chunks: list[Chunk[T]]) -> None:
        """Distribute `chunks` (expected sorted by avail_date) across the view's
        orders / requirements per that view's rules. Abstract: raises
        NotImplementedError on the base; each concrete view overrides it."""
        ...
