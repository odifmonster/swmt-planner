#!/usr/bin/env python

from datetime import date

from swmtplanner.support.workcal import *

def make_workcal():
    return WorkCal(
        work_days=(0, 1, 2, 3, 4),
        day_start=9,
        day_end=17,
        holidays=(
            FixedDate(month=1, day=1),
            FixedDate(month=12, day=25),
            FlexDate(month=11, weekday=3, n=4),
            # Fakes for clean 2025 alignment. None overlaps any other test range.
            #   Apr 5 2025 (Sat): weekend, gets filtered.
            #   Apr 7 2025 (Mon): non-weekend.
            #   Apr 12 2025 (Sat): weekend, shares ISO week 15 with Apr 7 so the
            #     work_days_in_week "non-weekend + weekend" case lands in one week.
            FixedDate(month=4, day=5),
            FixedDate(month=4, day=7),
            FixedDate(month=4, day=12),
        ),
    )

def ord_(y, m, d):
    return date(y, m, d).toordinal()

# ---- get_holiday_ordinals fixtures ----------------------------------------
# Each case is (label, forward_start, forward_end, expected_forward_result).
# A backward call covers the same conceptual [start, end) range using
# (end - 1, start - 1, direction=-1); the result should be reversed(expected).
GHO_CASES = [
    ('empty range',
     ord_(2025, 6, 15), ord_(2025, 6, 15), []),
    ('holiday-free range',
     ord_(2025, 3, 3), ord_(2025, 3, 14), []),
    ('only weekend holiday in range',
     ord_(2022, 12, 19), ord_(2023, 1, 2), []),
    ('single non-weekend holiday in range',
     ord_(2025, 12, 24), ord_(2026, 1, 1), [ord_(2025, 12, 25)]),
]

def _backward_args(fwd_start, fwd_end):
    """Translate a forward [start, end) into backward (start, end, direction=-1) args."""
    if fwd_start == fwd_end:
        return fwd_start, fwd_end
    return fwd_end - 1, fwd_start - 1

# ---- get_holiday_ordinals: first-call correctness -------------------------
def test_get_holiday_ordinals_forward():
    for label, start, end, expected in GHO_CASES:
        wc = make_workcal()
        result = wc.get_holiday_ordinals(start, end, direction=1)
        assert result == expected, \
            f'[{label}] forward: expected {expected!r}, got {result!r}'

def test_get_holiday_ordinals_backward():
    for label, fwd_start, fwd_end, fwd_expected in GHO_CASES:
        wc = make_workcal()
        bwd_start, bwd_end = _backward_args(fwd_start, fwd_end)
        result = wc.get_holiday_ordinals(bwd_start, bwd_end, direction=-1)
        expected = list(reversed(fwd_expected))
        assert result == expected, \
            f'[{label}] backward: expected {expected!r}, got {result!r}'

# ---- get_holiday_ordinals: cache hit on repeat call -----------------------
def test_get_holiday_ordinals_repeat_call_forward():
    for label, start, end, _ in GHO_CASES:
        wc = make_workcal()
        first = wc.get_holiday_ordinals(start, end, direction=1)
        second = wc.get_holiday_ordinals(start, end, direction=1)
        assert first == second, \
            f'[{label}] forward repeat: first={first!r}, second={second!r}'

def test_get_holiday_ordinals_repeat_call_backward():
    for label, fwd_start, fwd_end, _ in GHO_CASES:
        wc = make_workcal()
        start, end = _backward_args(fwd_start, fwd_end)
        first = wc.get_holiday_ordinals(start, end, direction=-1)
        second = wc.get_holiday_ordinals(start, end, direction=-1)
        assert first == second, \
            f'[{label}] backward repeat: first={first!r}, second={second!r}'

# ---- get_holiday_ordinals: third call inside a cache spanning seeds A & B
SEED_A_FWD = (ord_(2025, 1, 1), ord_(2026, 7, 1))
SEED_B_FWD = (ord_(2026, 7, 1), ord_(2027, 1, 1))

