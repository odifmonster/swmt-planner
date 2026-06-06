#!/usr/bin/env python

import unittest
from datetime import datetime, timedelta

from swmtplanner.products import Greige, BeamSet
from swmtplanner.schedule import (
    Machine, Knit, Job, Roll, Waste, TapeOut, BeamLoad, StyleChange, Idle,
    TAPE_OUT_SINGLE_DURATION, TAPE_OUT_BOTH_DURATION,
)
from swmtplanner.support import WorkCal


# --- Fixtures -----------------------------------------------------------

# 24/7 workcal so most tests can do plain clock-time arithmetic. The
# weekday workcal is reserved for the workcal-offset test in 1.5.
_24_7 = WorkCal(work_days=(0, 1, 2, 3, 4, 5, 6),
                day_start=0, day_end=24, holidays=())
_WEEKDAY_9H = WorkCal(work_days=(0, 1, 2, 3, 4),
                      day_start=8, day_end=17, holidays=())

# Synthetic greiges chosen so all status arithmetic is exact under floats.
# Item A: family A, rate 100 lbs/h on M1, top_pct=0.4 / btm_pct=0.6.
_ITEM_A = Greige(
    'AU0001', family='A', tgt_wt=100.0,
    top_beam='40D BLACK 1000X4', top_pct=0.4,
    btm_beam='60D WHITE 1000X4', btm_pct=0.6,
    safety=1000.0, machines={'M1': 100.0},
)
# Item B: same family, same yarn as A; used for StyleChange tests where we
# want current_item to change but everything else to stay put.
_ITEM_B = Greige(
    'AU0002', family='A', tgt_wt=200.0,
    top_beam='40D BLACK 1000X4', top_pct=0.5,
    btm_beam='60D WHITE 1000X4', btm_pct=0.5,
    safety=1500.0, machines={'M1': 100.0},
)
# Item C: different family with same yarn IDs (so Phase 1 status tests can
# apply StyleChange to it without an inconsistent beam state). Different
# pcts and rate so next_runout math is visibly different from A's.
_ITEM_C = Greige(
    'AU0003', family='C', tgt_wt=150.0,
    top_beam='40D BLACK 1000X4', top_pct=0.2,
    btm_beam='60D WHITE 1000X4', btm_pct=0.8,
    safety=900.0, machines={'M1': 50.0},
)

_TOP_BEAM = BeamSet('40D BLACK 1000X4')
_BTM_BEAM = BeamSet('60D WHITE 1000X4')
_ALT_TOP_BEAM = BeamSet('30D RED 1000X4')
_ALT_BTM_BEAM = BeamSet('90D GREEN 1000X4')

# 2026-05-18 is a Monday — keeps the weekday-workcal test simple.
_START = datetime(2026, 5, 18, 9, 0)


_SIMPLE_CHANGE = timedelta(minutes=15)
_FAMILY_CHANGE = timedelta(hours=1)


def _make_machine(
    init_item=_ITEM_A,
    init_top_lbs=200.0,
    init_btm_lbs=300.0,
    workcal=_24_7,
    start=_START,
    init_top_beam=_TOP_BEAM,
    init_btm_beam=_BTM_BEAM,
    simple_change_duration=_SIMPLE_CHANGE,
    family_change_duration=_FAMILY_CHANGE,
    is_new=False,
) -> Machine:
    return Machine(
        id='M1',
        init_item=init_item,
        start=start,
        init_top_beam=init_top_beam,
        init_top_lbs=init_top_lbs,
        init_btm_beam=init_btm_beam,
        init_btm_lbs=init_btm_lbs,
        workcal=workcal,
        simple_change_duration=simple_change_duration,
        family_change_duration=family_change_duration,
        is_new=is_new,
    )


# ---------------------------- PHASE 1 -----------------------------------

# --- 1.1 Construction and initial state ---------------------------------

class MachineConstructionTests(unittest.TestCase):

    def test_id_and_prefix(self):
        m = _make_machine()
        self.assertEqual(m.id, 'M1')
        self.assertEqual(m.prefix, 'Machine')

    def test_initial_status_fields(self):
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        s = m.initial_status
        self.assertEqual(s.as_of, _START)
        self.assertEqual(s.top_beam, _TOP_BEAM)
        self.assertEqual(s.btm_beam, _BTM_BEAM)
        self.assertEqual(s.top_lbs_remaining, 200.0)
        self.assertEqual(s.btm_lbs_remaining, 300.0)
        self.assertEqual(s.current_item, _ITEM_A)
        self.assertTrue(s.is_idle)
        self.assertEqual(s.current_family, 'A')

    def test_current_status_equals_initial_after_construction(self):
        m = _make_machine()
        self.assertEqual(m.current_status, m.initial_status)

    def test_activities_empty_after_construction(self):
        m = _make_machine()
        self.assertEqual(m.activities, ())

    def test_schedule_tail_is_start_when_empty(self):
        m = _make_machine()
        self.assertEqual(m.schedule_tail, _START)

    def test_initial_next_runout(self):
        # top=200, btm=300, top_pct=0.4, btm_pct=0.6, rate=100, tgt_wt=100,
        # BEAM_FLOOR_LBS=5. Usable fabric: top (200-5)/0.4=487.5, btm
        # (300-5)/0.6=491.67 -> top limits at 487.5 lbs. next_runout is the
        # end of the last *whole* roll: floor(487.5/100)=4 rolls = 400 lbs,
        # 400/100 = 4h after _START (not the 4.875h floor-crossing point).
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        self.assertEqual(m.next_runout, _START + timedelta(hours=4))


# --- 1.2 Per-activity-type status update --------------------------------

class ActivityStatusUpdateTests(unittest.TestCase):

    def _expect(self, status, **expected):
        for k, v in expected.items():
            self.assertEqual(
                getattr(status, k), v,
                f'field {k!r}: got {getattr(status, k)!r}, expected {v!r}',
            )

    def test_knit_consumes_lbs_and_sets_current_item(self):
        # 50 lbs of A: 0.4*50=20 from top, 0.6*50=30 from btm. 30 min at rate 100.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(minutes=30)
        m.add_activities([Knit(start=_START, end=end, item=_ITEM_A, lbs=50.0)])
        s = m.current_status
        self._expect(
            s,
            as_of=end,
            top_beam=_TOP_BEAM,
            btm_beam=_BTM_BEAM,
            top_lbs_remaining=180.0,
            btm_lbs_remaining=270.0,
            current_item=_ITEM_A,
            is_idle=True,
        )
        self.assertEqual(s, m.status_at(end))

    def test_waste_top_empties_named_bar_and_keeps_item(self):
        # Waste('top') discards top's residue unknit: top beam -> None and
        # top lbs -> 0; btm untouched; current_item stays A. Zero duration
        # (start == end), so as_of is unchanged.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        m.add_activities([Waste(start=_START, end=_START, item=_ITEM_A,
                                bar='top', lbs=45.0)])
        s = m.current_status
        self._expect(
            s,
            as_of=_START,
            top_beam=None,
            btm_beam=_BTM_BEAM,
            top_lbs_remaining=0.0,
            btm_lbs_remaining=300.0,
            current_item=_ITEM_A,
            is_idle=True,
        )
        self.assertEqual(s, m.status_at(_START))

    def test_waste_btm_empties_named_bar_and_keeps_item(self):
        # Symmetric: Waste('btm') clears btm only; top untouched.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        m.add_activities([Waste(start=_START, end=_START, item=_ITEM_A,
                                bar='btm', lbs=55.0)])
        s = m.current_status
        self._expect(
            s,
            as_of=_START,
            top_beam=_TOP_BEAM,
            btm_beam=None,
            top_lbs_remaining=200.0,
            btm_lbs_remaining=0.0,
            current_item=_ITEM_A,
            is_idle=True,
        )
        self.assertEqual(s, m.status_at(_START))

    def test_tape_out_top_only(self):
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(minutes=20)
        m.add_activities([TapeOut(start=_START, end=end, bars='top')])
        s = m.current_status
        self._expect(
            s,
            as_of=end,
            top_beam=None,
            btm_beam=_BTM_BEAM,
            top_lbs_remaining=0.0,
            btm_lbs_remaining=300.0,
            current_item=_ITEM_A,
            is_idle=True,
        )

    def test_tape_out_btm_only(self):
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(minutes=20)
        m.add_activities([TapeOut(start=_START, end=end, bars='btm')])
        s = m.current_status
        self._expect(
            s,
            as_of=end,
            top_beam=_TOP_BEAM,
            btm_beam=None,
            top_lbs_remaining=200.0,
            btm_lbs_remaining=0.0,
            current_item=_ITEM_A,
            is_idle=True,
        )

    def test_tape_out_both(self):
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(hours=1)
        m.add_activities([TapeOut(start=_START, end=end, bars='both')])
        s = m.current_status
        self._expect(
            s,
            as_of=end,
            top_beam=None,
            btm_beam=None,
            top_lbs_remaining=0.0,
            btm_lbs_remaining=0.0,
            current_item=_ITEM_A,
            is_idle=True,
        )

    def test_beam_load_top_sets_beam_and_lbs(self):
        # Start with top already empty so this looks like a natural-exhaustion
        # reload (no preceding TapeOut). btm is untouched.
        m = _make_machine(init_top_lbs=0.0, init_btm_lbs=300.0)
        end = _START + timedelta(minutes=30)
        m.add_activities([
            BeamLoad(start=_START, end=end, bar='top',
                     beam=_ALT_TOP_BEAM, lbs=500.0),
        ])
        s = m.current_status
        self._expect(
            s,
            as_of=end,
            top_beam=_ALT_TOP_BEAM,
            btm_beam=_BTM_BEAM,
            top_lbs_remaining=500.0,
            btm_lbs_remaining=300.0,
            current_item=_ITEM_A,
            is_idle=True,
        )

    def test_beam_load_btm_sets_beam_and_lbs(self):
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=0.0)
        end = _START + timedelta(minutes=30)
        m.add_activities([
            BeamLoad(start=_START, end=end, bar='btm',
                     beam=_ALT_BTM_BEAM, lbs=400.0),
        ])
        s = m.current_status
        self._expect(
            s,
            as_of=end,
            top_beam=_TOP_BEAM,
            btm_beam=_ALT_BTM_BEAM,
            top_lbs_remaining=200.0,
            btm_lbs_remaining=400.0,
            current_item=_ITEM_A,
            is_idle=True,
        )

    def test_style_change_updates_only_current_item(self):
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(minutes=15)
        m.add_activities([
            StyleChange(start=_START, end=end,
                        from_item=_ITEM_A, to_item=_ITEM_B,
                        is_family_change=False),
        ])
        s = m.current_status
        self._expect(
            s,
            as_of=end,
            top_beam=_TOP_BEAM,
            btm_beam=_BTM_BEAM,
            top_lbs_remaining=200.0,
            btm_lbs_remaining=300.0,
            current_item=_ITEM_B,
            is_idle=True,
        )
        # A and B share family 'A' — current_family follows current_item.
        self.assertEqual(s.current_family, 'A')

    def test_style_change_to_different_family_updates_current_family(self):
        # Sanity-check current_family derivation across a family boundary.
        m = _make_machine(init_item=_ITEM_A)
        end = _START + timedelta(minutes=15)
        m.add_activities([
            StyleChange(start=_START, end=end,
                        from_item=_ITEM_A, to_item=_ITEM_C,
                        is_family_change=True),
        ])
        self.assertEqual(m.current_status.current_item, _ITEM_C)
        self.assertEqual(m.current_status.current_family, 'C')

    def test_idle_advances_as_of_and_leaves_everything_else_unchanged(self):
        # Idle is a deliberate gap — beams stay threaded, lbs stay full,
        # current_item is untouched. Only as_of moves forward.
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(hours=6)
        m.add_activities([Idle(start=_START, end=end)])
        s = m.current_status
        self._expect(
            s,
            as_of=end,
            top_beam=_TOP_BEAM,
            btm_beam=_BTM_BEAM,
            top_lbs_remaining=200.0,
            btm_lbs_remaining=300.0,
            current_item=_ITEM_A,
            is_idle=True,
        )

    def test_status_at_strictly_inside_idle_reports_in_progress(self):
        # Idle is itself an activity; status_at(t) for t strictly inside
        # the Idle interval has is_idle=False ("an activity is in progress")
        # even though semantically the machine isn't doing anything.
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(hours=6)
        m.add_activities([Idle(start=_START, end=end)])
        mid = _START + timedelta(hours=3)
        s = m.status_at(mid)
        self.assertEqual(s.as_of, mid)
        self.assertFalse(s.is_idle)
        # Beams and current_item unchanged at any point during the Idle.
        self.assertEqual(s.top_lbs_remaining, 200.0)
        self.assertEqual(s.btm_lbs_remaining, 300.0)
        self.assertEqual(s.current_item, _ITEM_A)


