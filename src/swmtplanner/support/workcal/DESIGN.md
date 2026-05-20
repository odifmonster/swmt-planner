# workcal

Support module for date math on a customizable work calendar. A `WorkCal` is
configured with working weekdays, daily business hours, and a set of
holidays, so callers can perform date arithmetic that correctly skips
non-working time.

## Structures

`Holiday` — abstract base for a holiday occurring in a given month.

```python
class Holiday:
    name: str
    month: int

    def date_in_year(self, year: int) -> datetime: ...  # abstract
```

`FixedDate` — `Holiday` subclass: holiday on a fixed day of the month
(e.g., Christmas → Dec 25).

```python
class FixedDate(Holiday):
    day: int

    def date_in_year(self, year: int) -> datetime: ...
```

`FlexDate` — `Holiday` subclass: holiday on the nth weekday of the month
(e.g., Thanksgiving → 4th Thursday of November).

```python
class FlexDate(Holiday):
    weekday: int
    n: int

    def date_in_year(self, year: int) -> datetime: ...
```

`WorkCal` — the working calendar; configured at construction with workdays,
business hours, and holidays. Immutable after construction.

```python
class WorkCal:
    # configured state (read-only)
    weekdays: tuple[int, ...]
    day_start: int
    day_end: int
    holidays: tuple[Holiday, ...]
    cal_shift: int

    # computed properties
    work_days_per_week: int
    work_hours_per_day: int

    def __init__(
        self,
        weekdays: list[int],
        day_start: int,
        day_end: int,
        holidays: list[Holiday],
        cal_shift: int = 0,
    ) -> None: ...

    # operations
    def is_workday(self, d: date) -> bool: ...
    def offset_work_days(self, start: date, days: int) -> date: ...
    def offset_work_hours(self, start: datetime, hours: float) -> datetime: ...
    def get_work_hours_between(self, start: datetime, end: datetime) -> float: ...
    def avail_hours_before_weekend(self, start: datetime) -> float: ...
```

## Holiday

`Holiday` is an abstract dataclass with two fields:

- `name: str` — display name of the holiday.
- `month: int` — month (1–12) in which it occurs.

It defines one abstract method, `date_in_year(year: int) -> datetime`, that
each subclass implements to return the concrete date for that holiday in a
given year.

### FixedDate

Adds a `day: int` field. `date_in_year` returns `datetime(year, month, day)`.

### FlexDate

Adds two fields:

- `weekday: int` — target weekday, Python `date.weekday()` convention
  (Mon=0..Sun=6).
- `n: int` — which occurrence within the month. Positive values count from
  the start of the month (`n=1` is the first, `n=4` is the fourth);
  negative values count from the end (`n=-1` is the last occurrence,
  `n=-2` the second-to-last).

`date_in_year` locates the first or last occurrence of `weekday` in the
target month and offsets by the appropriate number of weeks.

## WorkCal

### Construction

`WorkCal(weekdays, day_start, day_end, holidays, cal_shift=0)`:

- `weekdays: list[int]` — working weekdays, Python `date.weekday()`
  convention (Mon=0..Sun=6).
- `day_start: int` — hour the business day begins, in `[0, 24]`, measured
  from the start of the calendar day (see _Calendar shift_ below).
- `day_end: int` — hour the business day ends, in `[0, 24]`, measured from
  the start of the calendar day. `day_end=24` denotes a business day that
  runs to the end of the calendar day (i.e., a 24-hour workday when paired
  with `day_start=0`).
- `holidays: list[Holiday]` — holidays observed by this calendar.
- `cal_shift: int` — optional integer hour offset that shifts the start of
  every calendar day away from midnight. Defaults to `0`. See
  _Calendar shift_ below.

Both list arguments are **copied** at construction so that mutations to the
caller's lists cannot affect the calendar's internal state.

### Read-only state

After construction, all configured state is exposed as read-only `tuple`s;
there are no setters. Callers cannot mutate a `WorkCal` after it is built.

- `weekdays: tuple[int, ...]`
- `day_start: int`
- `day_end: int`
- `holidays: tuple[Holiday, ...]`
- `cal_shift: int`

### Computed properties

