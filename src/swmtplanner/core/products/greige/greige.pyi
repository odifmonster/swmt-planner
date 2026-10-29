from dataclasses import dataclass, InitVar

from ....support import HasID
from .beamconfig import BeamConfig

@dataclass(frozen=True, eq=False)
class Greige(HasID[str]):
    """
    An immutable greige style. A ``Greige`` stands for every database
    variant of a style; its ``id`` is the master style name.

    Equality and hashing are by ``id``.
    """

    id: str
    """The master style name, drawn from the master style map."""
    gauge: int
    """Machine gauge, in needles per inch."""
    width: int
    """Width, in inches."""
    rack_wt: float
    """Weight in pounds per 100 racks."""
    std_wt: float
    """Standard weight of one roll of this style, in pounds."""
    beam_cfgs: tuple[BeamConfig, ...]
    """One ``BeamConfig`` per bar group, in bar order."""
    rates: InitVar[dict[str, float]]
    """
    Init-only: a map of machine id to this style's rate on that machine,
    in pounds per hour at 100% running efficiency. Actual output is lower
    because machines stop for defects and errors, and planners must not
    assume full efficiency. Stored privately and reached only through
    ``can_run_on_machine`` and ``get_rate_on_machine``.
    """

    @property
    def pattern(self) -> list[tuple[str, ...]]:
        """
        One entry per ``BeamConfig``, in order: the tuple of ``stitch``
        strings of its bars. Two styles share pattern wheels when their
        ``pattern`` values are equal, or equal after reversing the order of
        the groups (the order of stitches within a group is not reversed).
        """
        ...

    @property
    def beamsets(self) -> list[tuple[str, tuple[int, ...]]]:
        """
        One entry per ``BeamConfig``, in order: its ``beamset.id`` and the
        tuple of its bars' ``num``s. Two styles share yarn when their
        ``beamsets`` values are equal.
        """
        ...

    def can_run_on_machine(self, mchn: str) -> bool:
        """Whether this style can be knit on the machine with id ``mchn``."""
        ...

    def get_rate_on_machine(self, mchn: str) -> float:
        """
        The rate for this style on machine ``mchn``, in pounds per hour at
        100% running efficiency.

        :raises KeyError: if the style cannot run on that machine.
        """
        ...
