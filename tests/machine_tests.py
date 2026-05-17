#!/usr/bin/env python

import unittest
from datetime import datetime, timedelta

from swmtplanner.products import Greige, BeamSet
from swmtplanner.schedule import (
    Machine, Job, Waste, TapeOut, BeamLoad, StyleChange, Idle,
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

    def test_next_job_end_is_start_when_empty(self):
        m = _make_machine()
        self.assertEqual(m.next_job_end, _START)

    def test_initial_next_runout(self):
        # top=200, btm=300, top_pct=0.4, btm_pct=0.6, rate=100 lbs/h.
        # top exhausts at 200/0.4 = 500 lbs; btm at 300/0.6 = 500 lbs.
        # Simultaneous, 500 lbs / 100 lbs/h = 5h after _START.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        self.assertEqual(m.next_runout, _START + timedelta(hours=5))


# --- 1.2 Per-activity-type status update --------------------------------

class ActivityStatusUpdateTests(unittest.TestCase):

    def _expect(self, status, **expected):
        for k, v in expected.items():
            self.assertEqual(
                getattr(status, k), v,
                f'field {k!r}: got {getattr(status, k)!r}, expected {v!r}',
            )

    def test_job_consumes_lbs_and_sets_current_item(self):
        # 50 lbs of A: 0.4*50=20 from top, 0.6*50=30 from btm. 30 min at rate 100.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(minutes=30)
        m.add_activities([Job(start=_START, end=end, item=_ITEM_A, lbs=50.0)])
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

    def test_waste_consumes_lbs_but_keeps_current_item(self):
        # 25 lbs of A as waste: 10 top, 15 btm. current_item still A.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(minutes=15)
        m.add_activities([Waste(start=_START, end=end, item=_ITEM_A, lbs=25.0)])
        s = m.current_status
        self._expect(
            s,
            as_of=end,
            top_lbs_remaining=190.0,
            btm_lbs_remaining=285.0,
            current_item=_ITEM_A,
            is_idle=True,
        )
        self.assertEqual(s, m.status_at(end))

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
            Job(start=t4, end=t5, item=_ITEM_C, lbs=50.0),
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
            Job(start=t0, end=t1, item=_ITEM_A, lbs=100.0),
            Job(start=t1, end=t2, item=_ITEM_A, lbs=100.0),
        ]
        m_batched.add_activities(acts)
        for a in acts:
            m_split.add_activities([a])
        self.assertEqual(m_batched.current_status, m_split.current_status)
        self.assertEqual(m_batched.activities, m_split.activities)

    def test_activities_tuple_reflects_full_appended_history(self):
        m = _make_machine()
        a1 = Job(start=_START, end=_START + timedelta(hours=1),
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
            Job(start=t0, end=t1, item=_ITEM_A, lbs=100.0),
            Job(start=t2, end=t3, item=_ITEM_A, lbs=100.0),
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
        m.add_activities([Job(start=_START, end=end,
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
        m.add_activities([Job(start=_START, end=end,
                              item=_ITEM_A, lbs=100.0)])
        s = m.status_at(end)
        self.assertEqual(s.as_of, end)
        self.assertTrue(s.is_idle)
        self.assertEqual(s.top_lbs_remaining, 360.0)
        self.assertEqual(s.btm_lbs_remaining, 540.0)

    def test_status_at_past_tail_matches_current_status_with_shifted_as_of(self):
        m = _make_machine()
        end = _START + timedelta(hours=1)
        m.add_activities([Job(start=_START, end=end,
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
        # top=200, btm=400: producible_top=500, producible_btm=666.67. Top wins.
        # 500 / 100 = 5h.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=400.0)
        self.assertEqual(m.next_runout, _START + timedelta(hours=5))

    def test_btm_runs_out_first(self):
        # top=400, btm=240: producible_top=1000, producible_btm=400. Btm wins.
        # 400 / 100 = 4h.
        m = _make_machine(init_top_lbs=400.0, init_btm_lbs=240.0)
        self.assertEqual(m.next_runout, _START + timedelta(hours=4))

    def test_simultaneous_runout(self):
        # top=200, btm=300: both producible at 500 lbs.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        self.assertEqual(m.next_runout, _START + timedelta(hours=5))

    def test_after_job_reflects_remaining_lbs(self):
        # A Job that consumes proportionally to the item's pcts doesn't
        # change *when* the beams will exhaust in absolute time — it just
        # advances `as_of` by the time it took and shrinks the remaining
        # lbs by exactly that much. So next_runout stays at +5h.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(minutes=30)
        m.add_activities([Job(start=_START, end=end,
                              item=_ITEM_A, lbs=50.0)])
        self.assertEqual(m.next_runout, _START + timedelta(hours=5))

    def test_after_beam_load_pushes_runout_later(self):
        # TapeOut top 20 min, BeamLoad top → 500 lbs (30 min). After: top=500,
        # btm=300, as_of=+50min. producible = min(500/0.4, 300/0.6) = 500.
        # 500 / 100 = 5h → next_runout = +50min + 5h.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        t0 = _START
        t1 = t0 + timedelta(minutes=20)
        t2 = t1 + timedelta(minutes=30)
        m.add_activities([
            TapeOut(start=t0, end=t1, bars='top'),
            BeamLoad(start=t1, end=t2, bar='top',
                     beam=_TOP_BEAM, lbs=500.0),
        ])
        self.assertEqual(m.next_runout, t2 + timedelta(hours=5))

    def test_after_style_change_uses_new_item_pcts_and_rate(self):
        # StyleChange A→C. After change, top_pct=0.2, btm_pct=0.8, rate=50.
        # producible = min(200/0.2, 300/0.8) = min(1000, 375) = 375.
        # 375 / 50 = 7.5h.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(minutes=15)
        m.add_activities([
            StyleChange(start=_START, end=end,
                        from_item=_ITEM_A, to_item=_ITEM_C,
                        is_family_change=True),
        ])
        self.assertEqual(m.next_runout,
                         end + timedelta(hours=7, minutes=30))

    def test_after_tape_out_both_runout_is_immediate(self):
        # Both bars at 0 → producible 0 → next_runout == as_of.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(hours=1)
        m.add_activities([TapeOut(start=_START, end=end, bars='both')])
        self.assertEqual(m.next_runout, end)

    def test_workcal_offset_crosses_non_work_hours(self):
        # 9-hour workday (8:00–17:00), Mon-Fri. _START is Mon 9:00.
        # Synthetic item: rate=1 lb/h, top_pct=1.0, btm_pct=1.0.
        # top=10 lbs constrains; btm=100 lbs is slack.
        # producible_before_runout = 10 lbs → 10 work-hours offset.
        # offset(Mon 9:00, 10h): 8h fits Mon (until 17:00); 2h remaining →
        # Tue 8:00 + 2h = Tue 10:00.
        item = Greige(
            'TEST', family='X', tgt_wt=1.0,
            top_beam='40D BLACK 1000X4', top_pct=1.0,
            btm_beam='60D WHITE 1000X4', btm_pct=1.0,
            safety=1.0, machines={'M1': 1.0},
        )
        m = _make_machine(
            init_item=item, init_top_lbs=10.0, init_btm_lbs=100.0,
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


def _shape(plan):
    """Tuple-ize a plan for structural comparison, dropping the auto-
    incrementing activity ids. Each tuple's leading entry is the activity
    type name; remaining entries are the fields we care about per type."""
    out = []
    for a in plan:
        if isinstance(a, Job):
            out.append(('Job', a.lbs, a.item.id))
        elif isinstance(a, Waste):
            out.append(('Waste', a.lbs, a.item.id))
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


# --- 2.1 Input acceptance -----------------------------------------------

class PlanProductionInputAcceptanceTests(unittest.TestCase):

    def test_same_item_accepted(self):
        m = _make_machine()
        # No exception → accepted.
        m.plan_production(_ITEM_A, lbs=100.0, start_at='next_job_end')

    def test_same_yarn_same_family_different_item_accepted(self):
        m = _make_machine()
        m.plan_production(_ITEM_B, lbs=200.0, start_at='next_job_end')

    def test_invalid_start_at_raises_value_error(self):
        m = _make_machine()
        with self.assertRaises(ValueError):
            m.plan_production(_ITEM_A, lbs=100.0, start_at='bogus')


# --- 2.2 Preamble shape -------------------------------------------------

class PlanProductionPreambleTests(unittest.TestCase):

    def test_same_item_emits_no_preamble(self):
        # to_item == current_item → no preamble; only the production loop.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_A, lbs=100.0, start_at='next_job_end')
        self.assertEqual(_shape(plan), [('Job', 100.0, 'AU0001')])

    def test_different_item_emits_simple_style_change_only(self):
        # Different item, same yarn + family → exactly one
        # StyleChange(is_family_change=False), no TapeOut or BeamLoad.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='next_job_end')
        self.assertEqual(_shape(plan), [
            ('StyleChange', 'AU0001', 'AU0002', False),
            ('Job', 200.0, 'AU0002'),
        ])
        # Duration of the StyleChange is simple_change_duration.
        sc = plan[0]
        self.assertEqual(sc.end - sc.start, _SIMPLE_CHANGE)


# --- 2.3 Production loop ------------------------------------------------

class PlanProductionLoopTests(unittest.TestCase):

    def test_single_roll_no_exhaustion_emits_one_job(self):
        # tgt_wt=100, lbs=100, beams have plenty of capacity.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_A, lbs=100.0, start_at='next_job_end')
        self.assertEqual(_shape(plan), [('Job', 100.0, 'AU0001')])

    def test_multiple_rolls_no_exhaustion_emits_one_job(self):
        # 500 lbs = 5 rolls. Beams have capacity (200 top + 300 btm < 2800/1800).
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_A, lbs=500.0, start_at='next_job_end')
        self.assertEqual(_shape(plan), [('Job', 500.0, 'AU0001')])

    def test_top_exhausts_at_roll_boundary_no_waste(self):
        # top=200, btm=2000(slack), top_pct=0.4 → top_capacity=500=5 rolls.
        # 40D denier → fresh top is 2800 lbs.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=2000.0)
        plan = m.plan_production(_ITEM_A, lbs=700.0, start_at='next_job_end')
        self.assertEqual(_shape(plan), [
            ('Job', 500.0, 'AU0001'),
            ('BeamLoad', 'top', 2800.0),
            ('Job', 200.0, 'AU0001'),
        ])

    def test_top_exhausts_mid_roll_emits_waste(self):
        # Synthetic item with tgt_wt=300 so producible 500 splits 300 + 200.
        item_big_roll = Greige(
            'AU_BIG', family='A', tgt_wt=300.0,
            top_beam='40D BLACK 1000X4', top_pct=0.4,
            btm_beam='60D WHITE 1000X4', btm_pct=0.6,
            safety=1000.0, machines={'M1': 100.0},
        )
        m = _make_machine(init_item=item_big_roll,
                          init_top_lbs=200.0, init_btm_lbs=2000.0)
        plan = m.plan_production(item_big_roll, lbs=600.0,
                                 start_at='next_job_end')
        self.assertEqual(_shape(plan), [
            ('Job', 300.0, 'AU_BIG'),     # 1 complete roll before top runs out
            ('Waste', 200.0, 'AU_BIG'),   # partial fabric, discarded
            ('BeamLoad', 'top', 2800.0),
            ('Job', 300.0, 'AU_BIG'),     # 1 more complete roll on the new beam
        ])

    def test_btm_exhausts_at_roll_boundary(self):
        # top=2000(slack), btm=300 → btm_capacity=500=5 rolls.
        # 60D denier → fresh btm is 1800 lbs.
        m = _make_machine(init_top_lbs=2000.0, init_btm_lbs=300.0)
        plan = m.plan_production(_ITEM_A, lbs=700.0, start_at='next_job_end')
        self.assertEqual(_shape(plan), [
            ('Job', 500.0, 'AU0001'),
            ('BeamLoad', 'btm', 1800.0),
            ('Job', 200.0, 'AU0001'),
        ])

    def test_both_bars_exhaust_simultaneously(self):
        # top=200, btm=300: top_lbs/top_pct == btm_lbs/btm_pct == 500.
        # Both bars need a reload after the first 500 lbs.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        plan = m.plan_production(_ITEM_A, lbs=800.0, start_at='next_job_end')
        self.assertEqual(_shape(plan), [
            ('Job', 500.0, 'AU0001'),
            ('BeamLoad', 'top', 2800.0),
            ('BeamLoad', 'btm', 1800.0),
            ('Job', 300.0, 'AU0001'),
        ])

    def test_cascading_exhaustion_loops_more_than_twice(self):
        # After cycle 1 (Job 500 + reload both), cycle 2 produces 3000 lbs
        # before btm runs out again at 1800/0.6=3000. Cycle 3 finishes the
        # remaining 600.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        plan = m.plan_production(_ITEM_A, lbs=4100.0,
                                 start_at='next_job_end')
        self.assertEqual(_shape(plan), [
            ('Job', 500.0, 'AU0001'),
            ('BeamLoad', 'top', 2800.0),
            ('BeamLoad', 'btm', 1800.0),
            ('Job', 3000.0, 'AU0001'),
            ('BeamLoad', 'btm', 1800.0),
            ('Job', 600.0, 'AU0001'),
        ])


# --- 2.4 start_at mode behavior -----------------------------------------

class PlanProductionStartAtTests(unittest.TestCase):

    def test_next_job_end_no_run_up(self):
        # No current-item Jobs ahead of the changeover; first activity is
        # the StyleChange.
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_B, lbs=200.0,
                                 start_at='next_job_end')
        self.assertEqual(_shape(plan), [
            ('StyleChange', 'AU0001', 'AU0002', False),
            ('Job', 200.0, 'AU0002'),
        ])
        self.assertEqual(plan[0].start, m.current_status.as_of)

    def test_next_runout_emits_run_up_before_changeover(self):
        # Run-up emits Jobs of current_item until exhaustion, then changeover,
        # then new production.
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=200.0, init_btm_lbs=300.0)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='next_runout')
        self.assertEqual(_shape(plan), [
            ('Job', 500.0, 'AU0001'),       # run-up of current item
            ('BeamLoad', 'top', 2800.0),
            ('BeamLoad', 'btm', 1800.0),
            ('StyleChange', 'AU0001', 'AU0002', False),
            ('Job', 200.0, 'AU0002'),       # new item production
        ])

    def test_next_runout_with_partial_roll_emits_waste_in_run_up(self):
        # Current item has tgt_wt=300, top exhausts at 500 lbs producible.
        # Run-up: Job(300) + Waste(200). Only top exhausted → single BeamLoad.
        item_big = Greige(
            'AU_RUN', family='A', tgt_wt=300.0,
            top_beam='40D BLACK 1000X4', top_pct=0.4,
            btm_beam='60D WHITE 1000X4', btm_pct=0.6,
            safety=1000.0, machines={'M1': 100.0},
        )
        m = _make_machine(init_item=item_big,
                          init_top_lbs=200.0, init_btm_lbs=2000.0)
        plan = m.plan_production(_ITEM_A, lbs=100.0, start_at='next_runout')
        self.assertEqual(_shape(plan), [
            ('Job', 300.0, 'AU_RUN'),
            ('Waste', 200.0, 'AU_RUN'),
            ('BeamLoad', 'top', 2800.0),
            ('StyleChange', 'AU_RUN', 'AU0001', False),
            ('Job', 100.0, 'AU0001'),
        ])


# --- 2.5 Purity and commit ----------------------------------------------

class PlanProductionPurityTests(unittest.TestCase):

    def test_plan_production_does_not_mutate_state(self):
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        before_status = m.current_status
        before_acts = m.activities
        m.plan_production(_ITEM_B, lbs=200.0, start_at='next_runout')
        self.assertEqual(m.current_status, before_status)
        self.assertEqual(m.activities, before_acts)

    def test_two_calls_produce_identical_shape(self):
        # Activity ids necessarily differ between calls; structural shape
        # (types, items, lbs, etc.) must match.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        plan1 = m.plan_production(_ITEM_B, lbs=200.0, start_at='next_runout')
        plan2 = m.plan_production(_ITEM_B, lbs=200.0, start_at='next_runout')
        self.assertEqual(_shape(plan1), _shape(plan2))

    def test_commit_yields_status_matching_manual_application(self):
        # plan_production + add_activities should leave current_status in the
        # same state as applying each activity manually via apply_activity.
        m_plan = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        m_manual = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)

        plan = m_plan.plan_production(_ITEM_B, lbs=200.0,
                                      start_at='next_job_end')
        m_plan.add_activities(plan)

        manual_status = m_manual.current_status
        for a in plan:
            manual_status = manual_status.apply_activity(a)

        for field in ('as_of', 'top_beam', 'btm_beam', 'top_lbs_remaining',
                      'btm_lbs_remaining', 'current_item', 'is_idle'):
            self.assertEqual(
                getattr(m_plan.current_status, field),
                getattr(manual_status, field),
                f'field {field!r} differs',
            )


# --- 2.6 Timing ---------------------------------------------------------

class PlanProductionTimingTests(unittest.TestCase):

    def test_each_activity_starts_where_previous_ended(self):
        # Plan spanning run-up + reload + changeover + production. Verify
        # activities chain contiguously with no gaps.
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=200.0, init_btm_lbs=300.0)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='next_runout')
        self.assertEqual(plan[0].start, m.current_status.as_of)
        for i in range(1, len(plan)):
            self.assertEqual(
                plan[i].start, plan[i-1].end,
                f'activity {i} ({type(plan[i]).__name__}) start '
                f'{plan[i].start} != previous end {plan[i-1].end}',
            )

    def test_job_duration_matches_rate(self):
        # 200 lbs of B at rate 100 lbs/h → 2h.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='next_job_end')
        job = next(a for a in plan if isinstance(a, Job))
        self.assertEqual(job.end - job.start, timedelta(hours=2))

    def test_style_change_duration_matches_simple_change_duration(self):
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='next_job_end')
        sc = next(a for a in plan if isinstance(a, StyleChange))
        self.assertEqual(sc.end - sc.start, _SIMPLE_CHANGE)

    def test_beam_load_duration_matches_module_constant(self):
        from swmtplanner.schedule import BEAM_LOAD_DURATION
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=2000.0)
        plan = m.plan_production(_ITEM_A, lbs=700.0, start_at='next_job_end')
        bl = next(a for a in plan if isinstance(a, BeamLoad))
        self.assertEqual(bl.end - bl.start, BEAM_LOAD_DURATION)

    def test_activity_end_respects_workcal_gap(self):
        # Weekday 8-17 workcal; _START is Mon 9:00. Request 1000 lbs of A at
        # rate 100 = 10 work-hours. 8h fits Mon (9-17), 2h spills to Tue
        # 8-10. End should be Tue 10:00.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0,
                          workcal=_WEEKDAY_9H)
        plan = m.plan_production(_ITEM_A, lbs=1000.0,
                                 start_at='next_job_end')
        self.assertEqual(plan[0].start, _START)
        self.assertEqual(plan[0].end, datetime(2026, 5, 19, 10, 0))