- `work_days_per_week: int` — `len(weekdays)`.
- `work_hours_per_day: int` — `day_end - day_start`.

### Calendar shift

`cal_shift` lets the calendar's day boundary live somewhere other than
midnight. It is an integer number of hours by which the start of each
calendar day is offset from real-clock midnight:

- `cal_shift = 0` (the default) — calendar day boundaries coincide with
  midnight.
- `cal_shift < 0` — each calendar day starts *before* midnight, in the
  previous real-clock day's evening.
- `cal_shift > 0` — each calendar day starts *after* midnight, in the
  real-clock morning.

Concretely, the calendar day to which a real datetime `dt` belongs is

```
calendar_date(dt) = (dt - timedelta(hours=cal_shift)).date()
```

and the real datetime at the start of calendar date `cd` is

```
datetime.combine(cd, time()) + timedelta(hours=cal_shift)
```

`day_start` and `day_end` are measured from that shifted day-start, not
from midnight, so `day_start=0, day_end=24` always denotes a 24-hour
business day regardless of `cal_shift`.

**Example.** A dyeing facility runs three 8-hour shifts: 23:00–07:00,
07:00–15:00, 15:00–23:00. Its "Monday" begins at 23:00 on Sunday (real
clock) and ends at 23:00 on Monday. That calendar is
`WorkCal(weekdays=[0,1,2,3,4], day_start=0, day_end=24, holidays=[...],
cal_shift=-1)`.

### Effect on operations

- `is_workday(d)` takes a *calendar* date — i.e., the date returned by
  `calendar_date(...)`, not necessarily the real-clock date a wall-clock
  observer would call it.
- `offset_work_days` operates in calendar days; its inputs and outputs are
  calendar dates.
- `offset_work_hours`, `get_work_hours_between`, and
  `avail_hours_before_weekend` take real datetimes and internally map them
  to calendar time via `cal_shift`.

### Operations

#### Snapping rule

The two offset operations both *snap* an input that falls outside of working
time onto the nearest business boundary before counting:

- If the offset is `>= 0`, snap **forward** to the next workday / next
  business hour.
- If the offset is `< 0`, snap **backward** to the previous workday /
  previous business hour.

A consequence is that calling either offset with `0` is a pure
snap-forward: it returns the input if it's already in working time, or the
next working boundary if not.

#### `is_workday(d) -> bool`

True iff `d.weekday()` is in `self.weekdays` and `d` does not coincide
with any holiday in `self.holidays` for that year.

#### `offset_work_days(start, days) -> date`

Returns the date that is `days` working days away from `start`. Sign
convention is symmetric: positive `days` advances forward, negative `days`
walks backward. Non-working days (weekends and holidays) are skipped — only
workdays count toward the offset. `date` is snapped per the rule above
before counting.

#### `offset_work_hours(start, hours) -> datetime`

Returns the datetime that is `hours` working hours away from `start`. `hours`
is a `float`, so fractional hours are supported. Time outside of business
hours (before `day_start`, after `day_end`, or on non-working days) does
not count toward the offset. Sign convention is symmetric. `start` is snapped
per the rule above before counting.

#### `get_work_hours_between(start, end) -> float`

Returns the total number of working hours falling within the interval
`[start, end]`. Time outside of business hours is excluded. Returns `0`
when `start >= end` (the function does not produce signed results).

#### `avail_hours_before_weekend(start) -> float`

Returns the number of working hours between `start` and the end of the ISO
calendar week that contains `start`'s calendar date — i.e., the instant
calendar Sunday rolls into calendar Monday. Equivalent to
`get_work_hours_between(start, end_of_iso_week)`.

`start` is **not** snapped. Any working hours falling between `start` and
end-of-week are counted; any non-working hours in that range are not.
Consequently:

- On a Mon-Fri calendar, calling with a Saturday or Sunday `start` returns
  `0`.
- On a Mon-Fri calendar with a Wednesday holiday, calling at Monday morning
  returns `4 * work_hours_per_day` (Mon + Tue + Thu + Fri).
- On a 24/7 calendar (all seven weekdays working), the function is still
  well-defined: it returns the working hours between `start` and the next
  calendar-Monday boundary.

Useful for asking "can this finish before the week is out?"
