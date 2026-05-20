#!/usr/bin/env python

import unittest
from datetime import date, datetime, timedelta

from swmtplanner.support.workcal import WorkCal
from swmtplanner.support.workcal.holiday import FixedDate, FlexDate


class ConstructionTests(unittest.TestCase):
    """Covers section 2.1 of COVERAGE.md."""

    def setUp(self):
        self.christmas = FixedDate(name='Christmas', month=12, day=25)
        self.july4 = FixedDate(name='Independence Day', month=7, day=4)
        self.thanksgiving = FlexDate(name='Thanksgiving', month=11, weekday=3, n=4)
        self.mem_day = FlexDate(name='Memorial Day', month=5, weekday=0, n=-1)

    def test_24_7_properties(self):
        """2.1.1: read-only and computed properties on a 24/7 calendar"""
        cal = WorkCal([0, 1, 2, 3, 4, 5, 6], 0, 24, [])
        self.assertEqual(cal.weekdays, (0, 1, 2, 3, 4, 5, 6))
        self.assertIsInstance(cal.weekdays, tuple)
        self.assertEqual(cal.day_start, 0)
        self.assertEqual(cal.day_end, 24)
        self.assertEqual(cal.holidays, ())
        self.assertIsInstance(cal.holidays, tuple)
        self.assertEqual(cal.cal_shift, 0)
        self.assertEqual(cal.work_days_per_week, 7)
        self.assertEqual(cal.work_hours_per_day, 24)

    def test_mon_fri_9_5_properties(self):
        """2.1.1: read-only and computed properties on a Mon-Fri 9-5 calendar"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [self.christmas])
        self.assertEqual(cal.weekdays, (0, 1, 2, 3, 4))
        self.assertIsInstance(cal.weekdays, tuple)
        self.assertEqual(cal.day_start, 9)
        self.assertEqual(cal.day_end, 17)
        self.assertEqual(cal.holidays, (self.christmas,))
        self.assertIsInstance(cal.holidays, tuple)
        self.assertEqual(cal.cal_shift, 0)
        self.assertEqual(cal.work_days_per_week, 5)
        self.assertEqual(cal.work_hours_per_day, 8)

    def test_input_list_isolation(self):
        """2.1.2: mutating input lists after construction does not modify the WorkCal"""
        weekdays = [0, 1, 2, 3, 4]
        holidays = [self.christmas]
        cal = WorkCal(weekdays, 9, 17, holidays)

        weekdays.append(5)
        holidays.append(self.thanksgiving)

        self.assertEqual(cal.weekdays, (0, 1, 2, 3, 4))
        self.assertEqual(cal.holidays, (self.christmas,))


class IsWorkdayTests(unittest.TestCase):
    """Covers section 2.2.1 of COVERAGE.md."""

    def setUp(self):
        self.christmas = FixedDate(name='Christmas', month=12, day=25)
        self.july4 = FixedDate(name='Independence Day', month=7, day=4)
        self.thanksgiving = FlexDate(name='Thanksgiving', month=11, weekday=3, n=4)
        self.mem_day = FlexDate(name='Memorial Day', month=5, weekday=0, n=-1)

    def test_false_for_weekends(self):
        """2.2.1.1: returns False for Saturday and Sunday"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        self.assertFalse(cal.is_workday(date(2026, 11, 28)))  # Sat
        self.assertFalse(cal.is_workday(date(2026, 11, 29)))  # Sun

    def test_false_for_weekday_fixed_holiday(self):
        """2.2.1.2: returns False for a FixedDate holiday on a weekday"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [self.christmas])
        self.assertFalse(cal.is_workday(date(2025, 12, 25)))  # Christmas 2025 = Thu

    def test_false_for_weekday_flex_holiday(self):
        """2.2.1.2: returns False for a FlexDate holiday on a weekday"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [self.thanksgiving])
        self.assertFalse(cal.is_workday(date(2026, 11, 26)))  # Thanksgiving 2026 = Thu

    def test_false_for_weekend_holiday(self):
        """2.2.1.3: returns False when a holiday lands on a weekend"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [self.july4])
        self.assertFalse(cal.is_workday(date(2026, 7, 4)))  # Independence Day 2026 = Sat

    def test_true_for_workday(self):
        """2.2.1.4: returns True for a workday that is not a holiday"""
        # Plain weekday, no holidays
        cal_no_holidays = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        self.assertTrue(cal_no_holidays.is_workday(date(2026, 11, 23)))  # Mon

        # Weekday on a calendar with holidays, but queried date is not one
        cal_with_holidays = WorkCal([0, 1, 2, 3, 4], 9, 17, [self.thanksgiving, self.christmas])
        self.assertTrue(cal_with_holidays.is_workday(date(2026, 11, 23)))  # Mon, not a holiday

        # Weekend day on a 24/7 calendar
        cal_24_7 = WorkCal([0, 1, 2, 3, 4, 5, 6], 0, 24, [])
        self.assertTrue(cal_24_7.is_workday(date(2026, 11, 28)))  # Sat


class OffsetWorkDaysTests(unittest.TestCase):
    """Covers section 2.2.2 of COVERAGE.md."""

    def setUp(self):
        self.christmas = FixedDate(name='Christmas', month=12, day=25)
        self.july4 = FixedDate(name='Independence Day', month=7, day=4)
        self.thanksgiving = FlexDate(name='Thanksgiving', month=11, weekday=3, n=4)
        self.mem_day = FlexDate(name='Memorial Day', month=5, weekday=0, n=-1)

    def test_noop_workday_zero(self):
        """2.2.2.1: returns start unchanged when start is a workday and days=0"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        monday = date(2026, 11, 23)
        self.assertEqual(cal.offset_work_days(monday, 0), monday)

    def test_snap_forward_weekend_start(self):
        """2.2.2.2: days=0 with weekend start snaps to the following Monday"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Sat Nov 28 -> Sun -> Mon Nov 30
        self.assertEqual(cal.offset_work_days(date(2026, 11, 28), 0), date(2026, 11, 30))

    def test_snap_forward_holiday_start(self):
        """2.2.2.2: days=0 with weekday-holiday start snaps to next workday"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [self.thanksgiving])
        # Thu Nov 26 (Thanksgiving) -> Fri Nov 27
        self.assertEqual(cal.offset_work_days(date(2026, 11, 26), 0), date(2026, 11, 27))

    def test_snap_forward_weekend_into_holiday(self):
        """2.2.2.2: weekend start where following Monday is a holiday snaps past both"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [self.mem_day])
        # Sat May 23 -> Sun -> Mon (Memorial Day) -> Tue May 26
        self.assertEqual(cal.offset_work_days(date(2026, 5, 23), 0), date(2026, 5, 26))

    # ---- forward offset (days > 0) ----

    def test_forward_24_7_no_holidays(self):
        """2.2.2.3: 24/7 no-holidays returns start + timedelta(days=days)"""
        cal = WorkCal([0, 1, 2, 3, 4, 5, 6], 0, 24, [])
        start = date(2026, 11, 23)
        self.assertEqual(cal.offset_work_days(start, 5), start + timedelta(days=5))

    def test_forward_24_7_skips_holiday(self):
        """2.2.2.3: 24/7 calendar skips holidays in path"""
        cal = WorkCal([0, 1, 2, 3, 4, 5, 6], 0, 24, [self.thanksgiving])
        # Mon Nov 23, +4: Tue, Wed, [skip Thu Thanksgiving], Fri, Sat Nov 28
        self.assertEqual(cal.offset_work_days(date(2026, 11, 23), 4), date(2026, 11, 28))

    def test_forward_mon_fri_crosses_weekend(self):
        """2.2.2.3: Mon-Fri offset crosses weekend to land on correct workday"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Thu Nov 19, +4: Fri, [skip weekend], Mon, Tue, Wed Nov 25
        self.assertEqual(cal.offset_work_days(date(2026, 11, 19), 4), date(2026, 11, 25))

    def test_forward_mon_fri_skips_holiday(self):
        """2.2.2.3: Mon-Fri offset skips weekday holiday in path"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [self.thanksgiving])
        # Wed Nov 25, +2: [skip Thu Thanksgiving], Fri Nov 27, [skip weekend], Mon Nov 30
        self.assertEqual(cal.offset_work_days(date(2026, 11, 25), 2), date(2026, 11, 30))

    def test_forward_mon_fri_non_workday_start(self):
        """2.2.2.3: Mon-Fri non-workday start is snapped forward before counting"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Sat Nov 28 -> snap to Mon Nov 30, +2: Tue, Wed Dec 2
        self.assertEqual(cal.offset_work_days(date(2026, 11, 28), 2), date(2026, 12, 2))

    # ---- backward offset (days < 0) ----

    def test_backward_24_7_no_holidays(self):
        """2.2.2.4: 24/7 no-holidays returns start + timedelta(days=days)"""
        cal = WorkCal([0, 1, 2, 3, 4, 5, 6], 0, 24, [])
        start = date(2026, 11, 28)
        self.assertEqual(cal.offset_work_days(start, -5), start + timedelta(days=-5))

    def test_backward_24_7_skips_holiday(self):
        """2.2.2.4: 24/7 calendar skips holidays in path"""
        cal = WorkCal([0, 1, 2, 3, 4, 5, 6], 0, 24, [self.thanksgiving])
        # Sat Nov 28, -4: Fri, [skip Thu Thanksgiving], Wed, Tue, Mon Nov 23
        self.assertEqual(cal.offset_work_days(date(2026, 11, 28), -4), date(2026, 11, 23))

    def test_backward_mon_fri_crosses_weekend(self):
        """2.2.2.4: Mon-Fri offset crosses weekend backward to correct workday"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Tue Nov 24, -3: Mon, [skip weekend], Fri, Thu Nov 19
        self.assertEqual(cal.offset_work_days(date(2026, 11, 24), -3), date(2026, 11, 19))

    def test_backward_mon_fri_skips_holiday(self):
        """2.2.2.4: Mon-Fri offset skips weekday holiday in path backward"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [self.thanksgiving])
        # Mon Nov 30, -2: [skip weekend], Fri Nov 27, [skip Thu Thanksgiving], Wed Nov 25
        self.assertEqual(cal.offset_work_days(date(2026, 11, 30), -2), date(2026, 11, 25))

    def test_backward_mon_fri_non_workday_start(self):
        """2.2.2.4: Mon-Fri non-workday start is snapped backward before counting"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Sun Nov 29 -> snap back to Fri Nov 27, -2: Thu, Wed Nov 25
        self.assertEqual(cal.offset_work_days(date(2026, 11, 29), -2), date(2026, 11, 25))


class OffsetWorkHoursTests(unittest.TestCase):
    """Covers section 2.3.1 of COVERAGE.md."""

    def setUp(self):
        self.christmas = FixedDate(name='Christmas', month=12, day=25)
        self.july4 = FixedDate(name='Independence Day', month=7, day=4)
        self.thanksgiving = FlexDate(name='Thanksgiving', month=11, weekday=3, n=4)
        self.mem_day = FlexDate(name='Memorial Day', month=5, weekday=0, n=-1)

    def test_noop_in_business_zero(self):
        """2.3.1.1: returns start unchanged when in business hours and hours=0"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        dt = datetime(2026, 11, 23, 10, 0)  # Mon 10am
        self.assertEqual(cal.offset_work_hours(dt, 0), dt)

    # ---- snap-forward (hours=0, non-business start) ----

    def test_snap_forward_zero_before_day_start(self):
        """2.3.1.2: hours=0, start before day_start on workday -> today's day_start"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Mon 7am -> Mon 9am
        self.assertEqual(
            cal.offset_work_hours(datetime(2026, 11, 23, 7, 0), 0),
            datetime(2026, 11, 23, 9, 0),
        )

    def test_snap_forward_zero_at_or_after_day_end(self):
        """2.3.1.2: hours=0, start at/after day_end on workday -> next workday's day_start"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Mon 5pm (at day_end) -> Tue 9am
        self.assertEqual(
            cal.offset_work_hours(datetime(2026, 11, 23, 17, 0), 0),
            datetime(2026, 11, 24, 9, 0),
        )
        # Mon 8pm -> Tue 9am
        self.assertEqual(
            cal.offset_work_hours(datetime(2026, 11, 23, 20, 0), 0),
            datetime(2026, 11, 24, 9, 0),
        )

    def test_snap_forward_zero_weekend(self):
        """2.3.1.2: hours=0 with weekend start -> next Monday's day_start"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Sat noon -> Mon 9am
        self.assertEqual(
            cal.offset_work_hours(datetime(2026, 11, 28, 12, 0), 0),
            datetime(2026, 11, 30, 9, 0),
        )

    def test_snap_forward_zero_holiday(self):
        """2.3.1.2: hours=0 with holiday start -> next workday's day_start"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [self.thanksgiving])
        # Thu Nov 26 (Thanksgiving) 10am -> Fri Nov 27 9am
        self.assertEqual(
            cal.offset_work_hours(datetime(2026, 11, 26, 10, 0), 0),
            datetime(2026, 11, 27, 9, 0),
        )

    # ---- snap-backward (hours<0, non-business start) ----

    def test_snap_backward_after_day_end(self):
        """2.3.1.3: hours<0, start after day_end on workday -> today's day_end, then offset"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Mon 8pm -> snap to Mon 5pm, then -1h -> Mon 4pm
        self.assertEqual(
            cal.offset_work_hours(datetime(2026, 11, 23, 20, 0), -1),
            datetime(2026, 11, 23, 16, 0),
        )

    def test_snap_backward_at_or_before_day_start(self):
        """2.3.1.3: hours<0, start at/before day_start on workday -> prev workday's day_end"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Tue 8am -> snap to Mon 5pm, then -1h -> Mon 4pm
        self.assertEqual(
            cal.offset_work_hours(datetime(2026, 11, 24, 8, 0), -1),
            datetime(2026, 11, 23, 16, 0),
        )

    def test_snap_backward_weekend(self):
        """2.3.1.3: hours<0 with weekend start -> prev workday's day_end"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Sat noon -> snap to Fri 5pm, then -1h -> Fri 4pm
        self.assertEqual(
            cal.offset_work_hours(datetime(2026, 11, 28, 12, 0), -1),
            datetime(2026, 11, 27, 16, 0),
        )

    def test_snap_backward_holiday(self):
        """2.3.1.3: hours<0 with holiday start -> prev workday's day_end"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [self.thanksgiving])
        # Thu (Thanksgiving) 10am -> snap to Wed Nov 25 5pm, then -1h -> Wed 4pm
        self.assertEqual(
            cal.offset_work_hours(datetime(2026, 11, 26, 10, 0), -1),
            datetime(2026, 11, 25, 16, 0),
        )

    # ---- forward offset (hours > 0) ----

    def test_forward_24_7_no_holidays(self):
        """2.3.1.4: 24/7 no-holidays returns start + timedelta(hours=hours)"""
        cal = WorkCal([0, 1, 2, 3, 4, 5, 6], 0, 24, [])
        start = datetime(2026, 11, 23, 10, 0)
        self.assertEqual(cal.offset_work_hours(start, 5), start + timedelta(hours=5))

    def test_forward_24_7_skips_holiday(self):
        """2.3.1.4: 24/7 calendar skips holiday days"""
        cal = WorkCal([0, 1, 2, 3, 4, 5, 6], 0, 24, [self.thanksgiving])
        # Wed Nov 25 noon, +24h: Wed 12-24 (12h), [skip Thu Thanksgiving], Fri 0-12 (12h) = Fri noon
        self.assertEqual(
            cal.offset_work_hours(datetime(2026, 11, 25, 12, 0), 24),
            datetime(2026, 11, 27, 12, 0),
        )

    def test_forward_mon_fri_within_workday(self):
        """2.3.1.4: Mon-Fri offset stays within a single workday"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Mon 10am, +3h -> Mon 1pm
        self.assertEqual(
            cal.offset_work_hours(datetime(2026, 11, 23, 10, 0), 3),
            datetime(2026, 11, 23, 13, 0),
        )

    def test_forward_mon_fri_crosses_workday_boundary(self):
        """2.3.1.4: Mon-Fri offset crosses one workday boundary"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Mon 3pm, +5h: Mon 3-5pm (2h), Tue 9am + 3h = Tue 12pm
        self.assertEqual(
            cal.offset_work_hours(datetime(2026, 11, 23, 15, 0), 5),
            datetime(2026, 11, 24, 12, 0),
        )

    def test_forward_mon_fri_crosses_weekend(self):
        """2.3.1.4: Mon-Fri offset crosses a weekend"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Fri 3pm, +4h: Fri 3-5pm (2h), [skip weekend], Mon 9am + 2h = Mon 11am
        self.assertEqual(
            cal.offset_work_hours(datetime(2026, 11, 27, 15, 0), 4),
            datetime(2026, 11, 30, 11, 0),
        )

    def test_forward_mon_fri_skips_holiday(self):
        """2.3.1.4: Mon-Fri offset whose path contains a weekday holiday"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [self.thanksgiving])
        # Wed Nov 25 3pm, +4h: Wed 3-5pm (2h), [skip Thanksgiving], Fri 9am + 2h = Fri 11am
        self.assertEqual(
            cal.offset_work_hours(datetime(2026, 11, 25, 15, 0), 4),
            datetime(2026, 11, 27, 11, 0),
        )

    def test_forward_fractional_hours(self):
        """2.3.1.4: fractional hours land at correct sub-hour offset"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Mon 10am, +1.5h -> Mon 11:30
        self.assertEqual(
            cal.offset_work_hours(datetime(2026, 11, 23, 10, 0), 1.5),
            datetime(2026, 11, 23, 11, 30),
        )

    # ---- backward offset (hours < 0) ----

    def test_backward_24_7_no_holidays(self):
        """2.3.1.5: 24/7 no-holidays returns start + timedelta(hours=hours)"""
        cal = WorkCal([0, 1, 2, 3, 4, 5, 6], 0, 24, [])
        start = datetime(2026, 11, 27, 10, 0)
        self.assertEqual(cal.offset_work_hours(start, -5), start + timedelta(hours=-5))

    def test_backward_24_7_skips_holiday(self):
        """2.3.1.5: 24/7 calendar skips holiday days backward"""
        cal = WorkCal([0, 1, 2, 3, 4, 5, 6], 0, 24, [self.thanksgiving])
        # Fri Nov 27 noon, -24h: Fri 0-12 (12h), [skip Thu Thanksgiving], Wed 12-24 (12h) = Wed noon
        self.assertEqual(
            cal.offset_work_hours(datetime(2026, 11, 27, 12, 0), -24),
            datetime(2026, 11, 25, 12, 0),
        )

    def test_backward_mon_fri_within_workday(self):
        """2.3.1.5: Mon-Fri backward offset stays within a single workday"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Mon 3pm, -3h -> Mon 12pm
        self.assertEqual(
            cal.offset_work_hours(datetime(2026, 11, 23, 15, 0), -3),
            datetime(2026, 11, 23, 12, 0),
        )

    def test_backward_mon_fri_crosses_workday_boundary(self):
        """2.3.1.5: Mon-Fri backward offset crosses one workday boundary"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Tue 11am, -5h: Tue 9-11 (2h), Mon 5pm - 3h = Mon 2pm
        self.assertEqual(
            cal.offset_work_hours(datetime(2026, 11, 24, 11, 0), -5),
            datetime(2026, 11, 23, 14, 0),
        )

    def test_backward_mon_fri_crosses_weekend(self):
        """2.3.1.5: Mon-Fri backward offset crosses a weekend"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Mon 11am, -4h: Mon 9-11 (2h), [skip weekend], Fri 5pm - 2h = Fri 3pm
        self.assertEqual(
            cal.offset_work_hours(datetime(2026, 11, 30, 11, 0), -4),
            datetime(2026, 11, 27, 15, 0),
        )

    def test_backward_mon_fri_skips_holiday(self):
        """2.3.1.5: Mon-Fri backward offset whose path contains a weekday holiday"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [self.thanksgiving])
        # Fri Nov 27 11am, -4h: Fri 9-11 (2h), [skip Thanksgiving], Wed 5pm - 2h = Wed 3pm
        self.assertEqual(
            cal.offset_work_hours(datetime(2026, 11, 27, 11, 0), -4),
            datetime(2026, 11, 25, 15, 0),
        )

    def test_backward_fractional_hours(self):
        """2.3.1.5: backward fractional hours land at correct sub-hour offset"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Mon 11:30, -1.5h -> Mon 10:00
        self.assertEqual(
            cal.offset_work_hours(datetime(2026, 11, 23, 11, 30), -1.5),
            datetime(2026, 11, 23, 10, 0),
        )

    # ---- calendar-shift ----

    def test_cal_shift_dyeing_facility(self):
        """2.3.1.6: cal_shift=-1 24-hour calendar, 8h forward from Sun 23:00 -> Mon 07:00"""
        cal = WorkCal([0, 1, 2, 3, 4], 0, 24, [], cal_shift=-1)
        # Real Sun 23:00 = calendar Mon 00:00; +8h work = calendar Mon 08:00 = real Mon 07:00
        self.assertEqual(
            cal.offset_work_hours(datetime(2026, 11, 22, 23, 0), 8),
            datetime(2026, 11, 23, 7, 0),
        )


