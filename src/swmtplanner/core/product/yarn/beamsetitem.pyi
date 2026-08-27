from swmtplanner.support import HasID

from .yarn import Yarn


__all__ = ['BeamSetItem']


class BeamSetItem(HasID[str]):
    """The set of beams one bar of the knitting machine draws from. Keyed by its
    id, which is built from the other properties."""
    def __init__(self, beams: int, ends: int, yarn: Yarn,
                 is_split: bool) -> None: ...
    @property
    def id(self) -> str:
        """The beam set's unique identifier, of the form
        `<yarn id> <ends>X<beams>[ S/L]` (e.g.
        `'40D24F-SDL-POL 1172X4 S/L'`). The trailing ' S/L' appears only when
        the set runs split lease."""
        ...
    @property
    def beams(self) -> int:
        """The number of beams in the set."""
        ...
    @property
    def ends(self) -> int:
        """The total number of ends across the set."""
        ...
    @property
    def yarn(self) -> Yarn:
        """The Yarn wound on the set's beams."""
        ...
    @property
    def is_split(self) -> bool:
        """Whether the set runs split lease, in which case it feeds two adjacent
        bars rather than one, each taking half the ends."""
        ...
