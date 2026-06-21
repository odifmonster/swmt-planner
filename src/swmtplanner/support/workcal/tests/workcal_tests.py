#!/usr/bin/env python

import unittest
from datetime import date, datetime

from swmtplanner.support.workcal import WorkCal, FixedDate, FlexDate

# Reference week: 2026-06-15 is a Monday.
#   Mon 06-15, Tue 06-16, Wed 06-17, Thu 06-18, Fri 06-19, Sat 06-20, Sun 06-21
# Holidays used as ground truth (US):
#   Christmas    2026-12-25 (Friday)   - non-weekend FixedDate
#   Thanksgiving 2026-11-26 (Thursday) - non-weekend FlexDate (4th Thu of Nov)
#   July 4th     2026-07-04 (Saturday) - weekend FixedDate
#   1st Sat Aug  2026-08-01 (Saturday) - weekend FlexDate
XMAS = FixedDate(name='Christmas', month=12, day=25)
THANKSGIVING = FlexDate(name='Thanksgiving', month=11, weekday=3, n=4)
JULY4 = FixedDate(name='Independence Day', month=7, day=4)
FIRST_SAT_AUG = FlexDate(name='First Saturday', month=8, weekday=5, n=1)

WEEKDAYS = [0, 1, 2, 3, 4]
ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]


class TestConstruction(unittest.TestCase):

    def test_construction(self):
        """2.1.1 — constructs correctly; computed properties behave as
        expected."""
        cal = WorkCal(WEEKDAYS, 7, 15, [XMAS])
        self.assertEqual(cal.weekdays, (0, 1, 2, 3, 4))
        self.assertEqual(cal.day_start, 7)
        self.assertEqual(cal.day_end, 15)
        self.assertEqual(cal.holidays, (XMAS,))
        self.assertEqual(cal.cal_shift, 0)
        self.assertEqual(cal.work_days_per_week, 5)
        self.assertEqual(cal.work_hours_per_day, 8)


class TestIsWorkday(unittest.TestCase):

    def test_weekendless_calendar(self):
        """2.2.1 — every weekday works: False on fixed and flex holidays, True
        otherwise (incl. what would be a weekend)."""
        cal = WorkCal(ALL_DAYS, 7, 15, [XMAS, THANKSGIVING])
        self.assertFalse(cal.is_workday(date(2026, 12, 25)))   # fixed holiday
        self.assertFalse(cal.is_workday(date(2026, 11, 26)))   # flex holiday
        self.assertTrue(cal.is_workday(date(2026, 12, 24)))    # ordinary day
        self.assertTrue(cal.is_workday(date(2026, 6, 21)))     # Sunday, no weekend

    def test_calendar_with_weekend(self):
        """2.2.2 — False on weekend holidays, plain weekends, and non-weekend
        holidays; True otherwise."""
        cal = WorkCal(WEEKDAYS, 7, 15, [JULY4, FIRST_SAT_AUG, XMAS, THANKSGIVING])
        # 2.2.2.1 fixed and flex holidays that fall on weekends
        self.assertFalse(cal.is_workday(date(2026, 7, 4)))     # Sat, fixed
        self.assertFalse(cal.is_workday(date(2026, 8, 1)))     # Sat, flex
        # 2.2.2.2 weekend days with no holiday
        self.assertFalse(cal.is_workday(date(2026, 6, 20)))    # Sat
        self.assertFalse(cal.is_workday(date(2026, 6, 21)))    # Sun
        # 2.2.2.3 non-weekend fixed and flex holidays
        self.assertFalse(cal.is_workday(date(2026, 12, 25)))   # Fri, fixed
        self.assertFalse(cal.is_workday(date(2026, 11, 26)))   # Thu, flex
        # True otherwise
        self.assertTrue(cal.is_workday(date(2026, 6, 17)))     # Wed

    def test_calendar_with_weekend_no_holidays(self):
        """2.2.3 — False on weekend days, True otherwise."""
        cal = WorkCal(WEEKDAYS, 7, 15, [])
        self.assertFalse(cal.is_workday(date(2026, 6, 20)))    # Sat
        self.assertFalse(cal.is_workday(date(2026, 6, 21)))    # Sun
        self.assertTrue(cal.is_workday(date(2026, 6, 17)))     # Wed


