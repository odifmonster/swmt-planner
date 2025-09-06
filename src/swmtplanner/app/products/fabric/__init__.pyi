from . import color
from .color import Color

import datetime as dt
from swmtplanner.support import SwmtBase, HasID
from swmtplanner.app.products import GreigeStyle

__all__ = ['color', 'Color', 'FabricItem', 'ITEMS']

ITEMS: dict[str, FabricItem] = ...

class FabricItem(SwmtBase, HasID[str],
                 read_only=('id','master','greige','color','yld','cycle_time'),
                 priv=('jets',)):
    """
    A class representing fabric (i.e. PA finished goods) items.
    Includes information about the cycle time and the jets that
    can run this product.
    """
    def __init__(self, item: str, master: str, greige: GreigeStyle,
                 color: Color, yld: float, jets: list[str]) -> None:
        """
        Initialize a new FabricItem object.

          item:
            The finished item number of the fabric.
          master:
            The master style of the fabric.
          greige:
            The greige style used by the fabric.
          color:
            The color of the fabric.
          yld:
            The average yards yielded per pound used.
          jets:
            The ids of the jets that can run this item.
        """
        ...
    @property
    def master(self) -> str:
        """The master style of this fabric item."""
        ...
    @property
    def greige(self) -> GreigeStyle:
        """The greige style used by this fabric item."""
        ...
    @property
    def color(self) -> Color:
        """The color of this fabric item."""
        ...
    @property
    def yld(self) -> float:
        """The average yards yielded per pound of greige consumed."""
        ...
    @property
    def cycle_time(self) -> dt.timedelta:
        """The cycle time for this fabric item."""
        ...
    def can_run_on_jet(self, jet_id: str) -> bool:
        """Returns True iff this item can run on the jet with the given id."""
        ...