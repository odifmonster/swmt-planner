from swmtplanner.support import SwmtBase, HasID, FloatRange

__all__ = ['GreigeStyle', 'load_translations', 'STYLE_MAP', 'load_styles', 'STYLES']

STYLE_MAP: dict[str, str] = ...

STYLES: dict[str, GreigeStyle] = ...

def load_translations(fpath: str) -> None: ...

def load_styles(fpath: str) -> None: ...

class GreigeStyle(SwmtBase, HasID[str], read_only=('id','load_rng','roll_rng')):
    """
    A class for representing greige styles and associated
    information.
    """
    def __init__(self, item: str, load_min: float, load_max: float,
                 roll_min: float, roll_max: float) -> None:
        """
        Initialize a new GreigeStyle object.

          item:
            The style's item number (as seen in the planning) files.
          load_min:
            The minimum lbs/port for this style.
          load_max:
            The maximum lbs/port for this style.
          roll_min:
            The minimum lbs/roll for this style.
          roll_max:
            The maximum lbs/roll for this style.
        """
        ...
    @property
    def load_rng(self) -> FloatRange:
        """The range of weights to load one port with this style."""
        ...
    @property
    def roll_rng(self) -> FloatRange:
        """The range of weights standard for a roll in this style."""
        ...