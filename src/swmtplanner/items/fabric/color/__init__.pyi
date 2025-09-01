from typing import NewType, Literal
from swmtplanner.support import SwmtBase, HasID

__all__ = ['Shade', 'EMPTY', 'HEAVYSTRIP', 'STRIP', 'LIGHT', 'MEDIUM',
           'BLACK', 'Color', 'init', 'get_color']

Shade = NewType('Shade', str)
EMPTY: Shade = ...
HEAVYSTRIP: Shade = ...
STRIP: Shade = ...
SOLUTION: Shade = ...
LIGHT: Shade = ...
MEDIUM: Shade = ...
BLACK: Shade = ...

type _ShadeInt = Literal[1, 2, 3, 4, 5, 6, 7]
type _ShadeStr = Literal['EMPTY', 'HEAVYSTRIP', 'STRIP', 'LIGHT', 'MEDIUM',
                         'BLACK']

def init() -> None:
    """
    Initialize the color submodule. Do not use any methods in
    this submodule before running the initializer.
    """
    ...

def get_color(number: str) -> Color | None:
    """
    Gets a Color object by its number (as a 5-digit string).
    Returns None if no color with the provided number was loaded
    in from the data file.
    """
    ...

class Color(SwmtBase, HasID[str], read_only=('id','name','shade','soil')):
    """
    A class for Color objects. Stores information about name and
    number, as well as the amount of "soil" this color adds to a
    jet and maximum "soil level" a jet can be and still run this
    color.
    """
    def __init__(self, number: int, name: str,
                 shadeval: _ShadeInt | _ShadeStr) -> None:
        """
        Initialize a new Color object.

          number:
            Dye formula as an int.
          name:
            The english name of this color.
          shadeval:
            A number or string representing this color's shade. The
            numbers 5-7 are for non-item colors (i.e. strips and
            unknowns).
        """
        ...
    @property
    def name(self) -> str: ...
    @property
    def shade(self) -> Shade: ...
    @property
    def soil(self) -> int:
        """How "soiled" this color makes a jet after running."""
        ...
    def get_strip(self, soil: int) -> Shade | None:
        """
        Gets the strip needed before running this color on a jet
        with the given soil level. Returns None if no strip is
        needed.
        """
        ...