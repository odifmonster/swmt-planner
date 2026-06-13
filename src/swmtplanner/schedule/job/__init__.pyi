from dataclasses import dataclass
from datetime import datetime

from swmtplanner.support import HasID
from swmtplanner.products import Greige
from swmtplanner.schedule.activity import Knit

__all__ = ['Roll', 'Job']


@dataclass(frozen=True)
class Roll:
    lbs: float
    completion_time: datetime
    knits: tuple[Knit, ...] = ...


@dataclass(frozen=True)
class Job(HasID[str]):
    item: Greige
    rolls: tuple[Roll, ...] = ...
    tgt_order: str | None = ...

    @property
    def id(self) -> str: ...
    @property
    def total_rolls(self) -> int: ...
    @property
    def total_lbs(self) -> float: ...
