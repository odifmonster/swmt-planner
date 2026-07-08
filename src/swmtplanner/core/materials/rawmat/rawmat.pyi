from datetime import datetime

from swmtplanner.support import HasID


__all__ = ['RawMat']


class RawMat(HasID[str | int]):
    """A unit of physical raw materials. "Abstract" only in concept — it
    represents raw material generally and is not meant to be instantiated
    directly — but its attributes are concretely stored. Keyed by id."""
    def __init__(self, id: str | int, sku: str, avail_date: datetime, qty: float,
                 unit: str) -> None: ...
    @property
    def id(self) -> str | int:
        """The unique identifier (a str for most materials, a unique int for
        some)."""
        ...
    @property
    def sku(self) -> str:
        """The material's SKU."""
        ...
    @property
    def avail_date(self) -> datetime:
        """When the material becomes available."""
        ...
    @property
    def qty(self) -> float:
        """The quantity on hand."""
        ...
    @property
    def unit(self) -> str:
        """The unit of measure for qty."""
        ...
