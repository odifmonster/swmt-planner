from swmtplanner.support import HasID, WorkCal
from swmtplanner.swmttypes.product import Greige, BeamSet
from swmtplanner.swmttypes.schedule import Job

from typing import Literal
from datetime import datetime

_TapeOut = tuple[Literal['top_to', 'btm_to', 'top_chg', 'btm_chg'], str, datetime]
_RunOut = tuple[Literal['top_ro', 'btm_ro'], datetime]

class Machine(HasID[str]):
    def __init__(self, name: str, cal: WorkCal, item: Greige, top_rem: float,
                 btm_rem: float) -> None: ...
    @property
    def cal(self) -> WorkCal: ...
    @property
    def item(self) -> Greige: ...
    @property
    def top_set(self) -> BeamSet: ...
    @property
    def btm_set(self) -> BeamSet: ...
    @property
    def jobs(self) -> list[Job]: ...
    def next_runout(self) -> _RunOut: ...
    def get_runouts(self, start: datetime, rolls: int, apply_changes: bool = False) \
        -> list[_RunOut]: ...
    def get_tapeouts(self, item: Greige) -> list[_TapeOut]:
        """
        Gets all the required beam changes and tape-outs needed to knit the
        given item next. Returns an empty list if no changes are needed. A
        tape out indicates the beam will be switched before running out.

          item:
            The next Greige item to knit.
        
        Returns a list of 3-tuples, where the first str indicates whether the
        change is a full tape out ('to') or a beam change after a run out
        ('chg') and whether it occurred on the top or bottom bar. The second
        str is a description of the new beamset product that will be loaded on,
        and the final element is the date/time the change will occur.
        """
        ...