THIRD_CALL_CASES = [
    ('empty contained interval',
     ord_(2025, 5, 1), ord_(2025, 6, 1), []),
    ('single-holiday contained interval',
     ord_(2025, 4, 7), ord_(2025, 4, 8), [ord_(2025, 4, 7)]),
    ('weekend holiday excluded, non-weekend retained',
     ord_(2025, 4, 5), ord_(2025, 4, 8), [ord_(2025, 4, 7)]),
]

def test_get_holiday_ordinals_third_call_contained_forward():
    for label, start, end, expected in THIRD_CALL_CASES:
        wc = make_workcal()
        wc.get_holiday_ordinals(*SEED_A_FWD, direction=1)
        wc.get_holiday_ordinals(*SEED_B_FWD, direction=1)
        result = wc.get_holiday_ordinals(start, end, direction=1)
        assert result == expected, \
            f'[{label}] forward third: expected {expected!r}, got {result!r}'

def test_get_holiday_ordinals_third_call_contained_backward():
    seed_a_bwd = _backward_args(*SEED_A_FWD)
    seed_b_bwd = _backward_args(*SEED_B_FWD)
    for label, fwd_start, fwd_end, fwd_expected in THIRD_CALL_CASES:
        wc = make_workcal()
        wc.get_holiday_ordinals(*seed_a_bwd, direction=-1)
        wc.get_holiday_ordinals(*seed_b_bwd, direction=-1)
        bwd_start, bwd_end = _backward_args(fwd_start, fwd_end)
        result = wc.get_holiday_ordinals(bwd_start, bwd_end, direction=-1)
        expected = list(reversed(fwd_expected))
        assert result == expected, \
            f'[{label}] backward third: expected {expected!r}, got {result!r}'

# ---- work_days_in_week fixtures -------------------------------------------
# Each entry encodes a week and its expected work-day-ordinal tuples for the
# four direction/bound combinations. Bound is a Wednesday: forward keeps Wed
# onward, backward keeps Wed and earlier.
WDIW_CASES = [
    {
        'label': 'no holidays (week 28 2025)',
        'iso': date(2025, 7, 7).isocalendar(),
        'forward_unbounded': (ord_(2025, 7, 7), ord_(2025, 7, 8), ord_(2025, 7, 9),
                              ord_(2025, 7, 10), ord_(2025, 7, 11)),
        'backward_unbounded': (ord_(2025, 7, 11), ord_(2025, 7, 10), ord_(2025, 7, 9),
                               ord_(2025, 7, 8), ord_(2025, 7, 7)),
        'bound': ord_(2025, 7, 9),
        'forward_bounded': (ord_(2025, 7, 9), ord_(2025, 7, 10), ord_(2025, 7, 11)),
        'backward_bounded': (ord_(2025, 7, 9), ord_(2025, 7, 8), ord_(2025, 7, 7)),
    },
    {
        'label': '1 non-weekend holiday (week 48 2025, Thanksgiving)',
        'iso': date(2025, 11, 27).isocalendar(),
        'forward_unbounded': (ord_(2025, 11, 24), ord_(2025, 11, 25),
                              ord_(2025, 11, 26), ord_(2025, 11, 28)),
        'backward_unbounded': (ord_(2025, 11, 28), ord_(2025, 11, 26),
                               ord_(2025, 11, 25), ord_(2025, 11, 24)),
        'bound': ord_(2025, 11, 26),
        'forward_bounded': (ord_(2025, 11, 26), ord_(2025, 11, 28)),
        'backward_bounded': (ord_(2025, 11, 26), ord_(2025, 11, 25), ord_(2025, 11, 24)),
    },
    {
        'label': '1 weekend holiday (week 14 2025, Apr 5 Sat)',
        'iso': date(2025, 4, 5).isocalendar(),
        'forward_unbounded': (ord_(2025, 3, 31), ord_(2025, 4, 1), ord_(2025, 4, 2),
                              ord_(2025, 4, 3), ord_(2025, 4, 4)),
        'backward_unbounded': (ord_(2025, 4, 4), ord_(2025, 4, 3), ord_(2025, 4, 2),
                               ord_(2025, 4, 1), ord_(2025, 3, 31)),
        'bound': ord_(2025, 4, 2),
        'forward_bounded': (ord_(2025, 4, 2), ord_(2025, 4, 3), ord_(2025, 4, 4)),
        'backward_bounded': (ord_(2025, 4, 2), ord_(2025, 4, 1), ord_(2025, 3, 31)),
    },
    {
        'label': '1 non-weekend + 1 weekend (week 15 2025, Apr 7 Mon + Apr 12 Sat)',
        'iso': date(2025, 4, 7).isocalendar(),
        'forward_unbounded': (ord_(2025, 4, 8), ord_(2025, 4, 9),
                              ord_(2025, 4, 10), ord_(2025, 4, 11)),
        'backward_unbounded': (ord_(2025, 4, 11), ord_(2025, 4, 10),
                               ord_(2025, 4, 9), ord_(2025, 4, 8)),
        'bound': ord_(2025, 4, 9),
        'forward_bounded': (ord_(2025, 4, 9), ord_(2025, 4, 10), ord_(2025, 4, 11)),
        'backward_bounded': (ord_(2025, 4, 9), ord_(2025, 4, 8)),
    },
]

