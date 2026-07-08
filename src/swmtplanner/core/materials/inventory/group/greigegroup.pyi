from typing import Any

from ...rawmat import GreigeRoll
from .group import ValGroup


__all__ = [
    'GreigeGroup',
    'MIN_PORT_LBS', 'MAX_PORT_LBS', 'PORT_EVEN_TOL', 'MAX_TRIM_LBS',
]


# dye-lot / jet-port loading limits (may change if the jets are replaced)
MIN_PORT_LBS: int    # minimum lbs a jet port may be loaded with
MAX_PORT_LBS: int    # maximum lbs a jet port may be loaded with
PORT_EVEN_TOL: int   # max lbs difference between ports in a lot
MAX_TRIM_LBS: int    # max lbs discarded from a roll when combining to reach standard


class GreigeGroup(ValGroup[GreigeRoll]):
    """A planner-specific ValGroup[GreigeRoll] keyed on the roll's sku (the greige
    style). It assembles the rolls of each style into dye lots (each lot's ports
    within PORT_EVEN_TOL lbs of one another, all in [MIN_PORT_LBS, MAX_PORT_LBS]).
    Lots are cached per style and invalidated when a roll of that style is added
    or removed."""
    def __init__(self) -> None: ...
    @property
    def skus(self) -> set[str]:
        """The set of sku values currently in the group."""
        ...
    def add(self, mat: GreigeRoll) -> None: ...
    def remove(self, id: str | int, val: Any) -> None: ...
    def prepare_dye_pool(self) -> None:
        """Group each style's rolls into valid dye lots and cache them per style
        (only for styles not already cached)."""
        ...
    def dye_lots(self, style: str) -> list[set[GreigeRoll]]:
        """The cached list of the largest disjoint sets of compatible rolls for
        style. Raises KeyError if the style has no cached lots."""
        ...
    def has_cached_lots(self, style: str) -> bool:
        """Whether valid cached lots exist for style."""
        ...
