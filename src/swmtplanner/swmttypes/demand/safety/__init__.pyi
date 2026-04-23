from typing import Protocol
from datetime import datetime

from swmtplanner.swmttypes.product import Greige
from swmtplanner.swmttypes.demand import Req

__all__ = ['Safety']

class _InvTracker(Protocol):
    item: Greige
    safety_lbs: float
    safety_rolls: int
    def net_position_by(self, date: datetime) -> float: ...

class Safety(Req):
    def __init__(self, item: Greige, rolls: int, year: int, week: int, tracker: _InvTracker) -> None: ...