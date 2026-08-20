from dataclasses import dataclass

from swmtplanner.core.product.fabric import Color
from swmtplanner.core.materials import DyeLot
from .activity import Activity


__all__ = ['STRIP_CYCLE_HRS', 'cycle_time_for_color',
           'DyeCycle', 'EmptyCycle', 'StripCycle']


STRIP_CYCLE_HRS: float
"""The length of a strip cycle, in hours."""


def cycle_time_for_color(color: Color) -> float:
    """The cycle time, in hours, of dyeing the given Color, determined by its
    shade_rating: 10 for BLACK, 6 for SD_BLACK, 8 for all other shades."""
    ...


@dataclass(frozen=True, eq=False)
class DyeCycle(Activity):
    """One productive dye run: the DyeLots dyed together in a single cycle on
    a jet. All three computed properties must be well defined: construction
    raises ValueError when any cannot be derived (no lots, or a lot with no
    rolls / no assigned fabric) or when the lots don't share a value for all
    three."""
    lots: tuple[DyeLot, ...]
    @property
    def greige(self) -> str:
        """The shared greige style string of the lots."""
        ...
    @property
    def style(self) -> str:
        """The shared style string of the lots' assigned Fabrics."""
        ...
    @property
    def color(self) -> Color:
        """The shared Color of the lots' assigned Fabrics."""
        ...


@dataclass(frozen=True, eq=False)
class EmptyCycle(Activity):
    """One empty light cycle — the EMPTY preparation activity
    Color.get_needed_strip calls for before an EXTRA_LIGHT color: a light
    cycle run with no lots in the jet."""
    color: Color


@dataclass(frozen=True, eq=False)
class StripCycle(Activity):
    """One strip (cleaning) cycle — the STRIP preparation activity
    Color.get_needed_strip returns. Adds nothing to Activity; its length is
    STRIP_CYCLE_HRS."""
    ...
