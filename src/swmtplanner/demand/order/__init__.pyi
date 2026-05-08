from typing import NamedTuple
from datetime import datetime

from swmtplanner.support import Observer, HasID
from swmtplanner.products import Greige
from swmtplanner.schedule import Job

__all__ = ['Order']

class DemandQty(NamedTuple):
    cumulative: float
    regular: float
    safety: float
    excess: float

class Order(HasID[str], Observer[Job]):
    """Class for tracking order fulfillment."""
    def __init__(self, item: Greige, due_date: datetime, priority: int,
                 cur_lbs: float, prev_lbs: float, prev_due: datetime,
                 safety: float, excess: float) -> None:
        """
        Initialize a new Order object.

        Args:
            item: the greige style of this order
            due_date: the due date for this order
            priority: how many weeks after the start week this order is due
            cur_lbs: the number of lbs ordered
            prev_lbs: the cumulative lbs of all previous orders
            prev_due: the due date of the last order before this one
            safety: the remaining safety replenishment needed (after netting out inventory)
            excess: usually 0, unless current inventory levels exceed cumulative demand and safety stock targets
        """
        ...
    @property
    def item(self) -> Greige: ...
    @property
    def due_date(self) -> datetime: ...
    def remaining(self, by: datetime | None = None) -> DemandQty:
        """Get the remaining unfulfilled demand. Optionally provide a date boundary to
        only include jobs ending before or on that date."""
        ...