# --- 2.7 idle_for parameter ---------------------------------------------

class PlanProductionIdleForTests(unittest.TestCase):

    def test_idle_for_default_emits_no_idle(self):
        m = _make_machine()
        plan = m.plan_production(_ITEM_A, lbs=100.0, start_at='next_job_end')
        self.assertFalse(any(isinstance(a, Idle) for a in plan))

    def test_idle_for_positive_emits_idle_first(self):
        m = _make_machine()
        plan = m.plan_production(_ITEM_A, lbs=100.0,
                                 start_at='next_job_end',
                                 idle_for=timedelta(hours=6))
        self.assertIsInstance(plan[0], Idle)
        self.assertEqual(plan[0].start, m.current_status.as_of)
        self.assertEqual(plan[0].end - plan[0].start, timedelta(hours=6))

    def test_idle_precedes_run_up_in_next_runout(self):
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=200.0, init_btm_lbs=300.0)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='next_runout',
                                 idle_for=timedelta(hours=6))
        # First is Idle; second is the run-up Job(A).
        self.assertIsInstance(plan[0], Idle)
        self.assertIsInstance(plan[1], Job)
        self.assertEqual(plan[1].item, _ITEM_A)

    def test_idle_precedes_preamble_in_next_job_end(self):
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='next_job_end',
                                 idle_for=timedelta(hours=6))
        # First is Idle; second is StyleChange.
        self.assertIsInstance(plan[0], Idle)
        self.assertIsInstance(plan[1], StyleChange)

    def test_negative_idle_for_raises_value_error(self):
        m = _make_machine()
        with self.assertRaises(ValueError):
            m.plan_production(_ITEM_A, lbs=100.0, start_at='next_job_end',
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
        plan = m.plan_production(_ITEM_D, lbs=100.0, start_at='next_job_end')
        self.assertEqual(_shape(plan), [
            ('TapeOut', 'top'),
            ('BeamLoad', 'top', 2800.0),
            ('StyleChange', 'AU0001', 'AU0004', False),
            ('Job', 100.0, 'AU0004'),
        ])

    def test_different_btm_yarn_same_family(self):
        # current A → E: btm yarn differs (90D GREEN), top yarn matches.
        # Expect TapeOut('btm') + BeamLoad(btm, 1800) + StyleChange(False).
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_E, lbs=100.0, start_at='next_job_end')
        self.assertEqual(_shape(plan), [
            ('TapeOut', 'btm'),
            ('BeamLoad', 'btm', 1800.0),
            ('StyleChange', 'AU0001', 'AU0005', False),
            ('Job', 100.0, 'AU0005'),
        ])

    def test_different_yarn_on_both_bars_same_family(self):
        # current A → G: both yarns differ, same family A.
        # Expect TapeOut('both') + BeamLoad(top, 2800) + BeamLoad(btm, 1800)
        # + StyleChange(False).
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_G, lbs=100.0, start_at='next_job_end')
        self.assertEqual(_shape(plan), [
            ('TapeOut', 'both'),
            ('BeamLoad', 'top', 2800.0),
            ('BeamLoad', 'btm', 1800.0),
            ('StyleChange', 'AU0001', 'AU0007', False),
            ('Job', 100.0, 'AU0007'),
        ])

    def test_same_yarn_different_family(self):
        # current A → C: same yarn on both bars, family changes (A → C).
        # Expect StyleChange(True) only; no beam work.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_C, lbs=150.0, start_at='next_job_end')
        self.assertEqual(_shape(plan), [
            ('StyleChange', 'AU0001', 'AU0003', True),
            ('Job', 150.0, 'AU0003'),
        ])

    def test_different_top_yarn_different_family(self):
        # current A → H: top yarn differs, btm yarn matches, family Q.
        # Expect TapeOut('top') + BeamLoad(top) + StyleChange(True).
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_H, lbs=100.0, start_at='next_job_end')
        self.assertEqual(_shape(plan), [
            ('TapeOut', 'top'),
            ('BeamLoad', 'top', 2800.0),
            ('StyleChange', 'AU0001', 'AU0008', True),
            ('Job', 100.0, 'AU0008'),
        ])

    def test_different_yarn_on_both_bars_different_family(self):
        # current A → F: both yarns differ, family Q.
        # Expect TapeOut('both') + BeamLoad(top) + BeamLoad(btm)
        # + StyleChange(True).
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_F, lbs=100.0, start_at='next_job_end')
        self.assertEqual(_shape(plan), [
            ('TapeOut', 'both'),
            ('BeamLoad', 'top', 2800.0),
            ('BeamLoad', 'btm', 1800.0),
            ('StyleChange', 'AU0001', 'AU0006', True),
            ('Job', 100.0, 'AU0006'),
        ])


