#!/usr/bin/env python

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from swmtplanner.support import HasID

if TYPE_CHECKING:
    from swmtplanner.products import Greige


def _make_id_counter():
    ctr = 0
    def _next():
        nonlocal ctr
        ctr += 1
        return ctr
    return _next


_JOB_ID = _make_id_counter()


@dataclass(frozen=True)
class Roll:
    """One completed roll coming off the machine. Pure data — no
    machine-state effect and no id of its own. The demand layer reads a
    `Job`'s rolls to learn when each roll lands and how heavy it is."""
    lbs: float
    completion_time: datetime       # when the roll is ready to ship


@dataclass(frozen=True)
class Job(HasID[str]):
    """An "order" for some number of rolls of an item on a machine,
    fulfilled by one call to `plan_production`. Records the rolls the
    call produced (each with its own completion time) and the item
    being knit. Pure data — no start/end of its own and no effect on
    machine `Status`. Lives on the production schedule (`Machine.jobs`),
    not the activity schedule.

    A single `Job` can span multiple `BeamLoad`s: every roll completed
    across the beam-swap sequence lands on the same `Job`. (Distinct
    from a `Knit` activity, which is one uninterrupted run.)"""
    item: 'Greige'
    rolls: tuple[Roll, ...] = ()
    _count: int = field(default_factory=_JOB_ID, init=False)

    @property
    def id(self) -> str:
        return f'JOB{self._count:05}'

    @property
    def total_rolls(self) -> int:
        return len(self.rolls)

    @property
    def total_lbs(self) -> float:
        return sum(roll.lbs for roll in self.rolls)
