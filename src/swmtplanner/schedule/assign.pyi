from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping

from swmtplanner.products import BeamSet, BeamSetDesc
from swmtplanner.schedule.inventory import Inventory
from swmtplanner.schedule.machine import Machine

__all__ = ['Assigned', 'SetAssignment', 'assign_sets']


@dataclass(frozen=True)
class Assigned:
    """One placeholder hang and what the second pass gave it."""
    machine: str
    bar: Literal['top', 'btm']
    at: datetime
    desc: BeamSetDesc
    placeholder: BeamSet
    hung: BeamSet | None
    """The real set, or None when stock had nothing (the placeholder stays)."""
    source: str
    """`'stock'` or `'new'`."""
    plan_lbs: float
    """The placeholder's pounds — what the plan timed the runouts by."""
    set_lbs: float | None
    """The real set's pounds."""
    consumed: float
    """Pounds the plan draws from the bar before its next hang."""
    short_by: float
    """How far the real set's usable pounds fall short of `consumed`; 0 when
    it covers the plan or nothing was assigned."""


@dataclass(frozen=True)
class SetAssignment:
    hangs: tuple[Assigned, ...]
    mapping: Mapping[str, BeamSet]
    """`{placeholder id: real set}` the machines were rebound with."""
    @property
    def still_new(self) -> tuple[Assigned, ...]: ...


def assign_sets(machines: Mapping[str, Machine], inventory: Inventory,
                *, now: datetime) -> SetAssignment:
    """Give every placeholder hang across `machines`, in time order, the set
    the walk would have picked then (stock by receipt plus sets earlier
    hangs tape out again, `choose_stock` for continuity), and relabel each
    machine's schedule with the result. `inventory` is never mutated."""
    ...
