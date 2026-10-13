#!/usr/bin/env python

"""Changeover capacity — the plant-wide ration of tape-outs and pattern
changes per day. See "Changeover capacity" in DESIGN.md."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Mapping, TYPE_CHECKING

if TYPE_CHECKING:
    from swmtplanner.support import WorkCal

__all__ = [
    'KINDS', 'Resource', 'Period', 'Slot', 'ChangeoverCapacity',
    'CapacityView', 'capacity_from_dict', 'DEFAULT_RESOURCES',
]

# The rationed kinds. A `TapeOut` books `tape_out` units — one per bar, so
# a 'both' tape-out books 2; an old machine's `PatternChange` books one
# `pattern_change` unit; and a preamble that changes the machine at all (a
# tape-out, pattern change, runner change or style change) books one
# `change` unit, the plant-wide cap on changes of any kind in a day.
KINDS = ('tape_out', 'pattern_change', 'change')


@dataclass(frozen=True)
class Resource:
    """One rationed resource: how many units each period allows and the
    clock window (local hours, `start < end`, within one day) the period
    covers."""
    units_per_period: int
    window: tuple[float, float]


@dataclass(frozen=True)
class Period:
    """One instance of a resource's window: the working day `day` it falls
    on and its `[start, end)` in the planner's clock."""
    kind: str
    day: date
    start: datetime
    end: datetime


# (kind, period day, units, the rationed activity's start)
Slot = tuple[str, date, int, datetime]

# The plant's current practice: two tape-out bars and three pattern changes
# a day, both on first and second shift only, and five machines changed a
# day of any kind, counted against the whole day.
DEFAULT_RESOURCES: dict[str, Resource] = {
    'tape_out': Resource(units_per_period=2, window=(8.0, 24.0)),
    'pattern_change': Resource(units_per_period=3, window=(8.0, 24.0)),
    'change': Resource(units_per_period=5, window=(0.0, 24.0)),
}


class ChangeoverCapacity:
    """The committed bookings of each rationed resource, by period, and the
    rule for finding the next slot. A resource with no entry in `resources`
    is unlimited; an instance with no resources at all constrains nothing
    (the default for a run without a `changeover_capacity` input).

    Bookings are a plain count per `(kind, day)`. `book` / `release` are the
    committing caller's (the planner's `State.commit_move`); plans only read
    through `next_slot`."""

    def __init__(self, workcal: 'WorkCal | None',
                 resources: Mapping[str, Resource] | None = None) -> None:
        self._workcal = workcal
        self._resources: dict[str, Resource] = dict(resources or {})
        if self._resources and workcal is None:
            raise ValueError('a work calendar is required to ration changeovers')
        for kind in self._resources:
            if kind not in KINDS:
                raise ValueError(f'unknown changeover resource {kind!r}')
        self._booked: dict[tuple[str, date], int] = {}

    # ----- read side -----------------------------------------------------

    @property
    def resources(self) -> Mapping[str, Resource]:
        return self._resources

    def limits(self, kind: str) -> Resource | None:
        """The resource rationing `kind`, or None when it is unlimited."""
        return self._resources.get(kind)

    def booked(self, kind: str, day: date) -> int:
        return self._booked.get((kind, day), 0)

    def bookings(self) -> dict[tuple[str, date], int]:
        """Every `(kind, day)` with units booked, as a plain dict."""
        return {k: v for k, v in self._booked.items() if v}

    def _local(self, t: datetime) -> datetime:
        return t - self._workcal.cal_shift

    def _period_on(self, kind: str, d: date) -> Period | None:
        """`kind`'s period on calendar day `d`, or None when the plant does
        not work that day (or the window clips to nothing)."""
        r = self._resources[kind]
        wc = self._workcal
        if not wc.is_work_day(d):
            return None
        midnight = datetime(d.year, d.month, d.day)
        lo_h, hi_h = wc.work_hours
        start = midnight + timedelta(hours=max(r.window[0], lo_h))
        end = midnight + timedelta(hours=min(r.window[1], hi_h))
        if end <= start:
            return None
        return Period(kind, d, start + wc.cal_shift, end + wc.cal_shift)

    def period_of(self, kind: str, t: datetime) -> Period | None:
        """The period of `kind` containing `t`, or None when `t` is outside
        every period (third shift, a weekend, a holiday)."""
        p = self._period_on(kind, self._local(t).date())
        if p is not None and p.start <= t < p.end:
            return p
        return None

    def next_period(self, kind: str, t: datetime) -> Period:
        """The period containing `t`, else the first one that starts after
        it."""
        p = self.period_of(kind, t)
        if p is not None:
            return p
        d = self._local(t).date()
        for _ in range(400):
            p = self._period_on(kind, d)
            if p is not None and p.start > t:
                return p
            d += timedelta(days=1)
        raise RuntimeError(f'no {kind} period within 400 days of {t}')

    def next_slot(self, kind: str, units: int, not_before: datetime,
                  duration_hours: float) -> datetime:
        """The earliest start at or after `not_before` for a `kind` activity
        of `units` units lasting `duration_hours` (work hours): inside a
        period, fitting entirely before the period's end, with
        `booked + units <= units_per_period`. Unrationed kinds start at
        `not_before`."""
        r = self._resources.get(kind)
        if r is None:
            return not_before
        if units > r.units_per_period:
            raise ValueError(
                f'{units} {kind} units exceed the {r.units_per_period} a period allows')
        p = self.next_period(kind, not_before)
        for _ in range(400):
            start = max(not_before, p.start)
            end = self._workcal.offset_work_hours(start, duration_hours)
            if end <= p.end and self.booked(kind, p.day) + units <= r.units_per_period:
                return start
            p = self.next_period(kind, p.end)
        raise RuntimeError(f'no free {kind} slot within 400 periods of {not_before}')

    # ----- write side ----------------------------------------------------

    def book(self, kind: str, day: date, units: int) -> None:
        if kind not in self._resources:
            return
        self._booked[(kind, day)] = self.booked(kind, day) + units

    def release(self, kind: str, day: date, units: int) -> None:
        if kind not in self._resources:
            return
        self._booked[(kind, day)] = max(0, self.booked(kind, day) - units)

    def view(self, extra: Mapping[tuple[str, date], int]) -> 'CapacityView':
        """A read-only overlay: these bookings plus `extra` (another party's
        uncommitted plans)."""
        return CapacityView(self, extra)


