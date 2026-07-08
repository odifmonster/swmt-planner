from ..rawmat import RawMat
from .condition import Condition


__all__ = ['Inventory']


class Inventory[T: RawMat]:
    """Holds a set of RawMat objects grouped by the values of certain attributes,
    supporting selection of the subset meeting a set of conditions. Maintains an
    internal id -> RawMat map plus one group per grouped/sorted attribute."""
    def __init__(self, grouped: list[str], sorted: list[str]) -> None:
        """Build an inventory. Each `grouped` attribute is backed by a ValGroup
        and each `sorted` attribute by a SortedGroup."""
        ...
    def add(self, mat: T) -> None:
        """Add a material to the inventory and to every group. Raises ValueError
        if a material with the same id is already present."""
        ...
    def remove(self, id: str | int) -> T:
        """Remove and return the material with the given id. Raises KeyError if no
        material with that id is in the inventory."""
        ...
    def select_where(self, **conditions: Condition | object) -> list[T]:
        """Return the materials meeting all the provided conditions (the
        intersection across attributes). Each keyword value is a Condition or a
        plain value (treated as Exactly). With no conditions, returns all
        materials; a keyword naming an attribute with no group raises KeyError."""
        ...
