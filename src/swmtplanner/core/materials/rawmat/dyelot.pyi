from datetime import datetime
from collections.abc import Iterator

from .greigeroll import GreigeRoll
from ...product.fabric import Fabric


__all__ = ['DyeLot']


class DyeLot:
    """A lot of greige rolls (all sharing a greige style and a plant) assigned to
    produce a specific finished Fabric; tracks the group's aggregate qualities."""
    def __init__(self, rolls: list[GreigeRoll]) -> None:
        """Build a dye lot from a (possibly empty) list of rolls; raises
        ValueError unless they all share a greige and a plant."""
        ...
    @property
    def greige(self) -> str | None:
        """The shared greige style of the component rolls (their sku); None if the
        lot is empty."""
        ...
    @property
    def plant(self) -> str | None:
        """The shared plant of the component rolls; None if the lot is empty."""
        ...
    @property
    def fabric(self) -> Fabric | None:
        """The Fabric these rolls are assigned to produce (initially None)."""
        ...
    @fabric.setter
    def fabric(self, fabric: Fabric | None) -> None:
        """Assign the fabric to produce. Raises ValueError if the fabric does not
        use the lot's current greige (fabric.greige != greige), or RuntimeError
        if the lot is frozen."""
        ...
    @property
    def avail_date(self) -> datetime | None:
        """The maximum avail_date among the component rolls; None if empty."""
        ...
    @property
    def total_lbs(self) -> float:
        """The total pounds across the rolls (sum of qty); 0 if empty."""
        ...
    @property
    def total_yds(self) -> float | None:
        """Expected yield in yards: None when fabric is None, else
        total_lbs * fabric.yds_per_lb."""
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
    def freeze(self) -> None:
        """Freeze the lot: once frozen, add, remove, and setting fabric raise
        RuntimeError. There is no unfreeze."""
        ...
    def add(self, roll: GreigeRoll) -> None:
        """Add a roll; it must share the lot's greige and plant (adding to an
        empty lot establishes them). If a fabric is assigned, the roll's greige
        must match fabric.greige, else ValueError. Raises RuntimeError if the
        lot is frozen."""
        ...
    def remove(self, id: str) -> GreigeRoll:
        """Remove and return the roll with the given id. Raises RuntimeError if
        the lot is frozen."""
        ...
    def __iter__(self) -> Iterator[GreigeRoll]:
        """Iterate over the rolls in the lot."""
        ...
