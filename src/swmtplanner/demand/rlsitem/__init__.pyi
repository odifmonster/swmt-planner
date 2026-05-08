from datetime import datetime

from swmtplanner.support import HasID
from swmtplanner.products import Greige
from swmtplanner.schedule import Job
from swmtplanner.demand import order

class RlsItem(HasID[str]):
    """Tracks all the demand on a single item, accounting for on-hand inventory
    and safety stock targets."""
    def __init__(self, item: Greige, on_hand: float, weekly_use: list[float], start_day: int):
        """
        Initialize a new RlsItem

        Args:
            item: the greige item whose demand is being tracked
            on_hand: the initial inventory on hand (in lbs)
            weekly_use: the total lbs needed each week
            start_day: the monday of the first week as an ordinal
        """
        ...
    @property
    def item(self) -> Greige: ...
    @property
    def orders(self) -> tuple[order.Order, ...]: ...
    @property
    def safety(self) -> float:
        """The remaining lbs needed to return inventory levels back to safety stock targets."""
        ...
    def assign(self, job: Job) -> None: ...
    def demand(self, year: int, week: int, by: datetime | None = None) -> order.DemandQty:
        """Get the remaining demand for the given week. Optionally provide a bound
        for the jobs to include when calculating effective on-hand inventory."""
        ...