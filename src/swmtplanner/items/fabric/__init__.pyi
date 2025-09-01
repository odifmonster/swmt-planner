from . import color
from .color import Color

from swmtplanner.support import SwmtBase, HasID
from swmtplanner.items import GreigeStyle

__all__ = ['color', 'Color', 'fabric', 'FabricStyle', 'init', 'get_style']

def init() -> None:
    """
    Initialize the fabric submodule. Do not use any methods in
    this submodule before running the initializer.
    """
    ...

def get_style(name: str) -> FabricStyle | None:
    """
    Gets a FabricStyle object by the item name. Returns None if
    no item with the provided name was loaded in from the data
    file.
    """
    ...

class FabricStyle(SwmtBase, HasID[str],
                  read_only=('id','master','greige','color','yld'),
                  priv=('jets',)):
    """
    A class for FabricStyle objects. Stores information about
    the master style, greige style, color, and yield.
    """
    def __init__(self, name: str, master: str, greige: GreigeStyle,
                 color: Color, yld: float, jets: list[str]) -> None:
        """
        Initialize a new FabricStyle object.

          name:
            The finished fabric item number.
          master:
            
        """
        ...
    @property
    def master(self) -> str:
        """This fabric item's master style."""
        ...
    @property
    def greige(self) -> GreigeStyle: ...
    @property
    def color(self) -> Color: ...
    @property
    def shade(self) -> color.Shade: ...
    @property
    def yld(self) -> float:
        """The average yard yielded per pound of greige consumed for this item."""
        ...
    def can_run_on_jet(self, jet_id: str) -> bool:
        """Returns True iff this item can run on the jet with the given id."""
        ...