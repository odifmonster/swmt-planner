from datetime import datetime
from typing import Literal

from swmtplanner.support import HasID

_Beam = str
_Bar = tuple[_Beam, float]

__all__ = ['Greige', 'BeamSet']

class Greige(HasID[str]):
    def __init__(self, name: str, family: str, beam_config: tuple[_Bar, _Bar],
                 tgt_wt: float, machines: dict[str, float]) -> None: ...
    @property
    def family(self) -> str:
        """The style family of this greige item."""
        ...
    @property
    def top_set(self) -> str:
        """The beamset used on the top bar to produce this greige item."""
        ...
    @property
    def btm_set(self) -> str:
        """The beamset used on the bottom bar to produce this greige item."""
        ...
    @property
    def top_pct(self) -> float:
        """The percent of the top beamset consumed by weight."""
        ...
    @property
    def btm_pct(self) -> float:
        """The percent of the bottom beamset consumed by weight."""
        ...
    @property
    def tgt_wt(self) -> float:
        """The target lbs/roll of greige fabric."""
        ...
    def can_run_on(self, mchn: str) -> bool:
        """Whether this greige style can be produced on the given machine."""
        ...
    def get_rate_on(self, mchn: str) -> float:
        """The rate of production on the given machine in lbs/hour."""
        ...

class BeamSet(HasID[int]):
    def __init__(self, name: str, init_lbs: float) -> None: ...
    @property
    def name(self) -> str:
        """A description of this beamset."""
        ...
    @property
    def denier(self) -> int: ...
    @property
    def lbs(self) -> float:
        """How many lbs remain on this beamset after the schedule has finished running."""
        ...
    def rem_lbs_by(self, date: datetime) -> float:
        """Returns the lbs remaining on this beamset by the given date."""
        ...
    def use(self, item: Greige, mchn: str, bar: Literal['top', 'btm'],
            start: datetime, end: datetime) -> None:
        """
        Log a usage of this beamset.

        Args:
          item: The Greige item being produced.
          mchn: The name of the machine the beamset is assigned to.
          bar: Which bar the beamset is on ('top' or 'btm').
          start: The start date/time of the job.
          end: The end date/time of the job.
        """
        ...