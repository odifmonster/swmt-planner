from dataclasses import dataclass

from swmtplanner.support import HasID


__all__ = [
    'EXTRA_LIGHT', 'LIGHT', 'MEDIUM', 'BLACK', 'SD_BLACK',
    'Color', 'Fabric',
]


# shade ratings (ordered lightest -> darkest)
EXTRA_LIGHT: int
LIGHT: int
MEDIUM: int
BLACK: int
SD_BLACK: int


@dataclass(frozen=True)
class Color:
    """A finished-fabric color."""
    name: str
    number: int
    shade_rating: int
    def get_needed_strip(self, jet_state):
        """Not yet implemented; will accept a JetState once the Jet class is
        designed."""
        ...


class Fabric(HasID[str]):
    """A finished fabric product. Keyed by its id."""
    def __init__(self, id: str, ply1_parts: tuple[str, ...], greige: str,
                 style: str, width: float, oz_sq_yd: float, yld_pct: float,
                 name: str, number: int, shade_rating: int,
                 jets: list[str]) -> None:
        """Build a Fabric. yds_per_lb is computed as
        36 * 16 / (oz_sq_yd * width) * yld_pct (width in inches); the color is
        built from name/number/shade_rating; jets is the list of jet IDs the
        product can run on."""
        ...
    @property
    def id(self) -> str:
        """The product's unique identifier."""
        ...
    @property
    def ply1_parts(self) -> tuple[str, ...]:
        """The ply1 part numbers associated with this fabric."""
        ...
    @property
    def greige(self) -> str:
        """The greige style string."""
        ...
    @property
    def style(self) -> str:
        """The style string."""
        ...
    @property
    def width(self) -> float:
        """The fabric width, in inches."""
        ...
    @property
    def color(self) -> Color:
        """The Color this fabric is dyed to."""
        ...
    @property
    def yds_per_lb(self) -> float:
        """The yards per pound."""
        ...
    def can_run_on_jet(self, jet: str) -> bool:
        """Whether the product can run on the given jet ID."""
        ...
