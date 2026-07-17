from swmtplanner.support import HasID
from swmtplanner.core.product import Product


__all__ = ['Requirement']


class Requirement[T: Product](HasID[str]):
    """A single quantity requirement on a product item. "Abstract" in concept —
    each subclass defines its id format — but its attributes are concretely
    stored. Keyed by id."""
    def __init__(self, item: T, init_qty: float,
                 covered_on_hand: float) -> None: ...
    @property
    def id(self) -> str:
        """The unique identifier; abstract — defined per subclass (raises
        NotImplementedError on Requirement itself)."""
        ...
    @property
    def item(self) -> T:
        """The product style this requirement is against."""
        ...
    @property
    def init_qty(self) -> float:
        """The initial quantity required."""
        ...
    @property
    def covered_on_hand(self) -> float:
        """How much of init_qty is already covered by on-hand inventory."""
        ...
    @property
    def allocated_qty(self) -> float:
        """How much the current schedule has allocated to this requirement.
        Starts at 0.0; settable, so the views can update it as they distribute
        jobs."""
        ...
    @allocated_qty.setter
    def allocated_qty(self, value: float) -> None: ...
    @property
    def remaining(self) -> float:
        """max(0.0, init_qty - covered_on_hand - allocated_qty): the quantity
        still unmet after on-hand coverage and the current allocation."""
        ...
