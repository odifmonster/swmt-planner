from swmtplanner.support import HasID, WorkCal
from swmtplanner.swmttypes.product import Greige, BeamSet
from swmtplanner.swmttypes.schedule import Job

from typing import Literal, NamedTuple
from datetime import datetime

__all__ = ['Decision', 'Machine']

_DecisionKind = Literal['JOB_END', 'TOP_RUNOUT', 'BTM_RUNOUT']
_StopKind = Literal['TOP_BEAM_CHANGE', 'BTM_BEAM_CHANGE', 'TOP_TAPE_OUT', 'BTM_TAPE_OUT',
                    'STYLE_CHANGE', 'FAMILY_CHANGE']

class Decision(NamedTuple):
    mchn_id: str
    kind: _DecisionKind
    date: datetime

class Stop(NamedTuple):
    mchn_id: str
    reason: _StopKind
    start: datetime
    end: datetime

class Machine(HasID[str]):
    def __init__(self, name: str, cal: WorkCal, item: Greige, top_rem: float,
                 btm_rem: float) -> None: ...
    @property
    def is_old(self) -> bool: ...
    @property
    def cal(self) -> WorkCal: ...
    @property
    def last_item(self) -> Greige: ...
    @property
    def top_set(self) -> BeamSet: ...
    @property
    def btm_set(self) -> BeamSet: ...
    @property
    def jobs(self) -> tuple[Job, ...]: ...