def test_work_days_in_week_forward_unbounded():
    for case in WDIW_CASES:
        wc = make_workcal()
        iso = case['iso']
        result = wc.work_days_in_week(iso.year, iso.week, direction=1)
        assert result == case['forward_unbounded'], \
            f'[{case["label"]}] forward unbounded: ' \
            f'expected {case["forward_unbounded"]!r}, got {result!r}'

def test_work_days_in_week_forward_bounded():
    for case in WDIW_CASES:
        wc = make_workcal()
        iso = case['iso']
        result = wc.work_days_in_week(iso.year, iso.week,
                                      bound=case['bound'], direction=1)
        assert result == case['forward_bounded'], \
            f'[{case["label"]}] forward bounded: ' \
            f'expected {case["forward_bounded"]!r}, got {result!r}'

def test_work_days_in_week_backward_unbounded():
    for case in WDIW_CASES:
        wc = make_workcal()
        iso = case['iso']
        result = wc.work_days_in_week(iso.year, iso.week, direction=-1)
        assert result == case['backward_unbounded'], \
            f'[{case["label"]}] backward unbounded: ' \
            f'expected {case["backward_unbounded"]!r}, got {result!r}'

def test_work_days_in_week_backward_bounded():
    for case in WDIW_CASES:
        wc = make_workcal()
        iso = case['iso']
        result = wc.work_days_in_week(iso.year, iso.week,
                                      bound=case['bound'], direction=-1)
        assert result == case['backward_bounded'], \
            f'[{case["label"]}] backward bounded: ' \
            f'expected {case["backward_bounded"]!r}, got {result!r}'

