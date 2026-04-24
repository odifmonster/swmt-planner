from typing import Protocol, NamedTuple
from datetime import datetime

from swmtplanner.swmttypes.product import Greige
from swmtplanner.swmttypes.schedule import Job

__all__ = ['Req', 'Production']

class _InvTracker(Protocol):
    item: Greige
    safety_lbs: float
    safety_rolls: int
    def net_position_by(self, date: datetime) -> float: ...

class Production(NamedTuple):
    job: Job
    rolls: int

class Req:
    def __init_subclass__(cls, read_only: tuple[str, ...] = ...,
                          priv: tuple[str, ...] = ...) -> None:
        ...
    def __init__(self, item: Greige, rolls: int, year: int, week: int, prty: int,
                 tracker: _InvTracker, **kwargs) -> None: ...
    @property
    def item(self) -> Greige: ...
    @property
    def rolls(self) -> int: ...
    @property
    def lbs(self) -> float: ...
    @property
    def year(self) -> int: ...
    @property
    def week(self) -> int: ...
    @property
    def prty(self) -> int: ...
    def add_production(self, prod: Production) -> None: ...
    def remaining_rolls(self, by: datetime | None = None) -> int:
        """
        Returns the number of rolls still needed to fulfill this requirement.

        Args:
            by: If provided, only counts production that finished by this
                datetime. If None, counts all production regardless of timing.
        """
        ...