# --- 1.3 add_activities sequencing --------------------------------------

class AddActivitiesSequencingTests(unittest.TestCase):

    def test_realistic_preamble_applied_in_order(self):
        # TapeOut('both') + BeamLoad(top) + BeamLoad(btm) + StyleChange + Job.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        t0 = _START
        t1 = t0 + timedelta(hours=1)     # TapeOut('both') ends
        t2 = t1 + timedelta(minutes=30)  # BeamLoad top ends
        t3 = t2 + timedelta(minutes=30)  # BeamLoad btm ends
        t4 = t3 + timedelta(minutes=15)  # StyleChange ends (to C; family change)
        # Job of 50 lbs of C at rate 50 = 1h. Consumes 0.2*50=10 top, 0.8*50=40 btm.
        t5 = t4 + timedelta(hours=1)
        m.add_activities([
            TapeOut(start=t0, end=t1, bars='both'),
            BeamLoad(start=t1, end=t2, bar='top',
                     beam=_ALT_TOP_BEAM, lbs=400.0),
            BeamLoad(start=t2, end=t3, bar='btm',
                     beam=_ALT_BTM_BEAM, lbs=600.0),
            StyleChange(start=t3, end=t4,
                        from_item=_ITEM_A, to_item=_ITEM_C,
                        is_family_change=True),
            Knit(start=t4, end=t5, item=_ITEM_C, lbs=50.0),
        ])
        s = m.current_status
        self.assertEqual(s.top_beam, _ALT_TOP_BEAM)
        self.assertEqual(s.btm_beam, _ALT_BTM_BEAM)
        self.assertEqual(s.top_lbs_remaining, 390.0)
        self.assertEqual(s.btm_lbs_remaining, 560.0)
        self.assertEqual(s.current_item, _ITEM_C)
        self.assertEqual(s.as_of, t5)
        self.assertTrue(s.is_idle)

    def test_incremental_matches_one_shot(self):
        # Splitting activities across multiple add_activities calls should
        # yield the same final state as a single batched call.
        m_batched = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        m_split = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        t0 = _START
        t1 = t0 + timedelta(hours=1)
        t2 = t1 + timedelta(hours=1)
        acts = [
            Knit(start=t0, end=t1, item=_ITEM_A, lbs=100.0),
            Knit(start=t1, end=t2, item=_ITEM_A, lbs=100.0),
        ]
        m_batched.add_activities(acts)
        for a in acts:
            m_split.add_activities([a])
        self.assertEqual(m_batched.current_status, m_split.current_status)
        self.assertEqual(m_batched.activities, m_split.activities)

    def test_activities_tuple_reflects_full_appended_history(self):
        m = _make_machine()
        a1 = Knit(start=_START, end=_START + timedelta(hours=1),
                 item=_ITEM_A, lbs=100.0)
        a2 = TapeOut(start=_START + timedelta(hours=1),
                     end=_START + timedelta(hours=2),
                     bars='both')
        m.add_activities([a1])
        m.add_activities([a2])
        self.assertEqual(m.activities, (a1, a2))


# --- 1.4 status_at ------------------------------------------------------

class StatusAtTests(unittest.TestCase):

    def test_status_at_initial_start_equals_initial_status(self):
        m = _make_machine()
        self.assertEqual(m.status_at(_START), m.initial_status)

    def test_status_at_in_gap_between_activities_is_post_previous(self):
        # Job 0-1h, idle gap, Job 2-3h. Sample at t1+30min (in the gap).
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=400.0, init_btm_lbs=600.0)
        t0, t1, t2, t3 = (_START + timedelta(hours=h) for h in (0, 1, 2, 3))
        m.add_activities([
            Knit(start=t0, end=t1, item=_ITEM_A, lbs=100.0),
            Knit(start=t2, end=t3, item=_ITEM_A, lbs=100.0),
        ])
        mid_gap = t1 + timedelta(minutes=30)
        s = m.status_at(mid_gap)
        self.assertEqual(s.as_of, mid_gap)
        self.assertTrue(s.is_idle)
        self.assertEqual(s.top_lbs_remaining, 360.0)  # 400 - 0.4*100
        self.assertEqual(s.btm_lbs_remaining, 540.0)  # 600 - 0.6*100

    def test_status_at_strictly_inside_activity_returns_pre_state(self):
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=400.0, init_btm_lbs=600.0)
        end = _START + timedelta(hours=1)
        m.add_activities([Knit(start=_START, end=end,
                              item=_ITEM_A, lbs=100.0)])
        mid = _START + timedelta(minutes=30)
        s = m.status_at(mid)
        self.assertEqual(s.as_of, mid)
        self.assertFalse(s.is_idle)
        # Pre-activity state: full beams (no consumption committed yet).
        self.assertEqual(s.top_lbs_remaining, 400.0)
        self.assertEqual(s.btm_lbs_remaining, 600.0)
        self.assertEqual(s.current_item, _ITEM_A)

    def test_status_at_at_activity_end_is_post_state(self):
        # Boundary: end is treated as inclusive of the post-activity state.
        # is_idle is True because no activity is *in progress* at the end
        # instant (and there is no contiguous next activity here).
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=400.0, init_btm_lbs=600.0)
        end = _START + timedelta(hours=1)
        m.add_activities([Knit(start=_START, end=end,
                              item=_ITEM_A, lbs=100.0)])
        s = m.status_at(end)
        self.assertEqual(s.as_of, end)
        self.assertTrue(s.is_idle)
        self.assertEqual(s.top_lbs_remaining, 360.0)
        self.assertEqual(s.btm_lbs_remaining, 540.0)

    def test_status_at_past_tail_matches_current_status_with_shifted_as_of(self):
        m = _make_machine()
        end = _START + timedelta(hours=1)
        m.add_activities([Knit(start=_START, end=end,
                              item=_ITEM_A, lbs=100.0)])
        far_future = end + timedelta(days=30)
        s = m.status_at(far_future)
        self.assertEqual(s.as_of, far_future)
        self.assertTrue(s.is_idle)
        tail = m.current_status
        for field in ('top_beam', 'btm_beam', 'top_lbs_remaining',
                      'btm_lbs_remaining', 'current_item', 'is_idle'):
            self.assertEqual(
                getattr(s, field), getattr(tail, field),
                f'field {field!r} differs from current_status',
            )

    def test_status_at_before_initial_raises(self):
        m = _make_machine()
        with self.assertRaises(ValueError):
            m.status_at(_START - timedelta(hours=1))


