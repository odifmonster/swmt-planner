from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from swmtplanner.support import HasID
from swmtplanner.products import Greige
from swmtplanner.schedule.activity import Activity, Knit

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
    activities: tuple[Activity, ...] = ...
    """The machine time the job accounts for, in schedule order: its item's
    setup (re-threads, changeover), its knits and doffs, and the tape-out
    that later takes its sets off. Idle and Waste belong to no job."""
    prior_job: str | None = ...
    """The previous plan's job this one was committed to honour, else None."""
    fill: bool = ...
    """True when the job knit rolls of the current item while the machine
    waited for a changeover-ration slot ("Filling a slot wait")."""

    @property
    def id(self) -> str: ...
    @property
    def total_rolls(self) -> int: ...
    @property
    def total_lbs(self) -> float: ...
    def with_activities(self, extra: Iterable[Activity]) -> Job:
        """This job (same id) with `extra` appended to `activities`."""
        ...