class GetWorkHoursBetweenTests(unittest.TestCase):
    """Covers section 2.3.2 of COVERAGE.md."""

    def setUp(self):
        self.christmas = FixedDate(name='Christmas', month=12, day=25)
        self.july4 = FixedDate(name='Independence Day', month=7, day=4)
        self.thanksgiving = FlexDate(name='Thanksgiving', month=11, weekday=3, n=4)
        self.mem_day = FlexDate(name='Memorial Day', month=5, weekday=0, n=-1)

    # ---- zero-result cases ----

    def test_zero_start_equals_end(self):
        """2.3.2.1: start == end returns 0"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        dt = datetime(2026, 11, 23, 10, 0)
        self.assertEqual(cal.get_work_hours_between(dt, dt), 0)

    def test_zero_start_greater_than_end(self):
        """2.3.2.1: start > end returns 0"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        start = datetime(2026, 11, 23, 12, 0)
        end = datetime(2026, 11, 23, 10, 0)
        self.assertEqual(cal.get_work_hours_between(start, end), 0)

    def test_zero_both_outside_business_same_workday(self):
        """2.3.2.1: both endpoints in the same outside-business window on a workday"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Both before day_start on Monday
        self.assertEqual(
            cal.get_work_hours_between(
                datetime(2026, 11, 23, 6, 0),
                datetime(2026, 11, 23, 8, 0),
            ),
            0,
        )

    def test_zero_both_on_non_workday(self):
        """2.3.2.1: both endpoints on the same non-workday returns 0"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        self.assertEqual(
            cal.get_work_hours_between(
                datetime(2026, 11, 28, 10, 0),  # Sat
                datetime(2026, 11, 28, 14, 0),
            ),
            0,
        )

    # ---- single workday ----

    def test_single_workday_within_business(self):
        """2.3.2.2: both endpoints within business hours returns (end - start)"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        self.assertEqual(
            cal.get_work_hours_between(
                datetime(2026, 11, 23, 10, 0),
                datetime(2026, 11, 23, 14, 0),
            ),
            4,
        )

    def test_single_workday_start_before_business(self):
        """2.3.2.2: start before day_start, end within: returns (end - day_start)"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Mon 7am to Mon 12pm => 9-12 = 3h
        self.assertEqual(
            cal.get_work_hours_between(
                datetime(2026, 11, 23, 7, 0),
                datetime(2026, 11, 23, 12, 0),
            ),
            3,
        )

    def test_single_workday_end_after_business(self):
        """2.3.2.2: start within, end after day_end: returns (day_end - start)"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Mon 2pm to Mon 7pm => 14-17 = 3h
        self.assertEqual(
            cal.get_work_hours_between(
                datetime(2026, 11, 23, 14, 0),
                datetime(2026, 11, 23, 19, 0),
            ),
            3,
        )

    def test_single_workday_engulfs_business(self):
        """2.3.2.2: start before day_start, end after day_end: returns work_hours_per_day"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        self.assertEqual(
            cal.get_work_hours_between(
                datetime(2026, 11, 23, 6, 0),
                datetime(2026, 11, 23, 23, 0),
            ),
            8,
        )

    # ---- multi-day intervals ----

    def test_multi_day_full_workweek(self):
        """2.3.2.3: full consecutive workdays"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Mon 9am to Fri 5pm => 5 * 8 = 40h
        self.assertEqual(
            cal.get_work_hours_between(
                datetime(2026, 11, 23, 9, 0),
                datetime(2026, 11, 27, 17, 0),
            ),
            40,
        )

    def test_multi_day_partial_endpoints(self):
        """2.3.2.3: partial first day, full middle, partial last day"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Mon 10am to Wed 2pm => 7h (Mon) + 8h (Tue) + 5h (Wed) = 20h
        self.assertEqual(
            cal.get_work_hours_between(
                datetime(2026, 11, 23, 10, 0),
                datetime(2026, 11, 25, 14, 0),
            ),
            20,
        )

    def test_multi_day_spans_weekend(self):
        """2.3.2.3: interval spans a weekend (weekend hours excluded)"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Fri 10am to Mon 2pm => 7h (Fri) + 5h (Mon) = 12h
        self.assertEqual(
            cal.get_work_hours_between(
                datetime(2026, 11, 27, 10, 0),
                datetime(2026, 11, 30, 14, 0),
            ),
            12,
        )

    def test_multi_day_spans_holiday(self):
        """2.3.2.3: interval spans a weekday holiday (holiday hours excluded)"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [self.thanksgiving])
        # Wed 10am to Fri 2pm with Thanksgiving in between => 7h (Wed) + 0h (Thu) + 5h (Fri) = 12h
        self.assertEqual(
            cal.get_work_hours_between(
                datetime(2026, 11, 25, 10, 0),
                datetime(2026, 11, 27, 14, 0),
            ),
            12,
        )

    # ---- calendar shift ----

    def test_cal_shift_dyeing_facility(self):
        """2.3.2.4: non-zero cal_shift produces the correct duration"""
        cal = WorkCal([0, 1, 2, 3, 4], 0, 24, [], cal_shift=-1)
        # Real Sun 23:00 = calendar Mon 00:00; real Mon 23:00 = calendar Tue 00:00
        # One full calendar Monday on a 24-hour workday => 24h
        self.assertEqual(
            cal.get_work_hours_between(
                datetime(2026, 11, 22, 23, 0),
                datetime(2026, 11, 23, 23, 0),
            ),
            24,
        )


