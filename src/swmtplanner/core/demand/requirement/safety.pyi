from swmtplanner.core.product import Product

from .requirement import Requirement


__all__ = ['Safety']


class Safety[T: Product](Requirement[T]):
    """The remaining safety-stock replenishment needed on an item. Adds nothing
    to Requirement beyond the id format."""
    @property
    def id(self) -> str:
        """f'S@{item.id}'."""
        ...