# --- 1.5 next_runout ----------------------------------------------------

class NextRunoutTests(unittest.TestCase):

    def test_top_runs_out_first(self):
        # top=200, btm=400: usable top (200-5)/0.4=487.5, btm
        # (400-5)/0.6=658.33 -> top limits. floor(487.5/100)=4 rolls ->
        # 400/100 = 4h.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=400.0)
        self.assertEqual(m.next_runout, _START + timedelta(hours=4))

    def test_btm_runs_out_first(self):
        # top=400, btm=240: usable top (400-5)/0.4=987.5, btm
        # (240-5)/0.6=391.67 -> btm limits. floor(391.67/100)=3 rolls ->
        # 300/100 = 3h.
        m = _make_machine(init_top_lbs=400.0, init_btm_lbs=240.0)
        self.assertEqual(m.next_runout, _START + timedelta(hours=3))

    def test_simultaneous_runout(self):
        # top=215, btm=320: usable top (215-5)/0.4=525, btm
        # (320-5)/0.6=525 -> equal (simultaneous floor). floor(525/100)=5
        # rolls -> 500/100 = 5h (the 5.25h floor-crossing rounds down).
        m = _make_machine(init_top_lbs=215.0, init_btm_lbs=320.0)
        self.assertEqual(m.next_runout, _START + timedelta(hours=5))

    def test_after_knit_of_whole_roll_preserves_absolute_runout(self):
        # Producing whole rolls of the current item doesn't change *when*
        # the beams force a changeover in absolute time: a whole 100-lb roll
        # advances as_of by 1h and drops the remaining whole-roll count by
        # exactly one. Initial next_runout is +4h (4 rolls); after the roll
        # (top-=40->160, btm-=60->240, as_of=+1h): usable
        # min((160-5)/0.4,(240-5)/0.6)=387.5 -> floor(3.875)=3 rolls -> 3h,
        # so +1h + 3h = +4h, unchanged.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(hours=1)
        m.add_activities([Knit(start=_START, end=end,
                              item=_ITEM_A, lbs=100.0)])
        self.assertEqual(m.next_runout, _START + timedelta(hours=4))

    def test_after_beam_load_pushes_runout_later(self):
        # TapeOut top, then BeamLoad top -> 500 lbs. After: top=500,
        # btm=300, as_of=t2. usable min((500-5)/0.4,(300-5)/0.6)=
        # min(1237.5, 491.67)=491.67 -> floor(4.9167)=4 rolls -> 4h.
        # next_runout = t2 + 4h.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        t0 = _START
        t1 = t0 + timedelta(minutes=20)
        t2 = t1 + timedelta(minutes=30)
        m.add_activities([
            TapeOut(start=t0, end=t1, bars='top'),
            BeamLoad(start=t1, end=t2, bar='top',
                     beam=_TOP_BEAM, lbs=500.0),
        ])
        self.assertEqual(m.next_runout, t2 + timedelta(hours=4))

    def test_after_style_change_uses_new_item_pcts_and_rate(self):
        # StyleChange A->C. C: top_pct=0.2, btm_pct=0.8, rate=50, tgt_wt=150.
        # usable min((200-5)/0.2,(300-5)/0.8)=min(975,368.75)=368.75 ->
        # floor(368.75/150)=2 rolls -> 2*150=300 lbs / 50 = 6h.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(minutes=15)
        m.add_activities([
            StyleChange(start=_START, end=end,
                        from_item=_ITEM_A, to_item=_ITEM_C,
                        is_family_change=True),
        ])
        self.assertEqual(m.next_runout, end + timedelta(hours=6))

    def test_after_tape_out_both_runout_is_immediate(self):
        # Both bars at 0 -> usable negative -> n_rolls clamps to 0 ->
        # next_runout == as_of (the changeover is immediately due).
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(hours=1)
        m.add_activities([TapeOut(start=_START, end=end, bars='both')])
        self.assertEqual(m.next_runout, end)

    def test_below_one_whole_roll_runout_is_immediate(self):
        # Usable yarn above the floor but less than one whole roll: top=40
        # -> usable (40-5)/0.4=87.5 fabric lbs < tgt_wt=100 (btm=300 slack).
        # floor(87.5/100)=0 rolls -> next_runout == as_of even though the
        # bar is well above the floor (distinguishes the whole-roll stopping
        # point from the raw floor-crossing point).
        m = _make_machine(init_top_lbs=40.0, init_btm_lbs=300.0)
        self.assertEqual(m.next_runout, _START)

    def test_workcal_offset_crosses_non_work_hours(self):
        # 9-hour workday (8:00-17:00), Mon-Fri. _START is Mon 9:00.
        # Synthetic item: rate=1 lb/h, top_pct=1.0, btm_pct=1.0, tgt_wt=1.0.
        # top=15 lbs constrains; btm=100 is slack. usable_top=(15-5)/1=10 ->
        # floor(10/1)=10 rolls -> 10 lb / 1 = 10 work-hours offset.
        # offset(Mon 9:00, 10h): 8h fits Mon (until 17:00); 2h remaining ->
        # Tue 8:00 + 2h = Tue 10:00.
        item = Greige(
            'TEST', family='X', tgt_wt=1.0,
            top_beam='40D BLACK 1000X4', top_pct=1.0,
            btm_beam='60D WHITE 1000X4', btm_pct=1.0,
            safety=1.0, machines={'M1': 1.0},
        )
        m = _make_machine(
            init_item=item, init_top_lbs=15.0, init_btm_lbs=100.0,
            workcal=_WEEKDAY_9H,
        )
        self.assertEqual(m.next_runout, datetime(2026, 5, 19, 10, 0))


# ---------------------------- PHASE 2 -----------------------------------

# Additional fixtures: items that violate the Phase 2 same-yarn / same-
# family restriction. These construct cleanly (valid BeamSet ids); the
# restriction check rejects them at plan_production time, not at Greige
# construction.
_ITEM_D = Greige(  # different top yarn, same family
    'AU0004', family='A', tgt_wt=100.0,
    top_beam='30D RED 1000X4', top_pct=0.4,
    btm_beam='60D WHITE 1000X4', btm_pct=0.6,
    safety=1000.0, machines={'M1': 100.0},
)
_ITEM_E = Greige(  # different btm yarn, same family
    'AU0005', family='A', tgt_wt=100.0,
    top_beam='40D BLACK 1000X4', top_pct=0.4,
    btm_beam='90D GREEN 1000X4', btm_pct=0.6,
    safety=1000.0, machines={'M1': 100.0},
)
_ITEM_F = Greige(  # different yarn on both bars AND different family
    'AU0006', family='Q', tgt_wt=100.0,
    top_beam='30D RED 1000X4', top_pct=0.4,
    btm_beam='90D GREEN 1000X4', btm_pct=0.6,
    safety=1000.0, machines={'M1': 100.0},
)
# Large-roll item (same yarn/family as A) for the production-loop runout
# cases: tgt_wt=300 makes the per-roll yarn draw (300*pct = 120 top / 180
# btm) exceed MAX_BEAM_WASTE_LBS=100, so a bar can reach the floor exactly
# at a roll boundary (clean reload, no Waste) instead of always passing
# through the (0, MAX] waste window. Fresh beams: 40D->2800, 60D->1800.
_ITEM_BIG = Greige(
    'AU_BIG', family='A', tgt_wt=300.0,
    top_beam='40D BLACK 1000X4', top_pct=0.4,
    btm_beam='60D WHITE 1000X4', btm_pct=0.6,
    safety=1000.0, machines={'M1': 100.0},
)


def _shape(plan):
    """Tuple-ize a plan's activity stream for structural comparison,
    dropping the auto-incrementing activity ids. Accepts a `ProductionPlan`
    or a raw iterable of activities. Each tuple's leading entry is the
    activity type name; remaining entries are the fields we care about per
    type."""
    activities = getattr(plan, 'activities', plan)
    out = []
    for a in activities:
        if isinstance(a, Knit):
            out.append(('Knit', a.lbs, a.item.id))
        elif isinstance(a, Waste):
            out.append(('Waste', a.bar, a.lbs, a.item.id))
        elif isinstance(a, TapeOut):
            out.append(('TapeOut', a.bars))
        elif isinstance(a, BeamLoad):
            out.append(('BeamLoad', a.bar, a.lbs))
        elif isinstance(a, StyleChange):
            out.append((
                'StyleChange', a.from_item.id, a.to_item.id, a.is_family_change,
            ))
        elif isinstance(a, Idle):
            out.append(('Idle',))
        else:
            raise AssertionError(f'unknown activity type {type(a).__name__}')
    return out


def _knit_count(plan):
    """Number of `Knit` activities in a plan's activity stream."""
    return sum(1 for a in plan.activities if isinstance(a, Knit))


def _job_shape(plan):
    """Structural shape of a plan's production records, dropping job ids:
    one tuple per `Job` of (item id, total_rolls, total_lbs, per-roll
    lbs)."""
    return [
        (j.item.id, j.total_rolls, j.total_lbs,
         tuple(r.lbs for r in j.rolls))
        for j in plan.jobs
    ]


