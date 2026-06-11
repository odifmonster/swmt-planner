#!/usr/bin/env python

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from swmtplanner.support import HasID

if TYPE_CHECKING:
    from swmtplanner.products import Greige
    from swmtplanner.schedule.activity import Knit


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
    `Job`'s rolls to learn when each roll lands and how heavy it is.

    `knits` is provenance: the `Knit` activities that wound this roll —
    one for a roll knit on a single beam, two when the roll straddles a
    beam swap (wound partly before, partly after the re-thread)."""
    lbs: float
    completion_time: datetime       # when the roll is ready to ship
    knits: tuple['Knit', ...] = ()  # the Knit(s) that wound this roll


@dataclass(frozen=True)
class Job(HasID[str]):
    """An "order" for some number of rolls of an item on a machine,
    fulfilled by one call to `plan_production`. Records the rolls the
    call produced (each with its own completion time) and the item
    being knit. Pure data — no start/end of its own and no effect on
    machine `Status`. Lives on the production schedule (`Machine.jobs`),
    not the activity schedule.

    Every roll completed across a beam-swap sequence lands on the same
    `Job`. (Distinct from a `Knit` activity, which is one uninterrupted
    run; a `Job`'s knits are the union of its rolls' knits.)

    `tgt_order` is provenance: the id of the order this `Job` was
    *created to target* (passed into `plan_production`), or `None` for a
    `Job` not raised against any particular order (e.g. a `'next_runout'`
    run-up `Job`). It is the caller's intent at planning time, *not* the
    order the `Job` actually fills — that is resolved by priority in the
    demand layer's `SafetyAwareView`, never stored here."""
    item: 'Greige'
    rolls: tuple[Roll, ...] = ()
    tgt_order: str | None = None
    _count: int = field(default_factory=_JOB_ID, init=False)

    @property
    def id(self) -> str:
        return f'JOB{self._count:08}'

    @property
    def total_rolls(self) -> int:
        return len(self.rolls)

    @property
    def total_lbs(self) -> float:
        return sum(roll.lbs for roll in self.rolls)