# --- 3.2 'next_runout' with non-trivial changeovers ---------------------

class PlanProductionNextRunoutChangeoverTests(unittest.TestCase):

    def test_one_bar_exhausted_other_yarn_matches(self):
        # top=200, btm=2000 → top exhausts at producible=500 (clean roll
        # boundary, no Waste). After run-up: top empty, btm has matching
        # yarn (A → D shares btm yarn). Expect only BeamLoad(top, new_top).
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=200.0, init_btm_lbs=2000.0)
        plan = m.plan_production(_ITEM_D, lbs=100.0, start_at='next_runout')
        self.assertEqual(_shape(plan), [
            ('Job', 500.0, 'AU0001'),               # run-up of current item
            ('BeamLoad', 'top', 2800.0),            # exhausted bar reload
            ('StyleChange', 'AU0001', 'AU0004', False),
            ('Job', 100.0, 'AU0004'),
        ])

    def test_one_bar_exhausted_other_yarn_does_not_match(self):
        # top=200, btm=2000 → top exhausts. A → G changes both yarns, so
        # btm (still threaded with A's yarn) needs to be taped out single.
        # Expect TapeOut('btm') + BeamLoad(top) + BeamLoad(btm) + StyleChange.
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=200.0, init_btm_lbs=2000.0)
        plan = m.plan_production(_ITEM_G, lbs=100.0, start_at='next_runout')
        self.assertEqual(_shape(plan), [
            ('Job', 500.0, 'AU0001'),
            ('TapeOut', 'btm'),                     # single, not 'both'
            ('BeamLoad', 'top', 2800.0),
            ('BeamLoad', 'btm', 1800.0),
            ('StyleChange', 'AU0001', 'AU0007', False),
            ('Job', 100.0, 'AU0007'),
        ])

    def test_both_bars_exhaust_simultaneously_with_full_changeover(self):
        # top=200, btm=300 → both exhaust at 500. After: both empty. A → G
        # changes both yarns but no TapeOut is needed (bars empty). Two
        # BeamLoads then StyleChange.
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=200.0, init_btm_lbs=300.0)
        plan = m.plan_production(_ITEM_G, lbs=100.0, start_at='next_runout')
        self.assertEqual(_shape(plan), [
            ('Job', 500.0, 'AU0001'),
            ('BeamLoad', 'top', 2800.0),
            ('BeamLoad', 'btm', 1800.0),
            ('StyleChange', 'AU0001', 'AU0007', False),
            ('Job', 100.0, 'AU0007'),
        ])

    def test_tape_out_both_never_appears_in_next_runout_mode(self):
        # Whatever the new item, after the run-up at least one bar is
        # empty, so TapeOut('both') cannot be emitted. Spot-check with
        # several new items spanning the changeover-shape cases.
        for new_item in (_ITEM_D, _ITEM_E, _ITEM_F, _ITEM_G, _ITEM_H):
            with self.subTest(new_item=new_item.id):
                m = _make_machine(init_item=_ITEM_A,
                                  init_top_lbs=200.0, init_btm_lbs=2000.0)
                plan = m.plan_production(
                    new_item, lbs=100.0, start_at='next_runout',
                )
                bars = [a.bars for a in plan if isinstance(a, TapeOut)]
                self.assertNotIn('both', bars)

    def test_style_change_is_family_change_reflects_family_comparison(self):
        # next_runout into a different-family item triggers
        # is_family_change=True.
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=200.0, init_btm_lbs=2000.0)
        plan = m.plan_production(_ITEM_C, lbs=150.0, start_at='next_runout')
        sc = next(a for a in plan if isinstance(a, StyleChange))
        self.assertTrue(sc.is_family_change)


