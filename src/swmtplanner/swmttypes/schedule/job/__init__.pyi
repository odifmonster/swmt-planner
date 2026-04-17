from datetime import datetime

from swmtplanner.support import HasID
from swmtplanner.swmttypes.product import Greige

__all__ = ['Job']

_RunOut = tuple[str, datetime]

class Job(HasID[str]):
    def __init__(self, item: Greige, start: datetime, end: datetime,
                 lbs_used_top: float, lbs_used_btm: float, lbs_prod: float,
                 run_outs: tuple[_RunOut, ...]) -> None: ...
    @property
    def item(self) -> Greige: ...
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
    def run_outs(self) -> tuple[_RunOut, ...]: ...