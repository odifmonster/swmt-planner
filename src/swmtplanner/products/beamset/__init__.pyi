from swmtplanner.support import HasID

__all__ = ['BeamSet']

class BeamSet(HasID[str]):
    """Represents a beam set product."""
    def __init__(self, id: str) -> None:
        """Initialize a new beam set using its product id, which the constructor
        will use to extract product information."""
        ...
    @property
    def denier(self) -> int: ...
    @property
    def ends(self) -> int:
        """Number of yarn ends on each beam."""
        ...
    @property
    def spools(self) -> int:
        """Number of beams in this set."""
        ...
    @property
    def split_lease(self) -> bool: ...
    @property
    def yarn_desc(self) -> str:
        """Additional descriptive information for the yarn."""
        ...