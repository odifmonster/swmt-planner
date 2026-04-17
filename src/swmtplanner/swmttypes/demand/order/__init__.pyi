from swmtplanner.swmttypes.product import Greige
from swmtplanner.swmttypes.demand import Req

from datetime import datetime

__all__ = ['Order']

class Order(Req):
    def __init__(self, item: Greige, rolls: int, date: datetime) -> None: ...
    @property
    def date(self) -> datetime: ...