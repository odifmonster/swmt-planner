# workcal — Design

`workcal` delegates date math across working hours: arithmetic that must skip
holidays, skip non-business hours, and handle overnight shifts that cross a day
boundary.

## Overview

`workcal` is made up of two parts:

- The main module, which holds the `WorkCal` class (the working-calendar engine).
- The `holiday` submodule, which holds convenience dataclasses for describing
  recurring holidays plus a loader for reading them from JSON.

`WorkCal` uses holiday definitions to determine which days are non-working.

## Core objects

### Module level

- Constants: none.
- Classes:
  ```python
  class WorkCal:
      def __init__(
          self,
          weekdays: list[int],
          day_start: int,
          day_end: int,
          holidays: list[Holiday],
          cal_shift: int = 0,
      ): ...

      # read-only properties
      @property
      def weekdays(self) -> tuple[int, ...]: ...
      @property
      def day_start(self) -> int: ...
      @property
      def day_end(self) -> int: ...
      @property
      def holidays(self) -> tuple[Holiday, ...]: ...
      @property
      def cal_shift(self) -> int: ...
      @property
      def work_days_per_week(self) -> int: ...      # computed
      @property
      def work_hours_per_day(self) -> int: ...      # computed

      def is_workday(self, date: date) -> bool: ...
      def offset_work_days(self, start: date, days: int) -> date: ...
      def offset_work_hours(self, start: datetime, hours: float) -> datetime: ...
      def get_work_hours_between(self, start: datetime, end: datetime) -> float: ...
      def avail_hours_before_weekend(self, start: datetime) -> float: ...
  ```

### `holiday` submodule

No dedicated `DESIGN.md`; documented here.

- Constants: none.
- Functions:
  ```python
  def load_holidays(json_str: str) -> list[Holiday]: ...
  ```
- Classes:
  ```python
  class Holiday(ABC):
      name: str
      month: int

      @abstractmethod
      def get_date_in_year(self, year: int) -> date: ...

  @dataclass(frozen=True)
  class FixedDate(Holiday):
      name: str
      month: int
      day: int

  @dataclass(frozen=True)
  class FlexDate(Holiday):
      name: str
      month: int
      weekday: int   # 0 = Monday
      n: int         # 1-indexed; the nth `weekday` of `month`
  ```

## `holiday` submodule

Convenience dataclasses for representing holidays, plus a JSON loader. The
holiday dataclasses are frozen — a holiday, once defined, does not change.

### `Holiday` (abstract base)

The base class for all holidays.

- `name` — the holiday's name (e.g. "Christmas").
- `month` — the month the holiday falls in.
- `get_date_in_year(year: int)` — abstract method returning the date on which the
  holiday falls in the given `year`.

### `FixedDate`

A holiday that falls on the same calendar date every year (e.g. Christmas).
Extends `Holiday` with:

- `day` — the day of the month.

`get_date_in_year(year)` returns the date `(year, month, day)`.

### `FlexDate`

A holiday that falls on a particular weekday of its month (e.g. Memorial Day).
Extends `Holiday` with:

- `weekday` — the weekday it falls on, with `0 = Monday`.
- `n` — which occurrence of that `weekday` within the `month`. It is 1-indexed
  but may be negative: `n = 1` is the first such weekday, `n = -1` is the last.

`get_date_in_year(year)` returns the date of the `n`th `weekday` of `month` in
the given `year`.

### `load_holidays`

Parses a set of holiday definitions from a JSON string and returns the
corresponding `Holiday` objects. The loader always receives a JSON string;
opening files is handled at the `app` layer.

The JSON string describes a list of holidays. Each holiday is a JSON object
whose keys are the dataclass fields and whose values are those fields' values —
e.g. `name`, `month`, `day` for a `FixedDate`, or `name`, `month`, `weekday`,
`n` for a `FlexDate`. The loader inspects the field list of each object to pick
the right `Holiday` subclass, and is responsible for validating that the JSON
string describes a valid list of holidays.

## `WorkCal`

The working-calendar engine. It is initialized with a list of weekday integers,
the workday start and end hours, a list of holidays, and optionally the calendar
shift (defaults to `0`).

### Properties (read-only)

- `weekdays` — a tuple of the days of the week that are working days, where
  `0 = Monday`.
- `day_start` — the hour the business day starts, as an integer.
- `day_end` — the hour the business day ends, as an integer. May be `24` to allow
  24-hour work days.
- `holidays` — the calendar's holidays.
- `cal_shift` — the integer number of hours the overnight shift is offset from
  midnight. For example, if the overnight shift runs from 11pm to 7am, this value
  is `-1` and every "day" is considered to end at 11pm. Defaults to `0`.
- `work_days_per_week` — computed: the number of working days in a week (the
  count of `weekdays`).
- `work_hours_per_day` — computed: the number of working hours in a day
  (`day_end - day_start`).

`day_start` and `day_end` are given *before* the calendar shift is applied. For
example, a factory running three 8-hour shifts with an overnight shift from 11pm
to 7am passes `day_start = 0` and `day_end = 24` (not `-1` and `23`, which would
be confusing). Only the offsetting and available-hours methods apply `cal_shift`,
since those are the ones provided real calendar datetimes to work from.

### Methods

#### `is_workday(date)`

Whether `date` is a working day (its weekday is in `weekdays` and it is not a
holiday).

The holiday check does **not** recompute all the holidays on every call. Instead
the calendar lazily computes and caches all the holiday ordinals within a range
of years, extending that range as needed:

- On the first call, it computes and caches the holiday ordinals for `date.year`
  and notes the cached range as `(date.year, date.year + 1)`.
- Any subsequent call for a date in an already-cached year simply checks that
  date's ordinal against the cached holiday ordinals.
- The first call for a date outside the cached range triggers computing the
  holiday ordinals for all the years between the relevant cache bound and the
  year of the date passed in, then updates the cache's year range to include it.

#### `offset_work_days(start, days)`

The date `days` working days from `start`. Accepts negative `days`.

If `start` is not a work day, it snaps in the direction of travel before
applying the offset: backward for negative `days`, forward for `days >= 0`.

#### `offset_work_hours(start, hours)`

The datetime `hours` working hours from `start`. Accepts negative `hours`.

If `start` is not within work hours, it snaps in the direction of travel before
applying the offset: backward for negative `hours`, forward for `hours >= 0`.

#### `get_work_hours_between(start, end)`

The number of working hours between `start` and `end`. It does **not** compute
negative intervals: it returns `0` if `start >= end`.

#### `avail_hours_before_weekend(start)`

The number of working hours remaining between `start` and the end of the week
containing `start`, using the ISO calendar week that contains `start` (after
adjusting for the calendar shift). For example, if `start` is a Sunday and the
calendar treats Sunday as a weekend, it returns `0`.
