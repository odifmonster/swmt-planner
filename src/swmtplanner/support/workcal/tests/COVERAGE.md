# workcal — Test Coverage

Test coverage for the `support/workcal/` submodule (`unittest`).

## Section 1 — `holiday` submodule

### 1.1 `FixedDate`

1. **Construction** — build a `FixedDate` (e.g. Christmas: `name='Christmas'`,
   `month=12`, `day=25`) and verify the fields are stored correctly.
2. **`get_date_in_year`** — one (trivial) check that it returns the expected
   date, e.g. `date(year, 12, 25)`.

### 1.2 `FlexDate`

1. **Construction** — build a `FlexDate` and verify the fields are stored
   correctly.
2. **`get_date_in_year`, positive `n`** — verify the nth-weekday calculation for
   a positive `n`.
3. **`get_date_in_year`, negative `n`** — verify the calculation for a negative
   `n` (e.g. `n = -1` for the last occurrence).
4. **A couple of dates, ≥ 2 weekdays** — check `get_date_in_year` against a
   couple of known dates, covering at least two different weekdays (e.g. the 4th
   Thursday of November and the last Monday of May, across a couple of years).

### 1.3 `load_holidays`

1. **Error: not a list** — a JSON string that describes something other than a
   list (e.g. a single object) raises `ValueError`.
2. **Error: element not a JSON object** — a JSON list with an element that is not
   an object (e.g. a number) raises `ValueError`.
3. **Error: element with wrong fields** — a JSON list with an object whose fields
   do not match any holiday type raises `ValueError`.
4. **Valid input** — a valid JSON string (mixing `FixedDate` and `FlexDate`
   entries) returns the correct list of `Holiday` objects.

## Section 2 — `WorkCal`

### 2.1 Construction

1. **Trivial construction** — build a `WorkCal` and confirm it constructs
   correctly, including that the computed properties (`work_days_per_week`,
   `work_hours_per_day`) behave as expected.

### 2.2 `is_workday`

1. **Weekend-less calendar** (every weekday is a working day) — returns `False`
   on both a `FixedDate` and a `FlexDate` holiday, and `True` otherwise.
2. **Calendar with a weekend** — returns `False` on:
   1. `FixedDate` and `FlexDate` holidays that fall on weekends,
   2. weekend days with no holiday,
   3. non-weekend `FixedDate` and `FlexDate` holidays,

   and `True` otherwise.
3. **Calendar with a weekend and no holidays** — returns `False` on weekend days
   and `True` otherwise.

### 2.3 `offset_work_days`

1. **Snap forward on 0 from a non-workday** — `days = 0` starting on a non-working
   day snaps forward to the next working day.
2. **No-op on 0 from a workday** — `days = 0` starting on a working day returns
   that same day.
3. **Snap backward before advancing on negative days from a non-workday** — a
   negative `days` starting on a non-working day snaps backward to the previous
   working day before applying the offset.
4. **Forward and backward correctness** — a couple of cases each for forward and
   backward traversal, covering crossing weekends, non-weekend holidays, weekend
   holidays, and both `FixedDate` and `FlexDate` holidays.

### 2.4 `offset_work_hours`

1. **Snapping behavior** —
   1. `hours = 0` starting outside working hours snaps forward to the next
      working hour;
   2. `hours = 0` starting within working hours returns that same instant;
   3. a negative `hours` starting outside working hours snaps backward before
      applying the offset;
   4. with a calendar shift (overnight shift, `cal_shift = -1`): snapping forward
      into a day that starts at 11pm the previous day, and snapping backward into
      a day that ends at 11pm (using a non-zero `hours` value).
2. **Non-24-hour calendar correctness** — on a calendar whose working day is
   shorter than 24 hours: starting within a working day and starting outside one,
   for both forward and backward traversal.
3. **Skips holidays and weekends** — confirm the offset correctly skips over
   holidays and weekends.

### 2.5 `get_work_hours_between`

1. **Start and end outside working hours** — both endpoints fall outside working
   hours.
2. **Interval contains a weekend** — the interval spans a weekend.
3. **Interval contains holidays** — the interval spans one or more holidays.
4. **Interval of only non-working hours** — an interval containing only
   non-working hours returns `0`.
5. **Interval entirely within working hours** — returns the same value as a
   regular datetime subtraction.
6. **24-hour, no-weekend, no-holiday calendar** — returns the same value as a
   regular datetime subtraction.
7. **`start >= end`** — returns `0`.
8. **Calendar shift** — a 24-hour calendar with `cal_shift = -4` makes holidays
   start 4 hours "early": an end datetime after 8pm on the eve of a holiday does
   not include the hours after 8pm (they fall on the shifted holiday).

### 2.6 `avail_hours_before_weekend`

Since `avail_hours_before_weekend` calls `get_work_hours_between`, far fewer
cases are needed.

1. **Start inside a weekend** — a start that falls within the weekend returns
   `0`.
2. **Start before the weekend** — a start before the weekend correctly computes
   the remaining working hours in the week.
