from dataclasses import dataclass

from ....support import HasID
from .yarn import Yarn

@dataclass(frozen=True, eq=False)
class BeamSetDesc(HasID[str]):
    """
    An immutable description of a beam set: the master yarn it is warped
    from, the number of beams, and the ends per beam.

    Equality and hashing are by ``id``.
    """

    yarn: Yarn
    """The master yarn the beam set is warped from."""
    beam_count: int
    """The number of beams in the set."""
    end_count: int
    """The number of ends per beam."""

    @property
    def id(self) -> str:
        """``<yarn id>-<end count>-<beam count>``."""
        ...

    def split(self, n: int) -> list[BeamSetDesc]:
        """
        Return ``n`` new descriptions identical to this one except that
        ``end_count`` is divided evenly by ``n``. For ``n == 1`` the result
        is a single-element list.

        :raises ValueError: if ``n < 1`` or ``end_count`` is not divisible
            by ``n``.
        """
        ...

    @classmethod
    def merge(cls, *bsets: BeamSetDesc) -> BeamSetDesc:
        """
        Combine the given descriptions into a single one by summing their
        ``end_count``s. Inverse of ``split``.

        :raises ValueError: if called with no arguments, or if the
            descriptions are not all identical (do not share an ``id``).
        """
        ...