def _assert_single_job(test, plan, item_id, total_lbs, total_rolls):
    """Assert the plan produced exactly one `Job` for `item_id` with the
    given roll totals (`Waste` lbs are not part of the `Job`)."""
    test.assertEqual(len(plan.jobs), 1)
    job = plan.jobs[0]
    test.assertEqual(job.item.id, item_id)
    test.assertAlmostEqual(job.total_lbs, total_lbs)
    test.assertEqual(job.total_rolls, total_rolls)


# --- 2.1 Input acceptance -----------------------------------------------

class PlanProductionInputAcceptanceTests(unittest.TestCase):

    def test_same_item_accepted(self):
        m = _make_machine()
        # No exception → accepted.
        m.plan_production(_ITEM_A, lbs=100.0, start_at='schedule_tail')

    def test_same_yarn_same_family_different_item_accepted(self):
        m = _make_machine()
        m.plan_production(_ITEM_B, lbs=200.0, start_at='schedule_tail')

    def test_invalid_start_at_raises_value_error(self):
        m = _make_machine()
        with self.assertRaises(ValueError):
            m.plan_production(_ITEM_A, lbs=100.0, start_at='bogus')


# --- 2.2 Preamble shape -------------------------------------------------

class PlanProductionPreambleTests(unittest.TestCase):

    def test_same_item_emits_no_preamble(self):
        # to_item == current_item → no preamble; only the production loop.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_A, lbs=100.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), [('Knit', 100.0, 'AU0001')])

    def test_different_item_emits_simple_style_change_only(self):
        # Different item, same yarn + family → exactly one
        # StyleChange(is_family_change=False), no TapeOut or BeamLoad.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), [
            ('StyleChange', 'AU0001', 'AU0002', False),
            ('Knit', 200.0, 'AU0002'),
        ])
        # Duration of the StyleChange is simple_change_duration.
        sc = plan.activities[0]
        self.assertEqual(sc.end - sc.start, _SIMPLE_CHANGE)


# --- 2.3 Production loop ------------------------------------------------

class PlanProductionLoopTests(unittest.TestCase):

    def test_single_roll_no_exhaustion_emits_one_job(self):
        # tgt_wt=100, lbs=100, beams have plenty of capacity.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_A, lbs=100.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), [('Knit', 100.0, 'AU0001')])
        # One Job, backed by exactly one Knit (no mid-job BeamLoad).
        _assert_single_job(self, plan, 'AU0001', 100.0, 1)
        self.assertEqual(_knit_count(plan), 1)

    def test_multiple_rolls_no_exhaustion_emits_one_job(self):
        # 500 lbs = 5 rolls. Beams have capacity (200 top + 300 btm < 2800/1800).
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_A, lbs=500.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), [('Knit', 500.0, 'AU0001')])
        # Still one Job (loop didn't split) backed by exactly one Knit.
        _assert_single_job(self, plan, 'AU0001', 500.0, 5)
        self.assertEqual(_knit_count(plan), 1)

    def test_exhaust_at_roll_boundary_no_waste(self):
        # 2.3.3.1. _ITEM_BIG (tgt 300, top_pct 0.4 -> 120 yarn/roll). top=245
        # so usable_top hits exactly 0 at the 3rd-roll boundary (knit=600:
        # 245-240-5=0), having been 240 / 120 at the prior boundaries -- it
        # jumps the (0, MAX] window, so the gate reloads with NO Waste.
        # btm=3000 stays well above MAX throughout.
        m = _make_machine(init_item=_ITEM_BIG,
                          init_top_lbs=245.0, init_btm_lbs=3000.0)
        plan = m.plan_production(_ITEM_BIG, lbs=900.0,
                                 start_at='schedule_tail')
        self.assertEqual(_shape(plan), [
            ('Knit', 600.0, 'AU_BIG'),       # 2 whole rolls before top floor
            ('BeamLoad', 'top', 2800.0),
            ('Knit', 300.0, 'AU_BIG'),       # final roll on the fresh beam
        ])
        _assert_single_job(self, plan, 'AU_BIG', 900.0, 3)
        self.assertEqual(_knit_count(plan), 2)

    def test_exhaust_at_roll_boundary_coswaps_below_max_bar(self):
        # 2.3.3.2. btm=365 hits exactly 0 at the 3rd-roll boundary (reload);
        # top=305 has only 60 usable yarn there (305-240-5=60 < MAX), so the
        # gate co-swaps it -> a zero-duration Waste(top,60) + BeamLoad(top)
        # alongside btm's reload. (top boundary usables 300 / 180 stayed
        # above MAX before, so it isn't swapped earlier.)
        m = _make_machine(init_item=_ITEM_BIG,
                          init_top_lbs=305.0, init_btm_lbs=365.0)
        plan = m.plan_production(_ITEM_BIG, lbs=900.0,
                                 start_at='schedule_tail')
        self.assertEqual(_shape(plan), [
            ('Knit', 600.0, 'AU_BIG'),
            ('Waste', 'top', 60.0, 'AU_BIG'),   # co-swapped, below MAX
            ('BeamLoad', 'top', 2800.0),
            ('BeamLoad', 'btm', 1800.0),
            ('Knit', 300.0, 'AU_BIG'),
        ])
        # The Waste lbs are not part of the Job.
        _assert_single_job(self, plan, 'AU_BIG', 900.0, 3)
        self.assertEqual(_knit_count(plan), 2)

    def test_exhaust_mid_roll_single_beam_load(self):
        # 2.3.4.1 straddle (also the §2.3.5 single-btm case). btm=305 hits
        # the floor 200 lbs into the 2nd roll (knit=500: 305-300-5=0);
        # top=3000 stays above MAX, so only btm reloads and the roll
        # continues on the fresh beam as one whole roll -- no Waste.
        m = _make_machine(init_item=_ITEM_BIG,
                          init_top_lbs=3000.0, init_btm_lbs=305.0)
        plan = m.plan_production(_ITEM_BIG, lbs=900.0,
                                 start_at='schedule_tail')
        self.assertEqual(_shape(plan), [
            ('Knit', 500.0, 'AU_BIG'),       # roll 1 + 200 lbs of roll 2
            ('BeamLoad', 'btm', 1800.0),
            ('Knit', 400.0, 'AU_BIG'),       # 100 lbs finishing roll 2 + roll 3
        ])
        _assert_single_job(self, plan, 'AU_BIG', 900.0, 3)
        self.assertEqual(_knit_count(plan), 2)

    def test_exhaust_mid_roll_double_beam_load_coswap(self):
        # 2.3.4.2 (other bar below MAX). btm=305 floors mid-roll-2 at
        # knit=500; top=255 has 50 usable yarn there (255-200-5=50 < MAX),
        # so the runout co-swaps top -> Waste(top,50) + BeamLoad(top) in
        # addition to btm's reload. Two beam loads.
        m = _make_machine(init_item=_ITEM_BIG,
                          init_top_lbs=255.0, init_btm_lbs=305.0)
        plan = m.plan_production(_ITEM_BIG, lbs=900.0,
                                 start_at='schedule_tail')
        self.assertEqual(_shape(plan), [
            ('Knit', 500.0, 'AU_BIG'),
            ('Waste', 'top', 50.0, 'AU_BIG'),
            ('BeamLoad', 'top', 2800.0),
            ('BeamLoad', 'btm', 1800.0),
            ('Knit', 400.0, 'AU_BIG'),
        ])
        _assert_single_job(self, plan, 'AU_BIG', 900.0, 3)
        self.assertEqual(_knit_count(plan), 2)

    def test_exhaust_mid_roll_both_bars_simultaneously(self):
        # 2.3.4.2 (both at floor mid-roll). top=235, btm=350 both reach the
        # floor 275 lbs into roll 2 (knit=575: 235-230-5=0 and
        # 350-345-5=0). Two BeamLoads, no Waste.
        m = _make_machine(init_item=_ITEM_BIG,
                          init_top_lbs=235.0, init_btm_lbs=350.0)
        plan = m.plan_production(_ITEM_BIG, lbs=900.0,
                                 start_at='schedule_tail')
        self.assertEqual(_shape(plan), [
            ('Knit', 575.0, 'AU_BIG'),
            ('BeamLoad', 'top', 2800.0),
            ('BeamLoad', 'btm', 1800.0),
            ('Knit', 325.0, 'AU_BIG'),
        ])
        _assert_single_job(self, plan, 'AU_BIG', 900.0, 3)
        self.assertEqual(_knit_count(plan), 2)

    def test_both_bars_exhaust_simultaneously_at_boundary(self):
        # 2.3.6. top=245, btm=365 both hit exactly 0 at the 3rd-roll
        # boundary (knit=600). Two BeamLoads, no Waste (both at the floor,
        # nothing above it to discard).
        m = _make_machine(init_item=_ITEM_BIG,
                          init_top_lbs=245.0, init_btm_lbs=365.0)
        plan = m.plan_production(_ITEM_BIG, lbs=900.0,
                                 start_at='schedule_tail')
        self.assertEqual(_shape(plan), [
            ('Knit', 600.0, 'AU_BIG'),
            ('BeamLoad', 'top', 2800.0),
            ('BeamLoad', 'btm', 1800.0),
            ('Knit', 300.0, 'AU_BIG'),
        ])
        _assert_single_job(self, plan, 'AU_BIG', 900.0, 3)
        self.assertEqual(_knit_count(plan), 2)

    def test_cascading_exhaustion_loops_more_than_twice(self):
        # 2.3.7. top=365, btm=365: btm floors at the 3rd-roll boundary
        # (reload btm), then top floors at the next boundary (reload top) --
        # two reloads on different bars give three Knit segments. Clean
        # boundaries throughout, so no Waste.
        m = _make_machine(init_item=_ITEM_BIG,
                          init_top_lbs=365.0, init_btm_lbs=365.0)
        plan = m.plan_production(_ITEM_BIG, lbs=1200.0,
                                 start_at='schedule_tail')
        self.assertEqual(_shape(plan), [
            ('Knit', 600.0, 'AU_BIG'),
            ('BeamLoad', 'btm', 1800.0),
            ('Knit', 300.0, 'AU_BIG'),
            ('BeamLoad', 'top', 2800.0),
            ('Knit', 300.0, 'AU_BIG'),
        ])
        _assert_single_job(self, plan, 'AU_BIG', 1200.0, 4)
        self.assertEqual(_knit_count(plan), 3)


