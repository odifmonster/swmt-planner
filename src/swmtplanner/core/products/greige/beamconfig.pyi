from dataclasses import dataclass

from ..beamset import BeamSetDesc
from .barconfig import BarConfig

@dataclass(frozen=True)
class BeamConfig:
    """
    An immutable description of how one bar group of a style is beamed and
    knit: the beam set it consumes and the configuration of each guide bar
    fed from it. A group may cover one or more guide bars.

    Equality is field-wise.
    """

    beamset: BeamSetDesc
    """
    The beam set description this configuration consumes, expressed as a
    single description covering all bars in the group (the per-bar
    descriptions merged, so ``end_count`` is the group's total ends per
    beam).
    """
    bars: tuple[BarConfig, ...]
    """The configuration of each guide bar in the group."""

    def can_use(self, bsets: list[BeamSetDesc]) -> bool:
        """
        Whether beam sets matching the given descriptions can be used to
        knit this configuration. ``True`` if and only if either

        1. ``bsets`` has exactly one element equal to ``self.beamset``
           (one combined beam set split across all the bars), or
        2. ``bsets`` has the same length as ``self.bars`` and
           ``BeamSetDesc.merge(*bsets)`` equals ``self.beamset`` (one beam
           set per bar).

        In every other case, including when the descriptions are not
        identical and so cannot be merged, returns ``False``.
        """
        ...
