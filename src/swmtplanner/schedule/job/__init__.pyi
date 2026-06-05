from dataclasses import dataclass
from datetime import datetime

from swmtplanner.support import HasID
from swmtplanner.products import Greige

__all__ = ['Roll', 'Job']


@dataclass(frozen=True)
class Roll:
    lbs: float
    completion_time: datetime


@dataclass(frozen=True)
class Job(HasID[str]):
    item: Greige
    rolls: tuple[Roll, ...] = ...

    @property
    def id(self) -> str: ...
    @property
    def total_rolls(self) -> int: ...
    @property
    def total_lbs(self) -> float: ...
