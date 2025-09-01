from . import translate

from swmtplanner.support import SwmtBase, HasID, FloatRange

__all__ = ['translate', 'GreigeStyle', 'init', 'get_style']

def init() -> None:
    """
    Initialize the greige submodule. Do not use any methods in
    this submodule before running the initializer.
    """
    ...

def get_style(name: str) -> GreigeStyle | None:
    """
    Gets a GreigeStyle object by the item name. Returns None if
    no item with the provided name was loaded in from the data
    file.
    """
    ...

class GreigeStyle(SwmtBase, HasID[str], read_only=('id','load_rng','roll_rng')):
    """
    A class for GreigeStyle objects. Stores information about
    the target size per roll and pounds per port.
    """
    def __init__(self, name: str, load_tgt: float) -> None:
        """
        Initialize a new GreigeStyle object.

          name:
            The item name/number (as it appears in the demand
            planning file).
          load_tgt:
            The target pounds to load in a single port.
        """
        ...
    @property
    def load_rng(self) -> FloatRange:
        """The range of weights to load in one port for this style."""
        ...
    @property
    def roll_rng(self) -> FloatRange:
        """The range for standard rolls in this style."""
        ...