# --- 2.4 start_at mode behavior -----------------------------------------

class PlanProductionStartAtTests(unittest.TestCase):

    def test_schedule_tail_no_run_up(self):
        # No current-item Jobs ahead of the changeover; first activity is
        # the StyleChange.
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_B, lbs=200.0,
                                 start_at='schedule_tail')
        self.assertEqual(_shape(plan), [
            ('StyleChange', 'AU0001', 'AU0002', False),
            ('Knit', 200.0, 'AU0002'),
        ])
        self.assertEqual(plan.activities[0].start, m.current_status.as_of)
        # schedule_tail mode: exactly one Job (the new item).
        _assert_single_job(self, plan, 'AU0002', 200.0, 1)

    def test_next_runout_emits_run_up_before_changeover(self):
        # Run-up emits WHOLE rolls of the current item (no Waste, no beam
        # work of its own), then the changeover, then new production.
        # init 200/400: run-up usable min((200-5)/0.4, (400-5)/0.6) =
        # min(487.5, 658.33) = 487.5 -> floor(4.875)=4 rolls = 400 lbs of A.
        # After: top=40, btm=160 (leftover, same yarn as B). The preamble
        # keeps both bars (matching yarn) so it emits only the StyleChange.
        # B's loop then hits the pre-roll gate: top usable 35 < MAX ->
        # Waste(top,35) + reload; btm usable 155 > MAX -> kept.
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=200.0, init_btm_lbs=400.0)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='next_runout')
        self.assertEqual(_shape(plan), [
            ('Knit', 400.0, 'AU0001'),          # run-up: 4 whole rolls, no Waste
            ('StyleChange', 'AU0001', 'AU0002', False),
            ('Waste', 'top', 35.0, 'AU0002'),   # loop swaps the leftover top beam
            ('BeamLoad', 'top', 2800.0),
            ('Knit', 200.0, 'AU0002'),          # new item production
        ])
        # Two Jobs: run-up Job (current item) then the new item's Job.
        self.assertEqual(len(plan.jobs), 2)
        self.assertEqual(plan.jobs[0].item.id, 'AU0001')
        self.assertEqual(
            (plan.jobs[0].total_rolls, plan.jobs[0].total_lbs), (4, 400.0),
        )
        self.assertEqual(plan.jobs[1].item.id, 'AU0002')
        self.assertEqual(
            (plan.jobs[1].total_rolls, plan.jobs[1].total_lbs), (1, 200.0),
        )
        # The run-up itself produced no Waste of the current item.
        self.assertFalse(any(
            isinstance(a, Waste) and a.item is _ITEM_A
            for a in plan.activities
        ))

    def test_next_runout_run_up_below_one_roll_yields_one_job(self):
        # Current item A (tgt 100). producible = (16-5)/0.4 = 27.5 fabric
        # lbs < tgt_wt, so the run-up makes no whole roll: it emits NOTHING
        # (no Knit, no Waste of A) and creates no run-up Job. Exactly one
        # Job is produced -- the new item's. (The leftover A yarn is swapped
        # later, inside B's production loop, recorded as a Waste of B.)
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=16.0, init_btm_lbs=2000.0)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='next_runout')
        # The run-up emitted nothing for the current item.
        self.assertFalse(any(
            isinstance(a, (Knit, Waste)) and a.item is _ITEM_A
            for a in plan.activities
        ))
        # Exactly one Job — the new item's.
        _assert_single_job(self, plan, 'AU0002', 200.0, 1)


# --- 2.5 Purity and commit ----------------------------------------------

class PlanProductionPurityTests(unittest.TestCase):

    def test_plan_production_does_not_mutate_state(self):
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        before_status = m.current_status
        before_acts = m.activities
        before_jobs = m.jobs
        m.plan_production(_ITEM_B, lbs=200.0, start_at='next_runout')
        self.assertEqual(m.current_status, before_status)
        self.assertEqual(m.activities, before_acts)
        self.assertEqual(m.jobs, before_jobs)

    def test_two_calls_produce_identical_shape(self):
        # Activity ids necessarily differ between calls; structural shape
        # (types, items, lbs, etc.) must match.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        plan1 = m.plan_production(_ITEM_B, lbs=200.0, start_at='next_runout')
        plan2 = m.plan_production(_ITEM_B, lbs=200.0, start_at='next_runout')
        self.assertEqual(_shape(plan1), _shape(plan2))
        self.assertEqual(_job_shape(plan1), _job_shape(plan2))

    def test_commit_yields_status_matching_manual_application(self):
        # plan_production + add_activities should leave current_status in the
        # same state as applying each activity manually via apply_activity.
        m_plan = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        m_manual = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)

        plan = m_plan.plan_production(_ITEM_B, lbs=200.0,
                                      start_at='schedule_tail')
        m_plan.add_activities(plan.activities)
        m_plan.add_jobs(plan.jobs)

        manual_status = m_manual.current_status
        for a in plan.activities:
            manual_status = manual_status.apply_activity(a)

        for field in ('as_of', 'top_beam', 'btm_beam', 'top_lbs_remaining',
                      'btm_lbs_remaining', 'current_item', 'is_idle'):
            self.assertEqual(
                getattr(m_plan.current_status, field),
                getattr(manual_status, field),
                f'field {field!r} differs',
            )
        # add_jobs committed exactly the plan's Job records.
        self.assertEqual(m_plan.jobs, plan.jobs)


# --- 2.6 Timing ---------------------------------------------------------

class PlanProductionTimingTests(unittest.TestCase):

    def test_each_activity_starts_where_previous_ended(self):
        # Plan spanning run-up + reload + changeover + production. Verify
        # activities chain contiguously with no gaps.
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=200.0, init_btm_lbs=300.0)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='next_runout')
        self.assertEqual(plan.activities[0].start, m.current_status.as_of)
        for i in range(1, len(plan.activities)):
            self.assertEqual(
                plan.activities[i].start, plan.activities[i-1].end,
                f'activity {i} ({type(plan.activities[i]).__name__}) start '
                f'{plan.activities[i].start} != previous end {plan.activities[i-1].end}',
            )

    def test_job_duration_matches_rate(self):
        # 200 lbs of B at rate 100 lbs/h → 2h.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='schedule_tail')
        job = next(a for a in plan.activities if isinstance(a, Knit))
        self.assertEqual(job.end - job.start, timedelta(hours=2))

    def test_style_change_duration_matches_simple_change_duration(self):
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='schedule_tail')
        sc = next(a for a in plan.activities if isinstance(a, StyleChange))
        self.assertEqual(sc.end - sc.start, _SIMPLE_CHANGE)

    def test_beam_load_duration_matches_module_constant(self):
        from swmtplanner.schedule import BEAM_LOAD_DURATION
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=2000.0)
        plan = m.plan_production(_ITEM_A, lbs=700.0, start_at='schedule_tail')
        bl = next(a for a in plan.activities if isinstance(a, BeamLoad))
        self.assertEqual(bl.end - bl.start, BEAM_LOAD_DURATION)

    def test_activity_end_respects_workcal_gap(self):
        # Weekday 8-17 workcal; _START is Mon 9:00. Request 1000 lbs of A at
        # rate 100 = 10 work-hours. 8h fits Mon (9-17), 2h spills to Tue
        # 8-10. End should be Tue 10:00.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0,
                          workcal=_WEEKDAY_9H)
        plan = m.plan_production(_ITEM_A, lbs=1000.0,
                                 start_at='schedule_tail')
        self.assertEqual(plan.activities[0].start, _START)
        self.assertEqual(plan.activities[0].end, datetime(2026, 5, 19, 10, 0))


# --- 2.7 idle_for parameter ---------------------------------------------

class PlanProductionIdleForTests(unittest.TestCase):

    def test_idle_for_default_emits_no_idle(self):
        m = _make_machine()
        plan = m.plan_production(_ITEM_A, lbs=100.0, start_at='schedule_tail')
        self.assertFalse(any(isinstance(a, Idle) for a in plan.activities))

    def test_idle_for_positive_emits_idle_first(self):
        m = _make_machine()
        plan = m.plan_production(_ITEM_A, lbs=100.0,
                                 start_at='schedule_tail',
                                 idle_for=timedelta(hours=6))
        self.assertIsInstance(plan.activities[0], Idle)
        self.assertEqual(plan.activities[0].start, m.current_status.as_of)
        self.assertEqual(plan.activities[0].end - plan.activities[0].start, timedelta(hours=6))

    def test_idle_precedes_run_up_in_next_runout(self):
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=200.0, init_btm_lbs=300.0)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='next_runout',
                                 idle_for=timedelta(hours=6))
        # First is Idle; second is the run-up Knit(A).
        self.assertIsInstance(plan.activities[0], Idle)
        self.assertIsInstance(plan.activities[1], Knit)
        self.assertEqual(plan.activities[1].item, _ITEM_A)

    def test_idle_precedes_preamble_in_schedule_tail(self):
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='schedule_tail',
                                 idle_for=timedelta(hours=6))
        # First is Idle; second is StyleChange.
        self.assertIsInstance(plan.activities[0], Idle)
        self.assertIsInstance(plan.activities[1], StyleChange)

    def test_negative_idle_for_raises_value_error(self):
        m = _make_machine()
        with self.assertRaises(ValueError):
            m.plan_production(_ITEM_A, lbs=100.0, start_at='schedule_tail',
                              idle_for=timedelta(hours=-1))


