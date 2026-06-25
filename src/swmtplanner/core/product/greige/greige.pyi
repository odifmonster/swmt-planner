from dataclasses import dataclass

from swmtplanner.support import HasID


__all__ = ['BeamConfig', 'Greige']


@dataclass(frozen=True)
class BeamConfig:
    """The beam set mounted on one bar (top or bottom) of the knitting
    machine."""
    beamset: str   # product SKU string of the beam set on this bar
    pct: float     # percent of the bar used per pound of knitted greige


class Greige(HasID[str]):
    """A greige (knitted, undyed) fabric style. Keyed by its id."""
    def __init__(self, id: str, tgt_wt: float, safety: float, pattern: str,
                 top: BeamConfig, bottom: BeamConfig,
                 alt_names: list[str]) -> None: ...
    @property
    def id(self) -> str:
        """The style's unique identifier."""
        ...
    @property
    def tgt_wt(self) -> float:
        """The expected weight, in pounds, of every roll of this greige
        style."""
        ...
    @property
    def safety(self) -> float:
        """The target safety stock level, in pounds."""
        ...
    @property
    def pattern(self) -> str:
        """A one-letter code representing the style's pattern family."""
        ...
    @property
    def top(self) -> BeamConfig:
        """The BeamConfig for the top bar."""
        ...
    @property
    def bottom(self) -> BeamConfig:
        """The BeamConfig for the bottom bar."""
        ...
    @property
    def alt_names(self) -> tuple[str, ...]:
        """The alternate (product-BOM) greige style names that condense into
        this knitting-plant style."""
        ...
