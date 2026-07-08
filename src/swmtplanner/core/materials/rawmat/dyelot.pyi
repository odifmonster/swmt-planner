from datetime import datetime
from collections.abc import Iterator

from .greigeroll import GreigeRoll


__all__ = ['DyeLot']


class DyeLot:
    """A group of GreigeRolls (all sharing a sku and a plant) that tracks the
    group's aggregate qualities."""
    def __init__(self, rolls: list[GreigeRoll]) -> None:
        """Build a dye lot from a (possibly empty) list of rolls; raises
        ValueError unless they all share a sku and a plant."""
        ...
    @property
    def sku(self) -> str | None:
        """The shared sku of the component rolls; None if the lot is empty."""
        ...
    @property
    def plant(self) -> str | None:
        """The shared plant of the component rolls; None if the lot is empty."""
        ...
    @property
    def avail_date(self) -> datetime | None:
        """The maximum avail_date among the component rolls; None if the lot is
        empty."""
        ...
    @property
    def total_lbs(self) -> float:
        """The total pounds across the rolls (sum of qty); 0 if empty."""
        ...
    @property
    def n_ports(self) -> int:
        """The total ports the lot spans (sum of the rolls' n_ports); 0 if
        empty."""
        ...
    @property
    def avg_port_wt(self) -> float:
        """The average pounds per port (total_lbs / n_ports); 0 if empty."""
        ...
    def add(self, roll: GreigeRoll) -> None:
        """Add a roll to the lot; it must share the lot's sku and plant (adding
        to an empty lot establishes them)."""
        ...
    def remove(self, id: str) -> GreigeRoll:
        """Remove and return the roll with the given id."""
        ...
    def __iter__(self) -> Iterator[GreigeRoll]:
        """Iterate over the rolls in the lot."""
        ...