# ---------------------------- PHASE 3 -----------------------------------

# Additional fixtures for cross-yarn / cross-family transitions.
_ITEM_G = Greige(  # different yarn on BOTH bars, same family
    'AU0007', family='A', tgt_wt=100.0,
    top_beam='30D RED 1000X4', top_pct=0.4,
    btm_beam='90D GREEN 1000X4', btm_pct=0.6,
    safety=1000.0, machines={'M1': 100.0},
)
_ITEM_H = Greige(  # different top yarn only, different family
    'AU0008', family='Q', tgt_wt=100.0,
    top_beam='30D RED 1000X4', top_pct=0.4,
    btm_beam='60D WHITE 1000X4', btm_pct=0.6,
    safety=1000.0, machines={'M1': 100.0},
)

# Pre-built BeamSet expected on emitted BeamLoads.
_ALT_TOP = BeamSet('30D RED 1000X4')      # denier 30 → fresh 2800
_ALT_BTM = BeamSet('90D GREEN 1000X4')    # denier 90 → fresh 1800


# --- 3.1 Inputs previously rejected, by changeover shape ----------------

class PlanProductionChangeoverShapeTests(unittest.TestCase):

    def test_different_top_yarn_same_family(self):
        # current A → D: top yarn differs (30D RED), btm yarn matches.
        # Expect TapeOut('top') + BeamLoad(top, 2800) + StyleChange(False).
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_D, lbs=100.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), [
            ('TapeOut', 'top'),
            ('BeamLoad', 'top', 2800.0),
            ('StyleChange', 'AU0001', 'AU0004', False),
            ('Knit', 100.0, 'AU0004'),
        ])

    def test_different_btm_yarn_same_family(self):
        # current A → E: btm yarn differs (90D GREEN), top yarn matches.
        # Expect TapeOut('btm') + BeamLoad(btm, 1800) + StyleChange(False).
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_E, lbs=100.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), [
            ('TapeOut', 'btm'),
            ('BeamLoad', 'btm', 1800.0),
            ('StyleChange', 'AU0001', 'AU0005', False),
            ('Knit', 100.0, 'AU0005'),
        ])

    def test_different_yarn_on_both_bars_same_family(self):
        # current A → G: both yarns differ, same family A.
        # Expect TapeOut('both') + BeamLoad(top, 2800) + BeamLoad(btm, 1800)
        # + StyleChange(False).
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_G, lbs=100.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), [
            ('TapeOut', 'both'),
            ('BeamLoad', 'top', 2800.0),
            ('BeamLoad', 'btm', 1800.0),
            ('StyleChange', 'AU0001', 'AU0007', False),
            ('Knit', 100.0, 'AU0007'),
        ])

    def test_same_yarn_different_family(self):
        # current A → C: same yarn on both bars, family changes (A → C).
        # Expect StyleChange(True) only; no beam work.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_C, lbs=150.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), [
            ('StyleChange', 'AU0001', 'AU0003', True),
            ('Knit', 150.0, 'AU0003'),
        ])

    def test_different_top_yarn_different_family(self):
        # current A → H: top yarn differs, btm yarn matches, family Q.
        # Expect TapeOut('top') + BeamLoad(top) + StyleChange(True).
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_H, lbs=100.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), [
            ('TapeOut', 'top'),
            ('BeamLoad', 'top', 2800.0),
            ('StyleChange', 'AU0001', 'AU0008', True),
            ('Knit', 100.0, 'AU0008'),
        ])

    def test_different_yarn_on_both_bars_different_family(self):
        # current A → F: both yarns differ, family Q.
        # Expect TapeOut('both') + BeamLoad(top) + BeamLoad(btm)
        # + StyleChange(True).
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_F, lbs=100.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), [
            ('TapeOut', 'both'),
            ('BeamLoad', 'top', 2800.0),
            ('BeamLoad', 'btm', 1800.0),
            ('StyleChange', 'AU0001', 'AU0006', True),
            ('Knit', 100.0, 'AU0006'),
        ])

    def test_mismatched_bar_below_max_is_wasted(self):
        # 3.1.3. A -> D (top yarn differs 30D, btm matches 60D). top has only
        # 50 lbs -> usable 45 <= MAX_BEAM_WASTE_LBS, so its mismatched residue
        # is discarded as a zero-duration Waste(top,45) rather than preserved
        # with a TapeOut. The Waste is attributed to the outgoing item A.
        m = _make_machine(init_top_lbs=50.0, init_btm_lbs=2800.0)
        plan = m.plan_production(_ITEM_D, lbs=100.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), [
            ('Waste', 'top', 45.0, 'AU0001'),
            ('BeamLoad', 'top', 2800.0),
            ('StyleChange', 'AU0001', 'AU0004', False),
            ('Knit', 100.0, 'AU0004'),
        ])

    def test_empty_bar_gets_beam_load_only(self):
        # 3.1.4. A -> D, top at the floor (5 lbs -> usable 0). An empty/at-
        # floor bar is reloaded with NO TapeOut and NO Waste (nothing worth
        # preserving or discarding). btm matches -> kept.
        m = _make_machine(init_top_lbs=5.0, init_btm_lbs=2800.0)
        plan = m.plan_production(_ITEM_D, lbs=100.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), [
            ('BeamLoad', 'top', 2800.0),
            ('StyleChange', 'AU0001', 'AU0004', False),
            ('Knit', 100.0, 'AU0004'),
        ])

    def test_mixed_tape_out_and_waste_no_both(self):
        # 3.1.6. A -> G (both yarns differ). top is full (usable > MAX) so it
        # tapes out to preserve; btm has only 50 lbs (usable 45 <= MAX) so it
        # wastes. Only one bar tapes -> single TapeOut('top'), NOT 'both'.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=50.0)
        plan = m.plan_production(_ITEM_G, lbs=100.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), [
            ('TapeOut', 'top'),
            ('Waste', 'btm', 45.0, 'AU0001'),
            ('BeamLoad', 'top', 2800.0),
            ('BeamLoad', 'btm', 1800.0),
            ('StyleChange', 'AU0001', 'AU0007', False),
            ('Knit', 100.0, 'AU0007'),
        ])

    def test_matching_near_empty_bar_kept_then_swapped_in_loop(self):
        # 3.1.7. A -> E (top matches 40D, btm differs 90D). top has only 50
        # lbs but its yarn MATCHES E, so the preamble keeps it (no Waste, no
        # TapeOut) -- the near-empty swap is deferred to the production
        # loop's pre-roll gate, which then wastes it as a Waste of E. btm
        # (mismatched, full) tapes out in the preamble.
        m = _make_machine(init_top_lbs=50.0, init_btm_lbs=2800.0)
        plan = m.plan_production(_ITEM_E, lbs=100.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), [
            ('TapeOut', 'btm'),                  # preamble: btm mismatched/full
            ('BeamLoad', 'btm', 1800.0),
            ('StyleChange', 'AU0001', 'AU0005', False),
            ('Waste', 'top', 45.0, 'AU0005'),    # loop: matching near-empty top
            ('BeamLoad', 'top', 2800.0),
            ('Knit', 100.0, 'AU0005'),
        ])


# --- 3.2 'next_runout' with non-trivial changeovers ---------------------

