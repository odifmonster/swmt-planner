from swmtplanner.support import HasID
from swmtplanner.products import Greige
from swmtplanner.schedule import Job

class RlsItem(HasID[str]):
    """Tracks all the demand on a single item, accounting for on-hand inventory
    and safety stock targets."""
    def __init__(self, item: Greige, on_hand: float, start_week: int, weekly_use: list[float]) -> None:
        """Instantiate a RlsItem. The start_week is the first ISO calendar week of demand.
        weekly_use[i] should contain the lbs of this greige style used in start_week + i."""
        ...
    @property
    def item(self) -> Greige: ...
    @property
    def safety(self) -> float:
        """The remaining lbs needed to meet safety stock targets for this item."""
        ...
    def demand(self, week: int) -> float:
        """Get the remaining unfulfilled demand in the given ISO calendar week,
        not including safety stock replenishment."""
        ...
    def assign(self, job: Job) -> None:
        """Assigns the given job to fulfill demand on this item. Remaining demand
        and safety requirements are recalculated."""
        ...