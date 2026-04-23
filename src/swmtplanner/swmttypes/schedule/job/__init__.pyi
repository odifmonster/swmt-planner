from datetime import datetime
from typing import Literal

from swmtplanner.support import HasID
from swmtplanner.swmttypes.product import Greige
from swmtplanner.swmttypes.demand import Req

__all__ = ['Job']

_RunOut = tuple[str, datetime]
_Change = tuple[Literal['top_to', 'btm_to', 'top_chg', 'btm_chg'], str, datetime]

class Job(HasID[str]):
    def __init__(self, item: Greige, req: Req, start: datetime, end: datetime,
                 lbs_used_top: float, lbs_used_btm: float, lbs_prod: float,
                 changes: list[_Change], run_outs: list[_RunOut]) -> None: ...
    @property
    def item(self) -> Greige: ...
    @property
    def req(self) -> Req: ...
    @property
    def start(self) -> datetime: ...
    @property
    def end(self) -> datetime: ...
    @property
    def lbs_used_top(self) -> float: ...
    @property
    def lbs_used_btm(self) -> float: ...
    @property
    def lbs_prod(self) -> float: ...
    @property
    def changes(self) -> tuple[_Change, ...]: ...
    @property
    def run_outs(self) -> tuple[_RunOut, ...]: ...