class PlanProductionNextRunoutChangeoverTests(unittest.TestCase):

    def test_both_bars_mismatched_above_max_tape_out_both(self):
        # 3.2.1 -- the headline case the OLD drain-to-empty model made
        # impossible. Current _ITEM_BIG (tgt 300) run up from 485/665:
        # usable min((485-5)/0.4, (665-5)/0.6)=min(1200,1100)=1100 ->
        # floor(1100/300)=3 rolls (900 lbs). Both bars are left with 125 lbs
        # (usable 120 > MAX) of MISMATCHED yarn (BIG is 40D/60D, F is
        # 30D/90D), so the preamble tapes BOTH out together -> TapeOut('both')
        # IS reachable in next_runout mode.
        m = _make_machine(init_item=_ITEM_BIG,
                          init_top_lbs=485.0, init_btm_lbs=665.0)
        plan = m.plan_production(_ITEM_F, lbs=100.0, start_at='next_runout')
        self.assertEqual(_shape(plan), [
            ('Knit', 900.0, 'AU_BIG'),           # run-up: 3 whole rolls
            ('TapeOut', 'both'),
            ('BeamLoad', 'top', 2800.0),
            ('BeamLoad', 'btm', 1800.0),
            ('StyleChange', 'AU_BIG', 'AU0006', True),
            ('Knit', 100.0, 'AU0006'),
        ])
        self.assertEqual(len(plan.jobs), 2)
        self.assertEqual(plan.jobs[0].item.id, 'AU_BIG')
        self.assertEqual(
            (plan.jobs[0].total_rolls, plan.jobs[0].total_lbs), (3, 900.0),
        )
        self.assertEqual(plan.jobs[1].item.id, 'AU0006')

    def test_limiting_bar_wasted_other_bar_taped(self):
        # 3.2.2. A (tgt 100) run up from 200/2000 -> 4 rolls (400 lbs),
        # leaving top=40 (usable 35) and btm=1760 (usable 1755). A -> G both
        # yarns differ: the limiting top (usable 35 <= MAX) is wasted, while
        # the full btm (usable 1755 > MAX) is preserved with a single
        # TapeOut('btm').
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=200.0, init_btm_lbs=2000.0)
        plan = m.plan_production(_ITEM_G, lbs=100.0, start_at='next_runout')
        self.assertEqual(_shape(plan), [
            ('Knit', 400.0, 'AU0001'),
            ('TapeOut', 'btm'),                  # other bar preserved
            ('Waste', 'top', 35.0, 'AU0001'),    # limiting bar discarded
            ('BeamLoad', 'top', 2800.0),
            ('BeamLoad', 'btm', 1800.0),
            ('StyleChange', 'AU0001', 'AU0007', False),
            ('Knit', 100.0, 'AU0007'),
        ])

    def test_one_bar_matches_is_kept(self):
        # 3.2.3. A -> D (btm yarn matches 60D, top differs). Run up 200/2000
        # -> 4 rolls; top leftover (usable 35, mismatched) is wasted, btm
        # leftover (matching) is kept and carries into D's production.
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=200.0, init_btm_lbs=2000.0)
        plan = m.plan_production(_ITEM_D, lbs=100.0, start_at='next_runout')
        self.assertEqual(_shape(plan), [
            ('Knit', 400.0, 'AU0001'),
            ('Waste', 'top', 35.0, 'AU0001'),
            ('BeamLoad', 'top', 2800.0),
            ('StyleChange', 'AU0001', 'AU0004', False),
            ('Knit', 100.0, 'AU0004'),
        ])

    def test_leftover_bar_at_floor_gets_beam_load_only(self):
        # 3.2.4. top=205 makes the run-up land top exactly at the floor:
        # usable (205-5)/0.4=500 = 5 whole rolls; after, top=5 (usable 0).
        # A -> D: the at-floor top is reloaded with NO Waste (nothing above
        # the floor to discard); btm matches and is kept.
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=205.0, init_btm_lbs=2000.0)
        plan = m.plan_production(_ITEM_D, lbs=100.0, start_at='next_runout')
        self.assertEqual(_shape(plan), [
            ('Knit', 500.0, 'AU0001'),           # 5 whole rolls
            ('BeamLoad', 'top', 2800.0),         # at-floor reload, no Waste
            ('StyleChange', 'AU0001', 'AU0004', False),
            ('Knit', 100.0, 'AU0004'),
        ])

    def test_run_up_emits_whole_rolls_and_no_waste(self):
        # 3.2.6 regression. The run-up itself is exactly whole rolls of the
        # current item with no Waste: the first activity is a Knit(A) whose
        # lbs is a multiple of tgt_wt, and the run-up Job's rolls are all
        # whole tgt_wt rolls. (Any Waste in the plan belongs to the preamble
        # or the new item's loop, never the run-up.)
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=200.0, init_btm_lbs=2000.0)
        plan = m.plan_production(_ITEM_D, lbs=100.0, start_at='next_runout')
        first = plan.activities[0]
        self.assertIsInstance(first, Knit)
        self.assertIs(first.item, _ITEM_A)
        self.assertEqual(first.lbs % _ITEM_A.tgt_wt, 0.0)
        run_up_job = plan.jobs[0]
        self.assertEqual(run_up_job.item.id, 'AU0001')
        self.assertTrue(all(r.lbs == _ITEM_A.tgt_wt for r in run_up_job.rolls))

    def test_style_change_is_family_change_reflects_family_comparison(self):
        # next_runout into a different-family item (same yarn) triggers
        # is_family_change=True.
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=200.0, init_btm_lbs=2000.0)
        plan = m.plan_production(_ITEM_C, lbs=150.0, start_at='next_runout')
        sc = next(a for a in plan.activities if isinstance(a, StyleChange))
        self.assertTrue(sc.is_family_change)


# --- 3.3 StyleChange duration -------------------------------------------

class PlanProductionStyleChangeDurationTests(unittest.TestCase):

    def test_simple_change_uses_simple_change_duration(self):
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='schedule_tail')
        sc = next(a for a in plan.activities if isinstance(a, StyleChange))
        self.assertFalse(sc.is_family_change)
        self.assertEqual(sc.end - sc.start, _SIMPLE_CHANGE)

    def test_family_change_uses_family_change_duration(self):
        # A → C is a family change with no beam work.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_C, lbs=150.0, start_at='schedule_tail')
        sc = next(a for a in plan.activities if isinstance(a, StyleChange))
        self.assertTrue(sc.is_family_change)
        self.assertEqual(sc.end - sc.start, _FAMILY_CHANGE)

    def test_durations_are_independent_per_machine(self):
        # Same transition, two machines with different family_change_duration:
        # expect the StyleChange end times to differ.
        long_family = timedelta(hours=3)
        m_short = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        m_long = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0,
                               family_change_duration=long_family)
        plan_short = m_short.plan_production(_ITEM_C, lbs=150.0,
                                             start_at='schedule_tail')
        plan_long = m_long.plan_production(_ITEM_C, lbs=150.0,
                                           start_at='schedule_tail')
        sc_short = next(a for a in plan_short.activities if isinstance(a, StyleChange))
        sc_long = next(a for a in plan_long.activities if isinstance(a, StyleChange))
        self.assertEqual(sc_short.end - sc_short.start, _FAMILY_CHANGE)
        self.assertEqual(sc_long.end - sc_long.start, long_family)


# --- 3.5 New-machine behavior (is_new=True) -----------------------------

class PlanProductionNewMachineTests(unittest.TestCase):
    """A `Machine` constructed with `is_new=True` collapses family changes
    into the same `StyleChange(is_family_change=False)` shape (and the
    same duration) as in-family style changes. The hardware-time
    distinction simply doesn't exist on these machines, and surfacing it
    as `is_family_change=True` would let any downstream cost weight
    that distinguishes family changes from simple ones double-charge a
    transition that isn't actually more expensive."""

    def test_is_new_attribute_round_trip(self):
        self.assertFalse(_make_machine().is_new)
        self.assertTrue(_make_machine(is_new=True).is_new)

    def test_new_machine_cross_family_emits_simple_style_change(self):
        # A → C (different family). On a legacy machine this would be
        # is_family_change=True; on a new machine it's False.
        m = _make_machine(
            init_top_lbs=2800.0, init_btm_lbs=1800.0, is_new=True,
        )
        plan = m.plan_production(_ITEM_C, lbs=150.0, start_at='schedule_tail')
        sc = next(a for a in plan.activities if isinstance(a, StyleChange))
        self.assertFalse(sc.is_family_change)
        self.assertEqual(sc.end - sc.start, _SIMPLE_CHANGE)

    def test_new_machine_in_family_unchanged(self):
        # A → B (same family). is_family_change=False on both machine
        # types; verifying the new-machine path doesn't perturb this.
        m = _make_machine(
            init_top_lbs=2800.0, init_btm_lbs=1800.0, is_new=True,
        )
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='schedule_tail')
        sc = next(a for a in plan.activities if isinstance(a, StyleChange))
        self.assertFalse(sc.is_family_change)
        self.assertEqual(sc.end - sc.start, _SIMPLE_CHANGE)

    def test_new_machine_ignores_family_change_duration(self):
        # The `family_change_duration` param is still accepted (kept for
        # API symmetry) but unused on new machines: every StyleChange
        # uses simple_change_duration regardless.
        long_family = timedelta(hours=10)
        m = _make_machine(
            init_top_lbs=2800.0, init_btm_lbs=1800.0,
            family_change_duration=long_family, is_new=True,
        )
        plan = m.plan_production(_ITEM_C, lbs=150.0, start_at='schedule_tail')
        sc = next(a for a in plan.activities if isinstance(a, StyleChange))
        self.assertEqual(sc.end - sc.start, _SIMPLE_CHANGE)
        self.assertFalse(sc.is_family_change)

    def test_old_machine_still_emits_family_change(self):
        # Regression check: the default (is_new=False) path is
        # unchanged.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_C, lbs=150.0, start_at='schedule_tail')
        sc = next(a for a in plan.activities if isinstance(a, StyleChange))
        self.assertTrue(sc.is_family_change)
        self.assertEqual(sc.end - sc.start, _FAMILY_CHANGE)


# --- 3.4 TapeOut duration -----------------------------------------------

class PlanProductionTapeOutDurationTests(unittest.TestCase):

    def test_single_tape_out_uses_single_duration(self):
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_D, lbs=100.0, start_at='schedule_tail')
        to = next(a for a in plan.activities if isinstance(a, TapeOut))
        self.assertEqual(to.bars, 'top')
        self.assertEqual(to.end - to.start, TAPE_OUT_SINGLE_DURATION)

    def test_both_tape_out_uses_both_duration(self):
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_F, lbs=100.0, start_at='schedule_tail')
        to = next(a for a in plan.activities if isinstance(a, TapeOut))
        self.assertEqual(to.bars, 'both')
        self.assertEqual(to.end - to.start, TAPE_OUT_BOTH_DURATION)


# ---------------------------- PHASE 4 -----------------------------------