# --- 3.3 StyleChange duration -------------------------------------------

class PlanProductionStyleChangeDurationTests(unittest.TestCase):

    def test_simple_change_uses_simple_change_duration(self):
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='next_job_end')
        sc = next(a for a in plan if isinstance(a, StyleChange))
        self.assertFalse(sc.is_family_change)
        self.assertEqual(sc.end - sc.start, _SIMPLE_CHANGE)

    def test_family_change_uses_family_change_duration(self):
        # A → C is a family change with no beam work.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_C, lbs=150.0, start_at='next_job_end')
        sc = next(a for a in plan if isinstance(a, StyleChange))
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
                                             start_at='next_job_end')
        plan_long = m_long.plan_production(_ITEM_C, lbs=150.0,
                                           start_at='next_job_end')
        sc_short = next(a for a in plan_short if isinstance(a, StyleChange))
        sc_long = next(a for a in plan_long if isinstance(a, StyleChange))
        self.assertEqual(sc_short.end - sc_short.start, _FAMILY_CHANGE)
        self.assertEqual(sc_long.end - sc_long.start, long_family)


# --- 3.4 TapeOut duration -----------------------------------------------

class PlanProductionTapeOutDurationTests(unittest.TestCase):

    def test_single_tape_out_uses_single_duration(self):
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_D, lbs=100.0, start_at='next_job_end')
        to = next(a for a in plan if isinstance(a, TapeOut))
        self.assertEqual(to.bars, 'top')
        self.assertEqual(to.end - to.start, TAPE_OUT_SINGLE_DURATION)

    def test_both_tape_out_uses_both_duration(self):
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_F, lbs=100.0, start_at='next_job_end')
        to = next(a for a in plan if isinstance(a, TapeOut))
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
        # 5h window remaining in the week; initial top=200 (with top_pct=0.4)
        # exhausts at 500 lbs producible = 5h. Reload would start at week_end
        # exactly, so it doesn't fit.
        as_of = _W21_END - timedelta(hours=5)
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=2000.0,
                          start=as_of)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_A, *_W21), 500.0)

    def test_multiple_mid_stream_reloads_fit(self):
        # top=200, btm=300 (simultaneous exhaustion at 500 lbs). 168h window.
        # Plan trace: 7 full cycles produce 14500 lbs by hour 161; an 8th
        # cycle starts at h=161 with 7h of window left, producing 700 more
        # lbs (within the partial Job before week_end). 15200 lbs total.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0,
                          start=_W21_START)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_A, *_W21), 15200.0)


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
