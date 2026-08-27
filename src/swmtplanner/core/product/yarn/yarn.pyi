from swmtplanner.support import HasID


__all__ = ['LUSTER_CODES', 'MATERIAL_CODES', 'ATTR_CODES', 'Yarn']


LUSTER_CODES: dict[str, str]
"""Maps a luster's long form to the code used in a Yarn id. Luster and
pre-knitting colour are one and the same for now; every yarn currently knitted
is semi-dull, and the only other luster in use (bright) comes in white only."""

MATERIAL_CODES: dict[str, str]
"""Maps a material's long form to the code used in a Yarn id."""

ATTR_CODES: dict[str, str]
"""Maps a yarn attribute's long form to the code used in a Yarn id."""


class Yarn(HasID[str]):
    """A single yarn. Keyed by its id, which is built from the other
    properties."""
    def __init__(self, denier: int, fill_ct: int, luster: str, material: str,
                 attributes: list[str]) -> None:
        """Build a yarn from its long-form components. Raises ValueError if the
        luster, the material, or any attribute is not a key of its code map."""
        ...
    @property
    def id(self) -> str:
        """The yarn's unique identifier, of the form
        `<denier>D<fill_ct>F-<luster>-<material>[-<attrs>]` (e.g.
        `'50D34F-SDL-POL-REP-TX'`). The attribute segment and its leading dash
        are omitted when the yarn has no attributes."""
        ...
    @property
    def denier(self) -> int:
        """The yarn's denier as the vendor names it, not a measured value."""
        ...
    @property
    def fill_ct(self) -> int:
        """The yarn's filament count."""
        ...
    @property
    def luster(self) -> str:
        """The yarn's luster in long form, carrying its colour when the yarn is
        dyed before knitting (e.g. 'Semi-Dull', 'Solution Dyed Black')."""
        ...
    @property
    def material(self) -> str:
        """The yarn's material in long form (e.g. 'Polyester')."""
        ...
    @property
    def attributes(self) -> tuple[str, ...]:
        """The yarn's remaining attributes in long form, sorted so that the id
        does not depend on the order they were supplied in."""
        ...