class TestOffsetWorkDays(unittest.TestCase):

    def setUp(self):
        self.cal = WorkCal(WEEKDAYS, 7, 15, [])
        self.cal_hol = WorkCal(
            WEEKDAYS, 7, 15, [XMAS, THANKSGIVING, JULY4, FIRST_SAT_AUG])

    def test_snap_forward_on_zero_from_nonworkday(self):
        """2.3.1 — days=0 from a non-workday snaps forward."""
        self.assertEqual(
            self.cal.offset_work_days(date(2026, 6, 20), 0), date(2026, 6, 22))

    def test_noop_on_zero_from_workday(self):
        """2.3.2 — days=0 from a workday returns the same day."""
        self.assertEqual(
            self.cal.offset_work_days(date(2026, 6, 17), 0), date(2026, 6, 17))

    def test_snap_backward_on_negative_from_nonworkday(self):
        """2.3.3 — negative days from a non-workday snaps backward before
        offsetting (Sat -1 -> snap to Fri -> Thu)."""
        self.assertEqual(
            self.cal.offset_work_days(date(2026, 6, 20), -1), date(2026, 6, 18))

    def test_forward_correctness(self):
        """2.3.4 — forward traversal across weekends and holidays (fixed and
        flex, weekend and non-weekend)."""
        # cross a weekend
        self.assertEqual(
            self.cal.offset_work_days(date(2026, 6, 19), 1), date(2026, 6, 22))
        # cross a non-weekend flex holiday (Thanksgiving Thu 11-26)
        self.assertEqual(
            self.cal_hol.offset_work_days(date(2026, 11, 25), 1),
            date(2026, 11, 27))
        # cross a non-weekend fixed holiday + weekend (Christmas Fri 12-25)
        self.assertEqual(
            self.cal_hol.offset_work_days(date(2026, 12, 24), 1),
            date(2026, 12, 28))
        # weekend holiday (July 4 Sat) does not perturb the weekend skip
        self.assertEqual(
            self.cal_hol.offset_work_days(date(2026, 7, 3), 1), date(2026, 7, 6))

    def test_backward_correctness(self):
        """2.3.4 — backward traversal across weekends and holidays."""
        # cross a weekend
        self.assertEqual(
            self.cal.offset_work_days(date(2026, 6, 22), -1), date(2026, 6, 19))
        # cross a non-weekend flex holiday (Thanksgiving)
        self.assertEqual(
            self.cal_hol.offset_work_days(date(2026, 11, 27), -1),
            date(2026, 11, 25))
        # cross a fixed holiday + weekend (Christmas)
        self.assertEqual(
            self.cal_hol.offset_work_days(date(2026, 12, 28), -1),
            date(2026, 12, 24))


class TestOffsetWorkHours(unittest.TestCase):

    def setUp(self):
        self.cal = WorkCal(WEEKDAYS, 7, 15, [])
        self.cal_hol = WorkCal(WEEKDAYS, 7, 15, [THANKSGIVING])
        self.cal_shift = WorkCal(WEEKDAYS, 0, 24, [], cal_shift=-1)

    def test_zero_outside_hours_snaps_forward(self):
        """2.4.1.1 — hours=0 outside working hours snaps forward."""
        self.assertEqual(
            self.cal.offset_work_hours(datetime(2026, 6, 17, 5, 0), 0),
            datetime(2026, 6, 17, 7, 0))

    def test_zero_within_hours_is_noop(self):
        """2.4.1.2 — hours=0 within working hours returns the same instant."""
        self.assertEqual(
            self.cal.offset_work_hours(datetime(2026, 6, 17, 9, 0), 0),
            datetime(2026, 6, 17, 9, 0))

    def test_negative_outside_hours_snaps_backward(self):
        """2.4.1.3 — negative hours outside working hours snaps backward before
        offsetting (Wed 20:00 -1 -> snap to 15:00 -> 14:00)."""
        self.assertEqual(
            self.cal.offset_work_hours(datetime(2026, 6, 17, 20, 0), -1),
            datetime(2026, 6, 17, 14, 0))

    def test_shift_snap_forward_into_day_starting_prev_11pm(self):
        """2.4.1.4 — with cal_shift=-1, Monday's day starts at real Sun 23:00;
        snapping forward from the weekend lands relative to that 11pm start
        (Sun 21:00 +1h -> Mon 00:00)."""
        self.assertEqual(
            self.cal_shift.offset_work_hours(datetime(2026, 6, 21, 21, 0), 1),
            datetime(2026, 6, 22, 0, 0))

    def test_shift_snap_backward_into_day_ending_11pm(self):
        """2.4.1.4 — with cal_shift=-1, Friday's day ends at real Fri 23:00;
        snapping backward lands relative to that 11pm end (Fri 23:30 -1h ->
        Fri 22:00)."""
        self.assertEqual(
            self.cal_shift.offset_work_hours(datetime(2026, 6, 19, 23, 30), -1),
            datetime(2026, 6, 19, 22, 0))

    def test_non24_within_day_forward(self):
        """2.4.2 — within a working day, forward."""
        self.assertEqual(
            self.cal.offset_work_hours(datetime(2026, 6, 17, 8, 0), 4),
            datetime(2026, 6, 17, 12, 0))

    def test_non24_within_day_backward(self):
        """2.4.2 — within a working day, backward."""
        self.assertEqual(
            self.cal.offset_work_hours(datetime(2026, 6, 17, 12, 0), -4),
            datetime(2026, 6, 17, 8, 0))

    def test_non24_outside_day_forward(self):
        """2.4.2 — outside a working day, forward (snap up to start)."""
        self.assertEqual(
            self.cal.offset_work_hours(datetime(2026, 6, 17, 5, 0), 2),
            datetime(2026, 6, 17, 9, 0))

    def test_non24_outside_day_backward(self):
        """2.4.2 — outside a working day, backward (snap back to end)."""
        self.assertEqual(
            self.cal.offset_work_hours(datetime(2026, 6, 17, 20, 0), -2),
            datetime(2026, 6, 17, 13, 0))

    def test_skips_weekend(self):
        """2.4.3 — offsetting rolls across a weekend (Fri 13:00 +4h -> Mon
        09:00)."""
        self.assertEqual(
            self.cal.offset_work_hours(datetime(2026, 6, 19, 13, 0), 4),
            datetime(2026, 6, 22, 9, 0))

    def test_skips_holiday(self):
        """2.4.3 — offsetting rolls across a holiday (Wed before Thanksgiving
        13:00 +4h -> Fri 09:00)."""
        self.assertEqual(
            self.cal_hol.offset_work_hours(datetime(2026, 11, 25, 13, 0), 4),
            datetime(2026, 11, 27, 9, 0))