# Mon 2026-05-18 00:00 is the start of ISO week 2026-W21 (chosen because
# _START = 2026-05-18 09:00 lives in this same ISO week — keeping the
# Phase 4 fixtures aligned with the rest of the file).
_W21 = (2026, 21)
_W21_START = datetime(2026, 5, 18, 0, 0)
_W21_END = _W21_START + timedelta(days=7)


# --- 4.1 No preamble required -------------------------------------------

class ProducibleLbsNoPreambleTests(unittest.TestCase):

    def test_time_bound_under_huge_beams(self):
        # Huge beams, 24/7 workcal: capacity is bounded by week-hours × rate.
        # 168h × 100 lbs/h = 16800 lbs (168 rolls of 100).
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=_W21_START)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_A, *_W21), 16800.0)

    def test_beam_bound_single_cycle(self):
        # 5h window remaining in the week. top=200 (top_pct=0.4): usable yarn
        # drops below MAX_BEAM_WASTE_LBS at the 4th-roll boundary
        # (200-3*40-5=75 < 100), so only 3 whole rolls (300 lbs = 3h) are
        # produced before the max-waste gate swaps top. The reload then runs
        # h=3..5, ending exactly at week_end, so no 4th roll fits -> 300 lbs.
        # (Under the no-floor model this used to be 500.)
        as_of = _W21_END - timedelta(hours=5)
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=2000.0,
                          start=as_of)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_A, *_W21), 300.0)

    def test_multiple_mid_stream_reloads_fit(self):
        # top=200, btm=300, 168h window. Production cascades through many
        # beam swaps; each forced BeamLoad costs 2h and each near-empty bar
        # is swapped (a zero-duration Waste) before it would strand a roll.
        # The floor + max-waste model leaves 15000 lbs of whole rolls fitting
        # in the week (vs 15200 under the old no-floor model -- the residue
        # discarded at each swap and the floor on each beam trim the total).
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0,
                          start=_W21_START)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_A, *_W21), 15000.0)


# --- 4.2 Preamble required ----------------------------------------------

class ProducibleLbsPreambleTests(unittest.TestCase):

    def test_preamble_fits_and_leaves_time(self):
        # Current = A, request B (same yarn, same family) → StyleChange of
        # _SIMPLE_CHANGE (15 min). 168h - 0.25h = 167.75h of production time.
        # 167.75 × 100 = 16775 lbs → floor to rolls of B's tgt_wt=200 =
        # 83 rolls × 200 = 16600.
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=_W21_START)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_B, *_W21), 16600.0)

    def test_preamble_alone_exceeds_window_returns_zero(self):
        # as_of 3h before week_end. Preamble for A → F (different yarn on
        # both bars, different family) = TapeOut('both', 6h) + 2×BeamLoad
        # (2h each) + StyleChange(family, 1h) = 11h. Far exceeds 3h window.
        as_of = _W21_END - timedelta(hours=3)
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=as_of)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_F, *_W21), 0.0)

    def test_preamble_fits_but_no_full_roll_returns_zero(self):
        # as_of 1.5h before week_end. A → C is a family change with no beam
        # work — only a StyleChange of _FAMILY_CHANGE (1h). 0.5h left for
        # production = 50 lbs at rate 100, less than tgt_wt=150 of C.
        as_of = _W21_END - timedelta(hours=1, minutes=30)
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=as_of)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_C, *_W21), 0.0)


# --- 4.3 Workcal alignment ----------------------------------------------

class ProducibleLbsWorkcalAlignmentTests(unittest.TestCase):

    def test_as_of_before_week_starts(self):
        # as_of one day before week_start (Sun before W21). With 24/7 workcal
        # the implicit idle bridges 24h, then full 168h production window.
        # Result should equal the case where as_of == week_start.
        as_of = _W21_START - timedelta(days=1)
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=as_of)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_A, *_W21), 16800.0)

    def test_as_of_strictly_inside_week(self):
        # as_of = Wed 12:00 of W21. Window: Wed 12:00 → next Mon 00:00 =
        # 108h. Capacity = 10800 lbs (huge beams, no preamble).
        as_of = datetime(2026, 5, 20, 12, 0)   # Wed of W21
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=as_of)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_A, *_W21), 10800.0)

    def test_as_of_past_week_end_returns_zero(self):
        as_of = _W21_END + timedelta(hours=1)
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=as_of)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_A, *_W21), 0.0)

    def test_non_work_hours_excluded_under_weekday_workcal(self):
        # Weekday 9h workcal: 5 days × 9h = 45 work hours in a week.
        # 45h × 100 lbs/h = 4500 lbs (45 rolls). No preamble.
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=_W21_START, workcal=_WEEKDAY_9H)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_A, *_W21), 4500.0)

    def test_iso_cross_year_week_resolves_correctly(self):
        # ISO 2026-W01 starts Mon Dec 29 2025. as_of in late Dec 2025; the
        # bridge spans the year boundary into the W01 window.
        as_of = datetime(2025, 12, 27, 0, 0)   # Sat before W01 Monday
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=as_of)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_A, 2026, 1), 16800.0)


# --- 4.4 Determinism and purity -----------------------------------------

class ProducibleLbsPurityTests(unittest.TestCase):

    def test_does_not_mutate_state(self):
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0,
                          start=_W21_START)
        before_status = m.current_status
        before_acts = m.activities
        m.producible_lbs_in_week(_ITEM_B, *_W21)
        self.assertEqual(m.current_status, before_status)
        self.assertEqual(m.activities, before_acts)

    def test_repeated_calls_yield_same_result(self):
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0,
                          start=_W21_START)
        a = m.producible_lbs_in_week(_ITEM_B, *_W21)
        b = m.producible_lbs_in_week(_ITEM_B, *_W21)
        self.assertEqual(a, b)


# --- 4.5 Rounding -------------------------------------------------------

class ProducibleLbsRoundingTests(unittest.TestCase):

    def test_result_is_always_a_multiple_of_tgt_wt(self):
        # Spot-check the multiple-of-tgt_wt property across varied scenarios.
        scenarios = [
            # (init_top, init_btm, as_of, item, year, week)
            (100_000.0, 100_000.0, _W21_START, _ITEM_A, *_W21),
            (200.0, 2000.0, _W21_END - timedelta(hours=5), _ITEM_A, *_W21),
            (200.0, 300.0, _W21_START, _ITEM_A, *_W21),
            (100_000.0, 100_000.0, _W21_START, _ITEM_B, *_W21),
            (100_000.0, 100_000.0, _W21_START, _ITEM_C, *_W21),
        ]
        for top, btm, start, item, year, week in scenarios:
            with self.subTest(start=start, item=item.id):
                m = _make_machine(init_top_lbs=top, init_btm_lbs=btm,
                                  start=start)
                result = m.producible_lbs_in_week(item, year, week)
                self.assertEqual(result % item.tgt_wt, 0.0,
                                 f'{result} is not a multiple of {item.tgt_wt}')

    def test_exactly_one_roll_fits(self):
        # 1h window, no preamble. 1h × 100 lbs/h = 100 lbs = exactly one roll.
        as_of = _W21_END - timedelta(hours=1)
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=as_of)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_A, *_W21), 100.0)

    def test_just_under_one_roll_returns_zero(self):
        # 30 min window, no preamble. 0.5h × 100 = 50 lbs, less than
        # tgt_wt=100. Result = 0.
        as_of = _W21_END - timedelta(minutes=30)
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=as_of)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_A, *_W21), 0.0)


# --- 4.6 `start` parameter ---------------------------------------------

class ProducibleLbsStartParameterTests(unittest.TestCase):

    def test_start_none_matches_explicit_as_of(self):
        # Passing start=current_status.as_of explicitly should produce the
        # same result as omitting it (the default branch).
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=_W21_START)
        default = m.producible_lbs_in_week(_ITEM_A, *_W21)
        explicit = m.producible_lbs_in_week(_ITEM_A, *_W21,
                                             start=m.current_status.as_of)
        self.assertEqual(default, explicit)

    def test_start_inside_window_delays_production(self):
        # as_of = week_start. With start = week_start + 48h, production
        # effectively begins 2 days into the window. 168h - 48h = 120h
        # of work-hour budget at rate 100 = 12000 lbs (huge beams).
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=_W21_START)
        start = _W21_START + timedelta(hours=48)
        self.assertEqual(
            m.producible_lbs_in_week(_ITEM_A, *_W21, start=start),
            12000.0,
        )

    def test_start_before_week_start_collapses_to_week_start(self):
        # as_of = day before week_start. start = 12h after as_of, still
        # before week_start. Production effectively begins at week_start
        # regardless — same result as start=None.
        as_of = _W21_START - timedelta(days=1)
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=as_of)
        default = m.producible_lbs_in_week(_ITEM_A, *_W21)
        explicit_pre_week = m.producible_lbs_in_week(
            _ITEM_A, *_W21, start=as_of + timedelta(hours=12),
        )
        self.assertEqual(default, explicit_pre_week)

    def test_start_past_week_end_returns_zero(self):
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=_W21_START)
        start = _W21_END + timedelta(hours=1)
        self.assertEqual(
            m.producible_lbs_in_week(_ITEM_A, *_W21, start=start),
            0.0,
        )

    def test_start_before_as_of_raises(self):
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=_W21_START)
        with self.assertRaises(ValueError):
            m.producible_lbs_in_week(_ITEM_A, *_W21,
                                      start=_W21_START - timedelta(hours=1))


if __name__ == '__main__':
    unittest.main()