# ---- snap_to_work_date fixtures -------------------------------------------
# Each entry is (label, input_date, expected_forward, expected_backward).
# Picked to exercise both single-day and multi-day snaps in each direction.
SNAP_CASES = [
    # Already a work day — both directions return it unchanged.
    ('work day no change',
     date(2025, 7, 9),       # Wed
     date(2025, 7, 9),
     date(2025, 7, 9)),

    # Saturday: forward needs 2 days (skip Sun) to Mon; backward needs 1 day to Fri.
    ('Saturday',
     date(2025, 7, 12),      # Sat
     date(2025, 7, 14),      # Mon (forward, +2)
     date(2025, 7, 11)),     # Fri (backward, -1)

    # Sunday: forward needs 1 day to Mon; backward needs 2 days (skip Sat) to Fri.
    ('Sunday',
     date(2025, 7, 13),      # Sun
     date(2025, 7, 14),      # Mon (forward, +1)
     date(2025, 7, 11)),     # Fri (backward, -2)

    # Thanksgiving Thursday — single-day snap in both directions.
    ('non-weekend holiday (Thanksgiving 2025)',
     date(2025, 11, 27),     # Thu, holiday
     date(2025, 11, 28),     # Fri (forward, +1)
     date(2025, 11, 26)),    # Wed (backward, -1)

    # Christmas 2026 falls on a Friday — forward must skip Sat+Sun to land on
    # Mon Dec 28 (+3 days); backward only steps to Thu Dec 24 (-1 day).
    ('non-weekend holiday before weekend (Fri Christmas 2026)',
     date(2026, 12, 25),     # Fri, holiday
     date(2026, 12, 28),     # Mon (forward, +3)
     date(2026, 12, 24)),    # Thu (backward, -1)

    # New Year's Day 2024 falls on a Monday — backward must skip Sun+Sat to land
    # on Fri Dec 29 2023 (-3 days); forward only steps to Tue Jan 2 (+1 day).
    ('non-weekend holiday after weekend (Mon Jan 1 2024)',
     date(2024, 1, 1),       # Mon, holiday
     date(2024, 1, 2),       # Tue (forward, +1)
     date(2023, 12, 29)),    # Fri (backward, -3)
]

def test_snap_to_work_date():
    for label, d, expected_fwd, expected_bwd in SNAP_CASES:
        # Reuse the same WorkCal for forward then backward to confirm that
        # cache extension built up by the forward walk does not corrupt the
        # backward walk that follows.
        wc = make_workcal()
        result_fwd = wc.snap_to_work_date(d, direction=1)
        assert result_fwd == expected_fwd, \
            f'[{label}] forward snap of {d}: expected {expected_fwd}, got {result_fwd}'
        result_bwd = wc.snap_to_work_date(d, direction=-1)
        assert result_bwd == expected_bwd, \
            f'[{label}] backward snap of {d} (after forward call): ' \
            f'expected {expected_bwd}, got {result_bwd}'

# ---- offset_work_days fixtures --------------------------------------------
# Each entry is (label, start_date, days, expected_date).
OFFSET_CASES = [
    # ---- Intervals containing only work days ------------------------------
    ('zero on a work day', date(2025, 7, 9), 0, date(2025, 7, 9)),
    ('+1 within work week (Tue to Wed)',
     date(2025, 7, 8), 1, date(2025, 7, 9)),
    ('+4 within work week (Mon to Fri)',
     date(2025, 7, 7), 4, date(2025, 7, 11)),
    ('-1 within work week (Wed to Tue)',
     date(2025, 7, 9), -1, date(2025, 7, 8)),
    ('-4 within work week (Fri to Mon)',
     date(2025, 7, 11), -4, date(2025, 7, 7)),

    # ---- Intervals crossing weekends --------------------------------------
    ('zero on Saturday snaps forward to Mon',
     date(2025, 7, 12), 0, date(2025, 7, 14)),
    ('zero on Sunday snaps forward to Mon',
     date(2025, 7, 13), 0, date(2025, 7, 14)),
    ('+1 Fri to Mon (skip Sat+Sun)',
     date(2025, 7, 11), 1, date(2025, 7, 14)),
    ('+5 Mon to next Mon (one full work week)',
     date(2025, 7, 7), 5, date(2025, 7, 14)),
    ('-1 Mon to Fri (skip Sun+Sat)',
     date(2025, 7, 14), -1, date(2025, 7, 11)),
    ('-5 Mon to prev Mon',
     date(2025, 7, 14), -5, date(2025, 7, 7)),

    # ---- Intervals crossing a non-weekend holiday -------------------------
    ('+1 Wed to Fri across Thanksgiving 2025',
     date(2025, 11, 26), 1, date(2025, 11, 28)),
    ('-1 Fri to Wed across Thanksgiving 2025',
     date(2025, 11, 28), -1, date(2025, 11, 26)),

    # ---- Intervals crossing weekend AND holiday ---------------------------
    # Christmas 2026 falls on a Friday; +1 from Thu must skip Fri-Sat-Sun.
    ('+1 Thu to Mon across Fri Christmas 2026 + weekend',
     date(2026, 12, 24), 1, date(2026, 12, 28)),
    ('-1 Mon to Thu across weekend + Fri Christmas 2026',
     date(2026, 12, 28), -1, date(2026, 12, 24)),

    # ---- Non-zero offsets starting on a non-work day ----------------------
    # Saturday +1: snap forward to Mon, then +1 work day = Tue.
    ('+1 starting on Saturday (snap then step)',
     date(2025, 7, 12), 1, date(2025, 7, 15)),
    # Sunday -1: snap backward to Fri, then -1 work day = Thu.
    ('-1 starting on Sunday (snap then step)',
     date(2025, 7, 13), -1, date(2025, 7, 10)),
    # Thanksgiving Thu +1: snap forward to Fri, then +1 = Mon Dec 1.
    ('+1 starting on Thanksgiving (snap then step across weekend)',
     date(2025, 11, 27), 1, date(2025, 12, 1)),
    # Thanksgiving Thu -1: snap backward to Wed, then -1 = Tue.
    ('-1 starting on Thanksgiving (snap then step)',
     date(2025, 11, 27), -1, date(2025, 11, 25)),
]

