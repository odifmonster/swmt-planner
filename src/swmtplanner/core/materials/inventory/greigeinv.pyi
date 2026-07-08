from datetime import datetime

from swmtplanner.core.product.greige import Greige
from ..rawmat import GreigeRoll
from .inventory import Inventory


__all__ = ['GreigeInv', 'PLANT_PREFIXES']


PLANT_PREFIXES: dict[str, str]   # plant name -> id prefix (Fairystone -> FS, ...)


class GreigeInv(Inventory[GreigeRoll]):
    """A planner-specific Inventory[GreigeRoll]. Fixes the grouping config for
    greige rolls (grouped: size/plant/variant/yarn_merge; sorted: qty/avail_date;
    sku via a GreigeGroup) and surfaces the dye-lot operations at the inventory
    level."""
    def __init__(self) -> None: ...
    def prepare_dye_pool(self) -> None:
        """Group each style's rolls into valid dye lots (delegates to the
        GreigeGroup)."""
        ...
    def dye_lots(self, style: str) -> list[set[GreigeRoll]]:
        """The cached dye lots for style (delegates to the GreigeGroup)."""
        ...
    def has_cached_lots(self, style: str) -> bool:
        """Whether valid cached lots exist for style (delegates to the
        GreigeGroup)."""
        ...
    def transform_rolls(self) -> None:
        """Bring off-size rolls to STANDARD by combining (and, in a second pass,
        combining with up to MAX_TRIM_LBS trimmed off the larger roll), removing
        the originals and adding the results so every group stays consistent."""
        ...
    def create_roll(self, sku: str, avail_date: datetime, qty: float, plant: str,
                    greige: Greige | None) -> GreigeRoll:
        """Construct (but do not add) a GreigeRoll for a roll needed but not in
        inventory: id is `<plant prefix>NEW-<counter>`, yarn_merge is -1, and
        variant equals sku."""
        ...
