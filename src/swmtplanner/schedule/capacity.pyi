from datetime import date, datetime
from typing import Any, Mapping

from swmtplanner.support import WorkCal

__all__ = [
    'KINDS', 'Resource', 'Period', 'Slot', 'ChangeoverCapacity',
    'CapacityView', 'capacity_from_dict', 'DEFAULT_RESOURCES',
]

KINDS: tuple[str, str]
"""`('tape_out', 'pattern_change')` — a TapeOut books one `tape_out` unit
per bar, an old machine's PatternChange one `pattern_change` unit."""


class Resource:
    units_per_period: int
    window: tuple[float, float]
    """Local clock hours `(start, end)`, `start < end`, within one day."""
    def __init__(self, units_per_period: int, window: tuple[float, float]) -> None: ...


class Period:
    """One instance of a resource's window on working day `day`."""
    kind: str
    day: date
    start: datetime
    end: datetime


Slot = tuple[str, date, int, datetime]
"""`(kind, period day, units, activity start)` — one booking a plan makes."""

DEFAULT_RESOURCES: dict[str, Resource]
"""Two tape-out bars and three pattern changes a day, 08:00–24:00."""


class ChangeoverCapacity:
    """Committed bookings per `(kind, day)` and the next-slot rule. See
    "Changeover capacity" in DESIGN.md. No resources ⇒ constrains nothing."""
    def __init__(self, workcal: WorkCal | None,
                 resources: Mapping[str, Resource] | None = ...) -> None: ...
    @property
    def resources(self) -> Mapping[str, Resource]: ...
    def limits(self, kind: str) -> Resource | None:
        """The resource rationing `kind`; None when unlimited."""
        ...
    def booked(self, kind: str, day: date) -> int: ...
    def bookings(self) -> dict[tuple[str, date], int]: ...
    def period_of(self, kind: str, t: datetime) -> Period | None:
        """The period containing `t`, or None outside every period."""
        ...
    def next_period(self, kind: str, t: datetime) -> Period:
        """The period containing `t`, else the first starting after it."""
        ...
    def next_slot(self, kind: str, units: int, not_before: datetime,
                  duration_hours: float) -> datetime:
        """Earliest start ≥ `not_before` inside a period, fitting before its
        end, with `booked + units <= units_per_period`. Unrationed kinds
        return `not_before`. Raises ValueError when `units` exceeds the
        period allowance."""
        ...
    def book(self, kind: str, day: date, units: int) -> None: ...
    def release(self, kind: str, day: date, units: int) -> None: ...
    def view(self, extra: Mapping[tuple[str, date], int]) -> CapacityView:
        """Read-only overlay of these bookings plus `extra`."""
        ...


class CapacityView(ChangeoverCapacity):
    """Bookings read through an overlay of another party's uncommitted
    plans; `book` / `release` raise."""
    def __init__(self, base: ChangeoverCapacity,
                 extra: Mapping[tuple[str, date], int]) -> None: ...


def capacity_from_dict(d: Mapping[str, Any] | None,
                       workcal: WorkCal) -> ChangeoverCapacity:
    """From the run-config's `changeover_capacity` block (`{kind:
    {"units_per_period", "window"}}` or `{kind: "default"}`); None ⇒ no
    constraint."""
    ...
