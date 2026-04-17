from swmtplanner.swmttypes.product import Greige
from swmtplanner.swmttypes.demand import Req

__all__ = ['Safety']

class Safety(Req):
    def __init__(self, item: Greige, rolls: int, week: int) -> None: ...