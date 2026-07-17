from swmtplanner.core.product import Product

from .order import Order


__all__ = ['SafetyOrder']


class SafetyOrder[T: Product](Order[T]):
    """One individual safety-stock replenishment order. Adds nothing to
    Order."""
    ...