class CapacityView(ChangeoverCapacity):
    """`ChangeoverCapacity` read through an overlay of extra bookings — the
    slots other staged (uncommitted) plans take. Reads see both; writes are
    refused."""

    def __init__(self, base: ChangeoverCapacity,
                 extra: Mapping[tuple[str, date], int]) -> None:
        self._workcal = base._workcal
        self._resources = base._resources
        self._base = base
        self._extra = dict(extra)
        self._booked = {}

    def booked(self, kind: str, day: date) -> int:
        return self._base.booked(kind, day) + self._extra.get((kind, day), 0)

    def bookings(self) -> dict[tuple[str, date], int]:
        out = dict(self._base.bookings())
        for k, v in self._extra.items():
            out[k] = out.get(k, 0) + v
        return {k: v for k, v in out.items() if v}

    def book(self, kind: str, day: date, units: int) -> None:
        raise TypeError('a CapacityView is read-only')

    def release(self, kind: str, day: date, units: int) -> None:
        raise TypeError('a CapacityView is read-only')


def capacity_from_dict(d: Mapping[str, Any] | None,
                       workcal: 'WorkCal') -> ChangeoverCapacity:
    """Build the ration from the run-config's `changeover_capacity` block:
    `{kind: {"units_per_period": int, "window": [start_hour, end_hour]}}`.
    A kind left out of the block is unlimited; a kind given as `"default"`
    takes `DEFAULT_RESOURCES`; `None` (no block) constrains nothing."""
    if d is None:
        return ChangeoverCapacity(workcal, {})
    resources: dict[str, Resource] = {}
    for kind, spec in d.items():
        if kind not in KINDS:
            raise ValueError(f'unknown changeover resource {kind!r}')
        if spec == 'default':
            resources[kind] = DEFAULT_RESOURCES[kind]
            continue
        window = spec.get('window', DEFAULT_RESOURCES[kind].window)
        resources[kind] = Resource(
            units_per_period=int(spec['units_per_period']),
            window=(float(window[0]), float(window[1])),
        )
    return ChangeoverCapacity(workcal, resources)
