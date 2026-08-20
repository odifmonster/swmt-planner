from dataclasses import dataclass
from datetime import datetime

from swmtplanner.support import HasID


__all__ = ['Activity', 'Idle']


@dataclass(frozen=True, eq=False)
class Activity(HasID[str]):
    """The generic base for everything that sits on a machine's schedule: a
    frozen record of a single span of time. Implements HasID[str] (this class
    and every subclass are declared eq=False so HasID's id-based eq/hash
    apply)."""
    start: datetime
    end: datetime
    @property
    def id(self) -> str:
        """The unique activity id: the concrete class's name in all upper
        case followed by the 8-digit zero-padded _idx (pulled from a single
        module-level counter shared by all activity classes) — e.g.
        'DYECYCLE00000004'."""
        ...


@dataclass(frozen=True, eq=False)
class Idle(Activity):
    """A machine idling for a period of time. Adds nothing to Activity;
    generic — any machine can idle."""
    ...