def test_offset_work_days():
    for label, start, days, expected in OFFSET_CASES:
        wc = make_workcal()
        result = wc.offset_work_days(start, days)
        assert result == expected, \
            f'[{label}] offset_work_days({start}, {days}): expected {expected}, got {result}'

# ---- offset_work_hours fixtures -------------------------------------------
# WorkCal hours per day = 17 - 9 = 8. Each entry is
# (label, start_datetime, hours, expected_datetime).
from datetime import datetime
OFFSET_HOURS_CASES = [
    # ---- Within a single work day, no snapping needed ------------------
    ('0h mid-day on a work day',
     datetime(2025, 7, 9, 10, 30), 0.0, datetime(2025, 7, 9, 10, 30)),
    ('+1.5h within a work day',
     datetime(2025, 7, 9, 10, 0), 1.5, datetime(2025, 7, 9, 11, 30)),
    ('-1.5h within a work day',
     datetime(2025, 7, 9, 11, 30), -1.5, datetime(2025, 7, 9, 10, 0)),

    # ---- Zero hours snap forward when not in working hours -------------
    ('0h before day_start clamps to 9:00 same day',
     datetime(2025, 7, 9, 7, 0), 0.0, datetime(2025, 7, 9, 9, 0)),
    ('0h after day_end rolls to 9:00 next work day',
     datetime(2025, 7, 9, 18, 0), 0.0, datetime(2025, 7, 10, 9, 0)),
    ('0h on Saturday snaps to Mon 9:00',
     datetime(2025, 7, 12, 10, 0), 0.0, datetime(2025, 7, 14, 9, 0)),
    ('0h on Thanksgiving Thu snaps to Fri 9:00',
     datetime(2025, 11, 27, 10, 0), 0.0, datetime(2025, 11, 28, 9, 0)),

    # ---- Crossing a day boundary --------------------------------------
    # +5h from Wed 14:00: 14→17 (3h), then 9→11 Thu (2h).
    ('+5h crosses single day boundary',
     datetime(2025, 7, 9, 14, 0), 5.0, datetime(2025, 7, 10, 11, 0)),
    # +1h from Wed 16:30: 16:30→17:00 (0.5h), then 9:00→9:30 Thu (0.5h).
    ('+1h crosses day boundary at end of day',
     datetime(2025, 7, 9, 16, 30), 1.0, datetime(2025, 7, 10, 9, 30)),
    # -1h from Wed 9:30: 9:30→9:00 (0.5h), then 17:00→16:30 Tue (0.5h).
    ('-1h crosses day boundary at start of day',
     datetime(2025, 7, 9, 9, 30), -1.0, datetime(2025, 7, 8, 16, 30)),

    # ---- Crossing a weekend -------------------------------------------
    ('+1h crosses weekend (Fri 16:30 -> Mon 9:30)',
     datetime(2025, 7, 11, 16, 30), 1.0, datetime(2025, 7, 14, 9, 30)),
    ('-1h crosses weekend (Mon 9:30 -> Fri 16:30)',
     datetime(2025, 7, 14, 9, 30), -1.0, datetime(2025, 7, 11, 16, 30)),

    # ---- Crossing a non-weekend holiday -------------------------------
    # +2h from Wed Nov 26 16:00: 16→17 (1h), skip Thanksgiving Thu, 9→10 Fri (1h).
    ('+2h crosses Thanksgiving 2025',
     datetime(2025, 11, 26, 16, 0), 2.0, datetime(2025, 11, 28, 10, 0)),
    # -2h from Fri Nov 28 10:00: 10→9 (1h), skip Thanksgiving Thu, 17→16 Wed (1h).
    ('-2h crosses Thanksgiving 2025',
     datetime(2025, 11, 28, 10, 0), -2.0, datetime(2025, 11, 26, 16, 0)),

    # ---- Crossing weekend AND holiday (Fri Christmas 2026) ------------
    # +2h from Thu Dec 24 2026 16:00: 16→17 (1h), skip Fri Christmas + Sat + Sun,
    # 9→10 Mon Dec 28 (1h).
    ('+2h crosses Christmas 2026 + weekend',
     datetime(2026, 12, 24, 16, 0), 2.0, datetime(2026, 12, 28, 10, 0)),
    # -2h from Mon Dec 28 2026 10:00: 10→9 (1h), skip Sun + Sat + Fri Christmas,
    # 17→16 Thu Dec 24 (1h).
    ('-2h crosses weekend + Christmas 2026',
     datetime(2026, 12, 28, 10, 0), -2.0, datetime(2026, 12, 24, 16, 0)),

    # ---- Non-zero hours starting on a non-work moment -----------------
    # Sat 10:00 +1h: snap forward to Mon 9:00, then +1h = Mon 10:00.
    ('+1h starting on Saturday (snap then step)',
     datetime(2025, 7, 12, 10, 0), 1.0, datetime(2025, 7, 14, 10, 0)),
    # Sun 14:00 -1h: snap backward to Fri 17:00, then -1h = Fri 16:00.
    ('-1h starting on Sunday (snap then step)',
     datetime(2025, 7, 13, 14, 0), -1.0, datetime(2025, 7, 11, 16, 0)),

    # ---- Multi-day spans ----------------------------------------------
    # +8h = exactly one full work day.
    ('+8h fills a full work day',
     datetime(2025, 7, 9, 9, 0), 8.0, datetime(2025, 7, 9, 17, 0)),
    # +9h = full day + 1h on the next.
    ('+9h spans full day + 1h',
     datetime(2025, 7, 9, 9, 0), 9.0, datetime(2025, 7, 10, 10, 0)),
    # +16h = two full work days.
    ('+16h spans two full days',
     datetime(2025, 7, 9, 9, 0), 16.0, datetime(2025, 7, 10, 17, 0)),
    # -8h = one full work day backward.
    ('-8h covers a full work day backward',
     datetime(2025, 7, 9, 17, 0), -8.0, datetime(2025, 7, 9, 9, 0)),
]

def test_offset_work_hours():
    for label, start, hours, expected in OFFSET_HOURS_CASES:
        wc = make_workcal()
        result = wc.offset_work_hours(start, hours)
        assert result == expected, \
            f'[{label}] offset_work_hours({start}, {hours}): ' \
            f'expected {expected}, got {result}'

def main():
    test_snap_to_work_date()
    print('All snap_to_work_date cases passed.')
    test_offset_work_days()
    print('All offset_work_days cases passed.')
    test_offset_work_hours()
    print('All offset_work_hours cases passed.')

if __name__ == '__main__':
    main()