class TestGetWorkHoursBetween(unittest.TestCase):

    def setUp(self):
        self.cal = WorkCal(WEEKDAYS, 7, 15, [])
        self.cal_hol = WorkCal(WEEKDAYS, 7, 15, [THANKSGIVING])
        self.cal_24 = WorkCal(ALL_DAYS, 0, 24, [])
        self.cal_shift = WorkCal(ALL_DAYS, 0, 24, [XMAS], cal_shift=-4)

    def test_start_and_end_outside_hours(self):
        """2.5.1 — both endpoints outside working hours (covers the full work
        window)."""
        self.assertEqual(
            self.cal.get_work_hours_between(
                datetime(2026, 6, 17, 5, 0), datetime(2026, 6, 17, 20, 0)),
            8.0)

    def test_interval_spans_weekend(self):
        """2.5.2 — interval spanning a weekend (Fri 10:00 -> Mon 10:00)."""
        self.assertEqual(
            self.cal.get_work_hours_between(
                datetime(2026, 6, 19, 10, 0), datetime(2026, 6, 22, 10, 0)),
            8.0)

    def test_interval_spans_holiday(self):
        """2.5.3 — interval spanning a holiday (Wed -> Sat across Thanksgiving:
        Wed 8h + Thu 0 + Fri 8h)."""
        self.assertEqual(
            self.cal_hol.get_work_hours_between(
                datetime(2026, 11, 25, 0, 0), datetime(2026, 11, 28, 0, 0)),
            16.0)

    def test_only_nonworking_hours(self):
        """2.5.4 — an interval of only non-working hours returns 0."""
        self.assertEqual(
            self.cal.get_work_hours_between(
                datetime(2026, 6, 17, 15, 0), datetime(2026, 6, 17, 20, 0)),
            0.0)

    def test_within_working_hours_equals_subtraction(self):
        """2.5.5 — interval entirely within working hours equals plain
        subtraction."""
        start = datetime(2026, 6, 17, 8, 0)
        end = datetime(2026, 6, 17, 14, 0)
        self.assertEqual(
            self.cal.get_work_hours_between(start, end),
            (end - start).total_seconds() / 3600)

    def test_24h_no_weekend_no_holiday_equals_subtraction(self):
        """2.5.6 — 24-hour, no-weekend, no-holiday calendar equals plain
        subtraction."""
        start = datetime(2026, 6, 15, 8, 0)
        end = datetime(2026, 6, 17, 20, 0)
        self.assertEqual(
            self.cal_24.get_work_hours_between(start, end),
            (end - start).total_seconds() / 3600)

    def test_start_after_end(self):
        """2.5.7 — start >= end returns 0."""
        self.assertEqual(
            self.cal.get_work_hours_between(
                datetime(2026, 6, 17, 12, 0), datetime(2026, 6, 17, 8, 0)),
            0.0)
        self.assertEqual(
            self.cal.get_work_hours_between(
                datetime(2026, 6, 17, 8, 0), datetime(2026, 6, 17, 8, 0)),
            0.0)

    def test_calendar_shift(self):
        """2.5.8 — cal_shift=-4: the Christmas holiday begins at real Dec 24
        20:00, so an interval Dec 24 18:00 -> 22:00 counts only 18:00-20:00."""
        self.assertEqual(
            self.cal_shift.get_work_hours_between(
                datetime(2026, 12, 24, 18, 0), datetime(2026, 12, 24, 22, 0)),
            2.0)


class TestAvailHoursBeforeWeekend(unittest.TestCase):

    def setUp(self):
        self.cal = WorkCal(WEEKDAYS, 7, 15, [])

    def test_start_inside_weekend(self):
        """2.6.1 — a start inside the weekend returns 0."""
        self.assertEqual(
            self.cal.avail_hours_before_weekend(datetime(2026, 6, 20, 10, 0)),
            0.0)
        self.assertEqual(
            self.cal.avail_hours_before_weekend(datetime(2026, 6, 21, 10, 0)),
            0.0)

    def test_start_before_weekend(self):
        """2.6.2 — a start before the weekend computes the remaining working
        hours (Wed 13:00 -> Wed 2h + Thu 8h + Fri 8h = 18h)."""
        self.assertEqual(
            self.cal.avail_hours_before_weekend(datetime(2026, 6, 17, 13, 0)),
            18.0)


if __name__ == '__main__':
    unittest.main()
