# Specification of coverage of workcal submodule

These tests target the `swmtplanner.support.workcal` submodule.

## Section 1: FlexDate and FixedDate

Since `Holiday` cannot be directly instantiated, there is nothing to test, so these will focus on
the behavior of `FixedDate` and `FlexDate`.

### 1.1 FixedDate

This is a very straightforward dataclass whose `date_in_year` method requires no complex calculation&mdash;this
section is simply for symmetry.

1. **construction works as expected** - test arbitrary date
2. **`date_in_year` works as expected** - test a couple year values on one `FixedDate` object

### 1.2 FlexDate

Run all tests on Thanksgiving and Memorial Day.

1. **construction works as expected**
2. **`date_in_year` works as expected**
    - test 2026 yields November 26 for Thanksgiving and May 25 for Memorial Day
    - test 2025 yields November 27 for Thanksgiving and May 26 for Memorial Day

## Section 2: WorkCal

### 2.1 Construction

1. **read-only and computed properties are correct** - test 24/7 work calendar and 9-5 Monday-Friday calendar
2. **editing input list after construction does not modify object**

### 2.2 Date-based operations

Tests targeting `is_workday` and `offset_work_days`. Some tests may use fake holidays for convenience/artificially
triggering edge cases.

#### 2.2.1 `is_workday` behavior

1. **False for weekends**
2. **False for weekday holiday** - test both `FixedDate` and `FlexDate` holidays
3. **False for weekend that is also a holiday**
4. **True for a workday that is not a holiday**
    - plain weekday on a Mon-Fri calendar with no holidays
    - plain weekday on a Mon-Fri calendar with holidays (queried date is not one)
    - weekend day on a 24/7 calendar with no holidays

#### 2.2.2 `offset_work_days` behavior

1. **no-op when start is a workday and `days=0`** - returns `start` unchanged
2. **snap-forward only when `days=0` and start is non-working**
    - weekend start
    - holiday start (on a weekday)
    - weekend start where the following Monday is a holiday
3. **forward offset (`days>0`)**
    - on a 24/7 calendar with no holidays, returns `start + timedelta(days=days)`
    - on a 24/7 calendar with holidays, correctly skips the holidays
    - on a Mon-Fri calendar, offset that crosses a weekend lands on the correct workday
    - on a Mon-Fri calendar, offset whose path contains a weekday holiday skips it
    - on a Mon-Fri calendar, non-workday start is snapped forward before counting
4. **backward offset (`days<0`)**
    - on a 24/7 calendar with no holidays, returns `start + timedelta(days=days)`
    - on a 24/7 calendar with holidays, correctly skips the holidays
    - on a Mon-Fri calendar, offset that crosses a weekend lands on the correct workday
    - on a Mon-Fri calendar, offset whose path contains a weekday holiday skips it
    - on a Mon-Fri calendar, non-workday start is snapped backward before counting

### 2.3 Datetime-based operations

Tests targeting `offset_work_hours`, `get_work_hours_between`, and `avail_hours_before_weekend`. Some
tests may use fake holidays for convenience/artificially triggering edge cases.

#### 2.3.1 `offset_work_hours` behavior

1. **no-op when start is in business time and `hours=0`** - returns `start` unchanged
2. **snap-forward only when `hours=0` and start is non-business**
    - start before `day_start` on a workday (snaps to today's `day_start`)
    - start at or after `day_end` on a workday (snaps to next workday's `day_start`)
    - start on a weekend
    - start on a holiday
3. **snap-backward when `hours<0` and start is non-business**
    - start after `day_end` on a workday (snaps to today's `day_end`)
    - start at or before `day_start` on a workday (snaps to previous workday's `day_end`)
    - start on a weekend
    - start on a holiday
4. **forward offset (`hours>0`)**
    - on a 24/7 calendar with no holidays, returns `start + timedelta(hours=hours)`
    - on a 24/7 calendar with holidays, correctly skips holiday days
    - on a Mon-Fri 9-5 calendar, offset that stays within a single workday
    - offset that crosses one workday boundary (consumes today's remainder, partial tomorrow)
    - offset that crosses a weekend lands on the correct workday and time-of-day
    - offset whose path contains a weekday holiday skips it
    - fractional `hours` land at the correct sub-hour offset
5. **backward offset (`hours<0`)**
    - on a 24/7 calendar with no holidays, returns `start + timedelta(hours=hours)`
    - on a 24/7 calendar with holidays, correctly skips holiday days
    - on a Mon-Fri 9-5 calendar, offset that stays within a single workday
    - offset that crosses one workday boundary (consumes today's elapsed time, partial previous day)
    - offset that crosses a weekend lands on the correct workday and time-of-day
    - offset whose path contains a weekday holiday skips it
    - fractional `hours` land at the correct sub-hour offset
6. **calendar-shift behavior** - non-zero `cal_shift` produces a result in real (un-shifted) time; e.g.,
   on a `cal_shift=-1` 24-hour calendar, 8 hours forward from Sunday 23:00 lands on Monday 07:00

#### 2.3.2 `get_work_hours_between` behavior

1. **zero-result cases**
    - `start == end` returns 0
    - `start > end` returns 0
    - both endpoints in the same outside-business window on a workday (e.g., both before `day_start`)
    - both endpoints on the same non-workday
2. **single workday**
    - both endpoints within business hours returns `(end - start)` in hours
    - start before `day_start`, end within business: returns `(end - day_start)`
    - start within business, end after `day_end`: returns `(day_end - start)`
    - start before `day_start`, end after `day_end`: returns `work_hours_per_day`
3. **multi-day intervals**
    - full consecutive workdays (e.g., Mon `day_start` to Fri `day_end` on a Mon-Fri calendar)
    - partial first day, full middle day(s), partial last day
    - interval spans a weekend (weekend hours excluded)
    - interval spans a weekday holiday (holiday hours excluded)
4. **calendar-shift behavior** - non-zero `cal_shift` produces the correct duration

#### 2.3.3 `avail_hours_before_weekend` behavior

Returns work hours between `start` and the end of the ISO calendar week containing `start`'s calendar
date. No snapping is applied to `start`.

1. **start mid-workday in business hours**
    - early in the week (e.g., Monday morning on a Mon-Fri 9-5) returns the full work week
    - late in the week (e.g., Friday afternoon) returns only hours until Friday's `day_end`
2. **start in non-working time** (no snap is applied)
    - start before `day_start` on Monday returns the full work week
    - start at or after `day_end` on Monday returns the work week minus Monday
    - start on a Saturday or Sunday on a Mon-Fri calendar returns 0
    - start on a weekday holiday returns the work-week hours from the next workday onward
3. **mid-week holiday is excluded but does not truncate** - e.g., Monday morning with a Wednesday
   holiday on a Mon-Fri 9-5 returns `4 * work_hours_per_day` (Mon + Tue + Thu + Fri)
4. **24/7 calendar** - all seven weekdays working, no holidays: from Wednesday noon returns
   `4.5 * 24 = 108` hours (well-defined, no snap-forward loop)
5. **calendar-shift behavior** - `cal_shift` is applied to `start` to determine its ISO calendar week
   (e.g., on a `cal_shift=-1` calendar, calling at real Sunday 23:00 returns a full calendar work
   week, since Sun 23:00 real is Mon 00:00 calendar — the start of a new ISO week)