class AvailHoursBeforeWeekendTests(unittest.TestCase):
    """Covers section 2.3.3 of COVERAGE.md."""

    def setUp(self):
        self.christmas = FixedDate(name='Christmas', month=12, day=25)
        self.july4 = FixedDate(name='Independence Day', month=7, day=4)
        self.thanksgiving = FlexDate(name='Thanksgiving', month=11, weekday=3, n=4)
        self.mem_day = FlexDate(name='Memorial Day', month=5, weekday=0, n=-1)

    # ---- start mid-workday in business hours ----

    def test_in_business_early_week(self):
        """2.3.3.1: Monday morning on Mon-Fri 9-5 returns the full work week"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Mon 9am -> end-of-ISO-week = Mon Nov 30 00:00; 5 * 8 = 40h
        self.assertEqual(
            cal.avail_hours_before_weekend(datetime(2026, 11, 23, 9, 0)),
            40,
        )

    def test_in_business_late_week(self):
        """2.3.3.1: Friday afternoon returns only hours until Friday's day_end"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Fri 3pm -> 2h
        self.assertEqual(
            cal.avail_hours_before_weekend(datetime(2026, 11, 27, 15, 0)),
            2,
        )

    # ---- start in non-working time (no snap) ----

    def test_non_business_before_day_start_mon(self):
        """2.3.3.2: start before day_start on Monday returns full work week"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Mon 7am -> work week starts at 9am; 5 * 8 = 40h
        self.assertEqual(
            cal.avail_hours_before_weekend(datetime(2026, 11, 23, 7, 0)),
            40,
        )

    def test_non_business_after_day_end_mon(self):
        """2.3.3.2: start at/after day_end on Monday returns work week minus Monday"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        # Mon 6pm -> Tue + Wed + Thu + Fri = 4 * 8 = 32h
        self.assertEqual(
            cal.avail_hours_before_weekend(datetime(2026, 11, 23, 18, 0)),
            32,
        )

    def test_non_business_saturday(self):
        """2.3.3.2: start on Saturday on a Mon-Fri calendar returns 0"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        self.assertEqual(
            cal.avail_hours_before_weekend(datetime(2026, 11, 28, 12, 0)),
            0,
        )

    def test_non_business_sunday(self):
        """2.3.3.2: start on Sunday on a Mon-Fri calendar returns 0"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [])
        self.assertEqual(
            cal.avail_hours_before_weekend(datetime(2026, 11, 29, 12, 0)),
            0,
        )

    def test_non_business_weekday_holiday(self):
        """2.3.3.2: start on weekday holiday returns work-week hours from next workday onward"""
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [self.thanksgiving])
        # Thu Nov 26 10am (Thanksgiving) -> Fri only = 8h
        self.assertEqual(
            cal.avail_hours_before_weekend(datetime(2026, 11, 26, 10, 0)),
            8,
        )

    # ---- mid-week holiday excluded but does not truncate ----

    def test_mid_week_holiday_excluded(self):
        """2.3.3.3: mid-week holiday is excluded from the count but does not truncate"""
        # Fake Wednesday holiday on Nov 25, 2026
        wed_holiday = FixedDate(name='Fake Wed Holiday', month=11, day=25)
        cal = WorkCal([0, 1, 2, 3, 4], 9, 17, [wed_holiday])
        # Mon 9am -> Mon + Tue + [skip Wed] + Thu + Fri = 4 * 8 = 32h
        self.assertEqual(
            cal.avail_hours_before_weekend(datetime(2026, 11, 23, 9, 0)),
            32,
        )

    # ---- 24/7 calendar ----

    def test_24_7_calendar(self):
        """2.3.3.4: 24/7 calendar from Wed noon returns 4.5*24 = 108h"""
        cal = WorkCal([0, 1, 2, 3, 4, 5, 6], 0, 24, [])
        # Wed Nov 25 12pm -> next Mon Nov 30 00:00 = 4.5 days * 24h = 108h
        self.assertEqual(
            cal.avail_hours_before_weekend(datetime(2026, 11, 25, 12, 0)),
            108,
        )

    # ---- calendar shift ----

    def test_cal_shift_dyeing_facility(self):
        """2.3.3.5: cal_shift=-1, Sun 23:00 real returns full calendar work week"""
        cal = WorkCal([0, 1, 2, 3, 4], 0, 24, [], cal_shift=-1)
        # Real Sun 22 23:00 = calendar Mon 23 00:00; ISO week ends at calendar Mon 30 00:00
        # = real Sun 29 23:00. Workdays Mon-Fri * 24h = 120h.
        self.assertEqual(
            cal.avail_hours_before_weekend(datetime(2026, 11, 22, 23, 0)),
            120,
        )


if __name__ == '__main__':
    unittest.main()
