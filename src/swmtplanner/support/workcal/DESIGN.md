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

    # computed properties
    work_days_per_week: int
    work_hours_per_day: int

    def __init__(
        self,
        weekdays: list[int],
        day_start: int,
        day_end: int,
        holidays: list[Holiday],
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

`WorkCal(weekdays, day_start, day_end, holidays)`:

- `weekdays: list[int]` — working weekdays, Python `date.weekday()`
  convention (Mon=0..Sun=6).
- `day_start: int` — hour the business day begins, in `[0, 24]`.
- `day_end: int` — hour the business day ends, in `[0, 24]`. `day_end=24`
  denotes a business day that runs to the end of the calendar day (i.e., a
  24-hour workday when paired with `day_start=0`).
- `holidays: list[Holiday]` — holidays observed by this calendar.

Both list arguments are **copied** at construction so that mutations to the
caller's lists cannot affect the calendar's internal state.

### Read-only state

After construction, all configured state is exposed as read-only `tuple`s;
there are no setters. Callers cannot mutate a `WorkCal` after it is built.

- `weekdays: tuple[int, ...]`
- `day_start: int`
- `day_end: int`
- `holidays: tuple[Holiday, ...]`

### Computed properties

- `work_days_per_week: int` — `len(weekdays)`.
- `work_hours_per_day: int` — `day_end - day_start`.

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

Returns the number of working hours between `start` and the start of the
next contiguous run of non-working days (i.e., the end of the current work
week from `start`'s perspective). If `start` is itself in non-working time
it is snapped forward first, so the result reflects the work week that
`start` enters into. Useful for asking "can this finish before the week is
out?"
