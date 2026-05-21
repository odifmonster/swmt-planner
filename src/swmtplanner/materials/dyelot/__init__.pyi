from dataclasses import dataclass
from datetime import date

from ..product import Fabric
from ..rawmat import GreigeRoll


__all__ = ['DyeLot']


@dataclass(frozen=True)
class DyeLot:
    """A grouping of compatible greige rolls assigned to produce a specific Fabric item.

    Frozen record: lots are constructed by the module-level factory
    functions (`get_dye_lot`, `get_dye_lots`) and are not modified
    afterward. The class itself performs no validation; the dye-cycle
    matching constraints are enforced by the factories.
    """
    fabric: Fabric
    rolls: tuple[GreigeRoll, ...]

    @property
    def avail_date(self) -> date | None:
        """Earliest date at which every roll in the lot is available.

        Equal to the latest non-`None` `avail_date` among `rolls`, with
        `None` (already in inventory) treated as immediately available.
        Returns `None` if every roll has `avail_date is None` (or if the
        lot has no rolls).
        """
        ...
