#!/usr/bin/env python

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Iterable, TYPE_CHECKING

from swmtplanner.support import HasID

if TYPE_CHECKING:
    from swmtplanner.products import Greige
    from swmtplanner.schedule.activity import Activity, Knit


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
    demand layer's `SafetyAwareView`, never stored here.

    `activities` is the machine time the job accounts for, in schedule
    order: the setup that prepared its item (re-threads, the changeover),
    its knits and doffs, and — appended later, when the *next* plan changes
    item — the `TapeOut` that took its sets off. `Idle` and `Waste` belong
    to no job. See "Job activities" in `schedule/DESIGN.md`. Since a `Job`
    is immutable, a later plan that adds to a committed job's activities
    recreates it with `with_activities` (same id) and the commit swaps the
    copies."""
    item: 'Greige'
    rolls: tuple[Roll, ...] = ()
    tgt_order: str | None = None
    activities: tuple['Activity', ...] = ()
    # init=True (with a default) so `dataclasses.replace` preserves the id.
    _count: int = field(default_factory=_JOB_ID, repr=False)

    @property
    def id(self) -> str:
        return f'JOB{self._count:08}'

    def with_activities(self, extra: Iterable['Activity']) -> 'Job':
        """This job (same id, rolls, target) with `extra` appended to its
        activities — how a later plan attaches the tape-out that ends it."""
        return replace(self, activities=self.activities + tuple(extra))

    @property
    def total_rolls(self) -> int:
        return len(self.rolls)

    @property
    def total_lbs(self) -> float:
        return sum(roll.lbs for roll in self.rolls)
