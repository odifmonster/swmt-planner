#!/usr/bin/env python

import unittest
from datetime import datetime, timedelta

from swmtplanner.products import Greige, BeamSet
from swmtplanner.schedule import (
    Machine, Status, Knit, Job, Roll, Waste, Doff, TapeOut,
    Hanging, Threading, StyleChange, RunnerChange, PatternChange, Idle,
    TAPE_OUT_SINGLE_DURATION, TAPE_OUT_BOTH_DURATION,
    HANGING_SINGLE_DURATION, HANGING_BOTH_DURATION,
    THREADING_SINGLE_DURATION, THREADING_BOTH_DURATION,
    DOFF_DURATION, STYLE_CHANGE_DURATION, RUNNER_CHANGE_DURATION,
    PATTERN_CHANGE_DURATION,
)
from swmtplanner.schedule.activity import BEAM_FLOOR_LBS
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


def _make_machine(
    init_item=_ITEM_A,
    init_top_lbs=200.0,
    init_btm_lbs=300.0,
    workcal=_24_7,
    start=_START,
    init_top_beam=_TOP_BEAM,
    init_btm_beam=_BTM_BEAM,
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
        is_new=is_new,
    )


def _status(top, btm, *, current_item=_ITEM_A, as_of=_START, is_idle=True):
    """Build a `Status` directly from per-bar `(beam, lbs_remaining,
    threaded)` tuples — used to set up the removed / hung / threaded
    pre-states the beam-swap guard rails depend on."""
    return Status.create(
        as_of=as_of, current_item=current_item, is_idle=is_idle,
        top_beam=top[0], top_lbs_remaining=top[1], top_threaded=top[2],
        btm_beam=btm[0], btm_lbs_remaining=btm[1], btm_threaded=btm[2],
    )


# ---------------------------- PHASE 1 -----------------------------------

# --- 1.1 Construction and initial state ---------------------------------

class MachineConstructionTests(unittest.TestCase):

    def test_id_and_prefix(self):
        m = _make_machine()
        self.assertEqual(m.id, 'M1')
        self.assertEqual(m.prefix, 'Machine')

    def test_initial_status_fields(self):
        # Read through the accessors; a machine begins threaded and running on
        # both bars.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        s = m.initial_status
        self.assertEqual(s.as_of, _START)
        self.assertEqual(s.beam('top'), _TOP_BEAM)
        self.assertEqual(s.beam('btm'), _BTM_BEAM)
        self.assertEqual(s.lbs_remaining('top'), 200.0)
        self.assertEqual(s.lbs_remaining('btm'), 300.0)
        self.assertTrue(s.threaded('top'))
        self.assertTrue(s.threaded('btm'))
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
        # (300-5)/0.6=491.67 -> top limits at 487.5 lbs -> floor(487.5/100)=4
        # whole rolls. next_runout folds in a Doff per roll: per_roll =
        # tgt_wt/rate + DOFF = 100/100 + 20/60 = 1h20m; 4 rolls = 5h20m after
        # _START (the last Doff.end, not the 4.875h floor-crossing point).
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        self.assertEqual(m.next_runout,
                         _START + timedelta(hours=5, minutes=20))


# --- 1.2 Per-activity-type status update --------------------------------

class ActivityStatusUpdateTests(unittest.TestCase):

    def _expect(self, status, *, as_of, current_item, is_idle, top, btm):
        """Assert a status's scalar fields and per-bar accessors. `top` /
        `btm` are `(beam, lbs_remaining, threaded)` tuples."""
        self.assertEqual(status.as_of, as_of)
        self.assertEqual(status.current_item, current_item)
        self.assertEqual(status.is_idle, is_idle)
        for bar, (beam, lbs, threaded) in (('top', top), ('btm', btm)):
            self.assertEqual(status.beam(bar), beam, f'{bar} beam')
            self.assertEqual(status.lbs_remaining(bar), lbs, f'{bar} lbs')
            self.assertEqual(status.threaded(bar), threaded,
                             f'{bar} threaded')

    def test_knit_consumes_lbs_and_sets_current_item(self):
        # 50 lbs of A: 0.4*50=20 from top, 0.6*50=30 from btm. Beams stay
        # mounted and threaded; only lbs and current_item move.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(minutes=30)
        m.add_activities([Knit(start=_START, end=end, item=_ITEM_A, lbs=50.0)])
        s = m.current_status
        self._expect(
            s, as_of=end, current_item=_ITEM_A, is_idle=True,
            top=(_TOP_BEAM, 180.0, True),
            btm=(_BTM_BEAM, 270.0, True),
        )
        self.assertEqual(s, m.status_at(end))

    def test_waste_top_empties_named_bar_and_keeps_item(self):
        # Waste('top') drops top's residue unknit: beam -> None, lbs -> 0,
        # threaded -> False; btm untouched; current_item stays A. Zero
        # duration (start == end), so as_of is unchanged.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        m.add_activities([Waste(start=_START, end=_START, beam=_TOP_BEAM,
                                bar='top', lbs=45.0)])
        s = m.current_status
        self._expect(
            s, as_of=_START, current_item=_ITEM_A, is_idle=True,
            top=(None, 0.0, False),
            btm=(_BTM_BEAM, 300.0, True),
        )
        self.assertEqual(s, m.status_at(_START))

    def test_waste_btm_empties_named_bar_and_keeps_item(self):
        # Symmetric: Waste('btm') clears btm only; top untouched.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        m.add_activities([Waste(start=_START, end=_START, beam=_BTM_BEAM,
                                bar='btm', lbs=55.0)])
        s = m.current_status
        self._expect(
            s, as_of=_START, current_item=_ITEM_A, is_idle=True,
            top=(_TOP_BEAM, 200.0, True),
            btm=(None, 0.0, False),
        )
        self.assertEqual(s, m.status_at(_START))

    def test_doff_advances_as_of_only(self):
        # Doff is fieldless machine time: as_of moves to its end; beams, lbs,
        # threaded, and current_item are all unchanged.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(minutes=20)
        m.add_activities([Doff(start=_START, end=end)])
        s = m.current_status
        self._expect(
            s, as_of=end, current_item=_ITEM_A, is_idle=True,
            top=(_TOP_BEAM, 200.0, True),
            btm=(_BTM_BEAM, 300.0, True),
        )
        self.assertEqual(s, m.status_at(end))

    def test_tape_out_top_only(self):
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(minutes=20)
        m.add_activities([TapeOut(start=_START, end=end, bars='top')])
        s = m.current_status
        self._expect(
            s, as_of=end, current_item=_ITEM_A, is_idle=True,
            top=(None, 0.0, False),
            btm=(_BTM_BEAM, 300.0, True),
        )
        self.assertEqual(s, m.status_at(end))

    def test_tape_out_btm_only(self):
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(minutes=20)
        m.add_activities([TapeOut(start=_START, end=end, bars='btm')])
        s = m.current_status
        self._expect(
            s, as_of=end, current_item=_ITEM_A, is_idle=True,
            top=(_TOP_BEAM, 200.0, True),
            btm=(None, 0.0, False),
        )
        self.assertEqual(s, m.status_at(end))

    def test_tape_out_both(self):
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(hours=1)
        m.add_activities([TapeOut(start=_START, end=end, bars='both')])
        s = m.current_status
        self._expect(
            s, as_of=end, current_item=_ITEM_A, is_idle=True,
            top=(None, 0.0, False),
            btm=(None, 0.0, False),
        )
        self.assertEqual(s, m.status_at(end))

    # Hanging / Threading require a non-initial pre-state (a removed / hung
    # bar), so build that pre-state with Status.create and exercise the pure
    # apply_activity transition. (The guard rails live in 1.3.)

    def test_hanging_top_loads_beam_unthreaded(self):
        # Removed-top pre-state: Hanging('top') loads the beam + lbs and
        # leaves it un-threaded; btm untouched; current_item unchanged.
        pre = Status.create(
            as_of=_START, current_item=_ITEM_A, is_idle=True,
            top_beam=None, top_lbs_remaining=0.0, top_threaded=False,
            btm_beam=_BTM_BEAM, btm_lbs_remaining=300.0, btm_threaded=True,
        )
        end = _START + timedelta(hours=1)
        s = pre.apply_activity(Hanging(
            start=_START, end=end, bars='top',
            top_beam=_ALT_TOP_BEAM, top_lbs=500.0,
        ))
        self._expect(
            s, as_of=end, current_item=_ITEM_A, is_idle=True,
            top=(_ALT_TOP_BEAM, 500.0, False),
            btm=(_BTM_BEAM, 300.0, True),
        )

    def test_hanging_btm_loads_beam_unthreaded(self):
        pre = Status.create(
            as_of=_START, current_item=_ITEM_A, is_idle=True,
            top_beam=_TOP_BEAM, top_lbs_remaining=200.0, top_threaded=True,
            btm_beam=None, btm_lbs_remaining=0.0, btm_threaded=False,
        )
        end = _START + timedelta(hours=1)
        s = pre.apply_activity(Hanging(
            start=_START, end=end, bars='btm',
            btm_beam=_ALT_BTM_BEAM, btm_lbs=400.0,
        ))
        self._expect(
            s, as_of=end, current_item=_ITEM_A, is_idle=True,
            top=(_TOP_BEAM, 200.0, True),
            btm=(_ALT_BTM_BEAM, 400.0, False),
        )

    def test_hanging_both_loads_both_unthreaded(self):
        pre = Status.create(
            as_of=_START, current_item=_ITEM_A, is_idle=True,
            top_beam=None, top_lbs_remaining=0.0, top_threaded=False,
            btm_beam=None, btm_lbs_remaining=0.0, btm_threaded=False,
        )
        end = _START + timedelta(hours=1)
        s = pre.apply_activity(Hanging(
            start=_START, end=end, bars='both',
            top_beam=_ALT_TOP_BEAM, top_lbs=500.0,
            btm_beam=_ALT_BTM_BEAM, btm_lbs=400.0,
        ))
        self._expect(
            s, as_of=end, current_item=_ITEM_A, is_idle=True,
            top=(_ALT_TOP_BEAM, 500.0, False),
            btm=(_ALT_BTM_BEAM, 400.0, False),
        )

    def test_threading_top_flips_threaded_only(self):
        # Hung-top pre-state (loaded, not threaded): Threading('top') flips
        # threaded -> True; beam/lbs unchanged; btm untouched.
        pre = Status.create(
            as_of=_START, current_item=_ITEM_A, is_idle=True,
            top_beam=_ALT_TOP_BEAM, top_lbs_remaining=500.0,
            top_threaded=False,
            btm_beam=_BTM_BEAM, btm_lbs_remaining=300.0, btm_threaded=True,
        )
        end = _START + timedelta(hours=1)
        s = pre.apply_activity(Threading(start=_START, end=end, bars='top'))
        self._expect(
            s, as_of=end, current_item=_ITEM_A, is_idle=True,
            top=(_ALT_TOP_BEAM, 500.0, True),
            btm=(_BTM_BEAM, 300.0, True),
        )

    def test_threading_btm_flips_threaded_only(self):
        pre = Status.create(
            as_of=_START, current_item=_ITEM_A, is_idle=True,
            top_beam=_TOP_BEAM, top_lbs_remaining=200.0, top_threaded=True,
            btm_beam=_ALT_BTM_BEAM, btm_lbs_remaining=400.0,
            btm_threaded=False,
        )
        end = _START + timedelta(hours=1)
        s = pre.apply_activity(Threading(start=_START, end=end, bars='btm'))
        self._expect(
            s, as_of=end, current_item=_ITEM_A, is_idle=True,
            top=(_TOP_BEAM, 200.0, True),
            btm=(_ALT_BTM_BEAM, 400.0, True),
        )

    def test_threading_both_flips_both(self):
        pre = Status.create(
            as_of=_START, current_item=_ITEM_A, is_idle=True,
            top_beam=_ALT_TOP_BEAM, top_lbs_remaining=500.0,
            top_threaded=False,
            btm_beam=_ALT_BTM_BEAM, btm_lbs_remaining=400.0,
            btm_threaded=False,
        )
        end = _START + timedelta(hours=1)
        s = pre.apply_activity(Threading(start=_START, end=end, bars='both'))
        self._expect(
            s, as_of=end, current_item=_ITEM_A, is_idle=True,
            top=(_ALT_TOP_BEAM, 500.0, True),
            btm=(_ALT_BTM_BEAM, 400.0, True),
        )

    def test_style_change_updates_only_current_item(self):
        # All three changeover classes share one status transition: switch
        # current_item, leave both bars (beam/lbs/threaded) untouched.
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(minutes=5)
        m.add_activities([StyleChange(start=_START, end=end,
                                      from_item=_ITEM_A, to_item=_ITEM_B)])
        s = m.current_status
        self._expect(
            s, as_of=end, current_item=_ITEM_B, is_idle=True,
            top=(_TOP_BEAM, 200.0, True),
            btm=(_BTM_BEAM, 300.0, True),
        )
        # A and B share family 'A' — current_family follows current_item.
        self.assertEqual(s.current_family, 'A')
        self.assertEqual(s, m.status_at(end))

    def test_runner_change_updates_only_current_item(self):
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(minutes=45)
        m.add_activities([RunnerChange(start=_START, end=end,
                                       from_item=_ITEM_A, to_item=_ITEM_B)])
        s = m.current_status
        self._expect(
            s, as_of=end, current_item=_ITEM_B, is_idle=True,
            top=(_TOP_BEAM, 200.0, True),
            btm=(_BTM_BEAM, 300.0, True),
        )
        self.assertEqual(s, m.status_at(end))

    def test_pattern_change_updates_item_and_family(self):
        # Cross-family changeover: current_item and current_family both move;
        # bars unchanged (A and C share yarn ids, so the state stays valid).
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(hours=1)
        m.add_activities([PatternChange(start=_START, end=end,
                                        from_item=_ITEM_A, to_item=_ITEM_C)])
        s = m.current_status
        self._expect(
            s, as_of=end, current_item=_ITEM_C, is_idle=True,
            top=(_TOP_BEAM, 200.0, True),
            btm=(_BTM_BEAM, 300.0, True),
        )
        self.assertEqual(s.current_family, 'C')
        self.assertEqual(s, m.status_at(end))

    def test_idle_advances_as_of_and_leaves_everything_else_unchanged(self):
        # Idle is a deliberate gap — beams stay threaded, lbs stay full,
        # current_item is untouched. Only as_of moves forward.
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(hours=6)
        m.add_activities([Idle(start=_START, end=end)])
        s = m.current_status
        self._expect(
            s, as_of=end, current_item=_ITEM_A, is_idle=True,
            top=(_TOP_BEAM, 200.0, True),
            btm=(_BTM_BEAM, 300.0, True),
        )
        self.assertEqual(s, m.status_at(end))

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
        self.assertEqual(s.lbs_remaining('top'), 200.0)
        self.assertEqual(s.lbs_remaining('btm'), 300.0)
        self.assertEqual(s.current_item, _ITEM_A)


# --- 1.3 add_activities sequencing --------------------------------------

class AddActivitiesSequencingTests(unittest.TestCase):

    def test_realistic_preamble_applied_in_order(self):
        # TapeOut('both') + Hanging('both') + Threading('both') + StyleChange +
        # Knit — the remove -> hang -> thread sequence with 'both' batching.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        t0 = _START
        t1 = t0 + timedelta(hours=1)        # TapeOut('both') ends
        t2 = t1 + timedelta(minutes=90)     # Hanging('both') ends
        t3 = t2 + timedelta(minutes=30)     # Threading('both') ends
        t4 = t3 + timedelta(minutes=15)     # StyleChange ends (to C)
        # Knit of 50 lbs of C at rate 50 = 1h. Consumes 0.2*50=10 top,
        # 0.8*50=40 btm.
        t5 = t4 + timedelta(hours=1)
        m.add_activities([
            TapeOut(start=t0, end=t1, bars='both'),
            Hanging(start=t1, end=t2, bars='both',
                    top_beam=_ALT_TOP_BEAM, top_lbs=400.0,
                    btm_beam=_ALT_BTM_BEAM, btm_lbs=600.0),
            Threading(start=t2, end=t3, bars='both'),
            StyleChange(start=t3, end=t4,
                        from_item=_ITEM_A, to_item=_ITEM_C),
            Knit(start=t4, end=t5, item=_ITEM_C, lbs=50.0),
        ])
        s = m.current_status
        self.assertEqual(s.beam('top'), _ALT_TOP_BEAM)
        self.assertEqual(s.beam('btm'), _ALT_BTM_BEAM)
        self.assertEqual(s.lbs_remaining('top'), 390.0)
        self.assertEqual(s.lbs_remaining('btm'), 560.0)
        self.assertTrue(s.threaded('top'))
        self.assertTrue(s.threaded('btm'))
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

    # --- beam-swap guard rails (apply_activity sequencing) ---

    def _end(self, hours=1):
        return _START + timedelta(hours=hours)

    # Hanging('top') / Hanging('btm') require the bar removed.

    def test_hanging_allowed_when_beam_is_none(self):
        pre = _status((None, 0.0, False), (_BTM_BEAM, 300.0, True))
        s = pre.apply_activity(Hanging(start=_START, end=self._end(), bars='top',
                                       top_beam=_ALT_TOP_BEAM, top_lbs=500.0))
        self.assertEqual(s.beam('top'), _ALT_TOP_BEAM)
        self.assertEqual(s.lbs_remaining('top'), 500.0)
        self.assertFalse(s.threaded('top'))

    def test_hanging_allowed_when_lbs_at_floor(self):
        # Beam still mounted but knit down to the floor -> removed.
        pre = _status((_TOP_BEAM, BEAM_FLOOR_LBS, True), (_BTM_BEAM, 300.0, True))
        s = pre.apply_activity(Hanging(start=_START, end=self._end(), bars='top',
                                       top_beam=_ALT_TOP_BEAM, top_lbs=500.0))
        self.assertEqual(s.beam('top'), _ALT_TOP_BEAM)
        self.assertFalse(s.threaded('top'))

    def test_hanging_raises_when_bar_holds_usable_set(self):
        # Full, threaded initial bar (beam present, lbs > floor) is not
        # removed -> cannot hang onto it.
        pre = _status((_TOP_BEAM, 200.0, True), (_BTM_BEAM, 300.0, True))
        with self.assertRaises(ValueError):
            pre.apply_activity(Hanging(start=_START, end=self._end(),
                                       bars='top', top_beam=_ALT_TOP_BEAM,
                                       top_lbs=500.0))

    def test_hanging_raises_when_bar_already_hung(self):
        # A second Hanging before the Threading: the bar is hung, not removed.
        pre = _status((_ALT_TOP_BEAM, 500.0, False), (_BTM_BEAM, 300.0, True))
        with self.assertRaises(ValueError):
            pre.apply_activity(Hanging(start=_START, end=self._end(),
                                       bars='top', top_beam=_ALT_TOP_BEAM,
                                       top_lbs=500.0))

    # Hanging('both') checks both bars.

    def test_hanging_both_accepted_when_both_removed(self):
        pre = _status((None, 0.0, False), (None, 0.0, False))
        s = pre.apply_activity(Hanging(start=_START, end=self._end(),
                                       bars='both',
                                       top_beam=_ALT_TOP_BEAM, top_lbs=500.0,
                                       btm_beam=_ALT_BTM_BEAM, btm_lbs=400.0))
        self.assertEqual(s.beam('top'), _ALT_TOP_BEAM)
        self.assertEqual(s.beam('btm'), _ALT_BTM_BEAM)
        self.assertFalse(s.threaded('top'))
        self.assertFalse(s.threaded('btm'))

    def _hang_both(self):
        return Hanging(start=_START, end=self._end(), bars='both',
                       top_beam=_ALT_TOP_BEAM, top_lbs=500.0,
                       btm_beam=_ALT_BTM_BEAM, btm_lbs=400.0)

    def test_hanging_both_raises_when_one_bar_has_usable_set(self):
        # Both arrangements: the guard fails on whichever bar is not removed.
        pre_top = _status((None, 0.0, False), (_BTM_BEAM, 300.0, True))
        with self.assertRaises(ValueError):
            pre_top.apply_activity(self._hang_both())
        pre_btm = _status((_TOP_BEAM, 300.0, True), (None, 0.0, False))
        with self.assertRaises(ValueError):
            pre_btm.apply_activity(self._hang_both())

    def test_hanging_both_raises_when_one_bar_hung(self):
        pre = _status((None, 0.0, False), (_ALT_BTM_BEAM, 400.0, False))
        with self.assertRaises(ValueError):
            pre.apply_activity(self._hang_both())

    # Threading('top') / Threading('btm') require the bar hung.

    def test_threading_allowed_on_hung_bar(self):
        pre = _status((_ALT_TOP_BEAM, 500.0, False), (_BTM_BEAM, 300.0, True))
        s = pre.apply_activity(Threading(start=_START, end=self._end(),
                                         bars='top'))
        self.assertTrue(s.threaded('top'))

    def test_threading_raises_when_already_threaded(self):
        pre = _status((_TOP_BEAM, 200.0, True), (_BTM_BEAM, 300.0, True))
        with self.assertRaises(ValueError):
            pre.apply_activity(Threading(start=_START, end=self._end(),
                                         bars='top'))

    def test_threading_raises_when_not_yet_hung(self):
        # Removed bar (no Hanging yet) -> not hung.
        pre = _status((None, 0.0, False), (_BTM_BEAM, 300.0, True))
        with self.assertRaises(ValueError):
            pre.apply_activity(Threading(start=_START, end=self._end(),
                                         bars='top'))

    # Threading('both') checks both bars.

    def test_threading_both_accepted_when_both_hung(self):
        pre = _status((_ALT_TOP_BEAM, 500.0, False),
                      (_ALT_BTM_BEAM, 400.0, False))
        s = pre.apply_activity(Threading(start=_START, end=self._end(),
                                         bars='both'))
        self.assertTrue(s.threaded('top'))
        self.assertTrue(s.threaded('btm'))

    def test_threading_both_raises_when_one_bar_already_threaded(self):
        pre_btm = _status((_ALT_TOP_BEAM, 500.0, False), (_BTM_BEAM, 300.0, True))
        with self.assertRaises(ValueError):
            pre_btm.apply_activity(Threading(start=_START, end=self._end(),
                                             bars='both'))
        pre_top = _status((_TOP_BEAM, 300.0, True), (_ALT_BTM_BEAM, 400.0, False))
        with self.assertRaises(ValueError):
            pre_top.apply_activity(Threading(start=_START, end=self._end(),
                                             bars='both'))

    def test_threading_both_raises_when_one_bar_removed(self):
        pre = _status((_ALT_TOP_BEAM, 500.0, False), (None, 0.0, False))
        with self.assertRaises(ValueError):
            pre.apply_activity(Threading(start=_START, end=self._end(),
                                         bars='both'))

    # Out-of-sequence multi-activity adds (via add_activities).

    def test_sequence_remove_hang_thread_succeeds(self):
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        t0 = _START
        t1 = t0 + timedelta(minutes=20)
        t2 = t1 + timedelta(hours=1)
        t3 = t2 + timedelta(hours=2)
        m.add_activities([
            TapeOut(start=t0, end=t1, bars='top'),
            Hanging(start=t1, end=t2, bars='top',
                    top_beam=_ALT_TOP_BEAM, top_lbs=500.0),
            Threading(start=t2, end=t3, bars='top'),
        ])
        s = m.current_status
        self.assertEqual(s.beam('top'), _ALT_TOP_BEAM)
        self.assertEqual(s.lbs_remaining('top'), 500.0)
        self.assertTrue(s.threaded('top'))

    def test_sequence_thread_before_hang_raises(self):
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        t0 = _START
        t1 = t0 + timedelta(minutes=20)
        t2 = t1 + timedelta(hours=2)
        with self.assertRaises(ValueError):
            m.add_activities([
                TapeOut(start=t0, end=t1, bars='top'),
                Threading(start=t1, end=t2, bars='top'),
            ])

    def test_sequence_double_hang_raises(self):
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        t0 = _START
        t1 = t0 + timedelta(minutes=20)
        t2 = t1 + timedelta(hours=1)
        t3 = t2 + timedelta(hours=1)
        with self.assertRaises(ValueError):
            m.add_activities([
                TapeOut(start=t0, end=t1, bars='top'),
                Hanging(start=t1, end=t2, bars='top',
                        top_beam=_ALT_TOP_BEAM, top_lbs=500.0),
                Hanging(start=t2, end=t3, bars='top',
                        top_beam=_ALT_TOP_BEAM, top_lbs=500.0),
            ])

    def test_sequence_post_waste_succeeds(self):
        # Waste removes the bar (beam -> None) like a TapeOut, so the same
        # remove -> hang -> thread sequence applies.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        t0 = _START
        t1 = t0 + timedelta(hours=1)
        t2 = t1 + timedelta(hours=2)
        m.add_activities([
            Waste(start=t0, end=t0, beam=_TOP_BEAM, bar='top', lbs=195.0),
            Hanging(start=t0, end=t1, bars='top',
                    top_beam=_ALT_TOP_BEAM, top_lbs=500.0),
            Threading(start=t1, end=t2, bars='top'),
        ])
        s = m.current_status
        self.assertEqual(s.beam('top'), _ALT_TOP_BEAM)
        self.assertTrue(s.threaded('top'))

    def test_sequence_post_waste_thread_before_hang_raises(self):
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        t0 = _START
        t1 = t0 + timedelta(hours=2)
        with self.assertRaises(ValueError):
            m.add_activities([
                Waste(start=t0, end=t0, beam=_TOP_BEAM, bar='top', lbs=195.0),
                Threading(start=t0, end=t1, bars='top'),
            ])

    def test_sequence_post_knit_to_floor_succeeds(self):
        # A Knit drawing top to the floor removes it. 487.5 lbs of A: top
        # 200 - 0.4*487.5 = 5.0 (== floor -> removed), btm 300 - 0.6*487.5 =
        # 7.5 (kept). Then Hanging + Threading top re-thread the spent bar.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        t0 = _START
        t1 = t0 + timedelta(hours=1)
        t2 = t1 + timedelta(hours=1)
        t3 = t2 + timedelta(hours=2)
        m.add_activities([
            Knit(start=t0, end=t1, item=_ITEM_A, lbs=487.5),
            Hanging(start=t1, end=t2, bars='top',
                    top_beam=_ALT_TOP_BEAM, top_lbs=500.0),
            Threading(start=t2, end=t3, bars='top'),
        ])
        s = m.current_status
        self.assertEqual(s.beam('top'), _ALT_TOP_BEAM)
        self.assertEqual(s.lbs_remaining('top'), 500.0)
        self.assertTrue(s.threaded('top'))


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
        self.assertEqual(s.lbs_remaining('top'), 360.0)  # 400 - 0.4*100
        self.assertEqual(s.lbs_remaining('btm'), 540.0)  # 600 - 0.6*100

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
        self.assertEqual(s.lbs_remaining('top'), 400.0)
        self.assertEqual(s.lbs_remaining('btm'), 600.0)
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
        self.assertEqual(s.lbs_remaining('top'), 360.0)
        self.assertEqual(s.lbs_remaining('btm'), 540.0)

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
        for bar in ('top', 'btm'):
            self.assertEqual(s.beam(bar), tail.beam(bar), f'{bar} beam')
            self.assertEqual(s.lbs_remaining(bar), tail.lbs_remaining(bar),
                             f'{bar} lbs')
            self.assertEqual(s.threaded(bar), tail.threaded(bar),
                             f'{bar} threaded')
        self.assertEqual(s.current_item, tail.current_item)
        self.assertEqual(s.is_idle, tail.is_idle)

    def test_status_at_before_initial_raises(self):
        m = _make_machine()
        with self.assertRaises(ValueError):
            m.status_at(_START - timedelta(hours=1))


# --- 1.5 next_runout ----------------------------------------------------

class NextRunoutTests(unittest.TestCase):

    def test_top_runs_out_first(self):
        # top=200, btm=400: usable top (200-5)/0.4=487.5, btm
        # (400-5)/0.6=658.33 -> top limits. floor(487.5/100)=4 rolls. Per-roll
        # = 100/100 + 20/60 = 1h20m; 4 rolls = 5h20m.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=400.0)
        self.assertEqual(m.next_runout,
                         _START + timedelta(hours=5, minutes=20))

    def test_btm_runs_out_first(self):
        # top=400, btm=240: usable top (400-5)/0.4=987.5, btm
        # (240-5)/0.6=391.67 -> btm limits. floor(391.67/100)=3 rolls.
        # 3 * 1h20m = 4h.
        m = _make_machine(init_top_lbs=400.0, init_btm_lbs=240.0)
        self.assertEqual(m.next_runout, _START + timedelta(hours=4))

    def test_simultaneous_runout(self):
        # top=215, btm=320: usable top (215-5)/0.4=525, btm
        # (320-5)/0.6=525 -> equal (simultaneous floor). floor(525/100)=5
        # rolls. 5 * 1h20m = 6h40m (the 5.25h floor-crossing rounds down).
        m = _make_machine(init_top_lbs=215.0, init_btm_lbs=320.0)
        self.assertEqual(m.next_runout,
                         _START + timedelta(hours=6, minutes=40))

    def test_after_whole_roll_preserves_absolute_runout(self):
        # A whole roll is a Knit + a Doff (the run-up's unit), so it advances
        # as_of by per_roll = 1h + 20min = 1h20m and drops the remaining
        # whole-roll count by one. Initial next_runout is +5h20m (4 rolls);
        # after the roll (top-=40->160, btm-=60->240, as_of=+1h20m): usable
        # min((160-5)/0.4,(240-5)/0.6)=387.5 -> floor(3.875)=3 rolls -> 4h,
        # so +1h20m + 4h = +5h20m, unchanged.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        knit_end = _START + timedelta(hours=1)
        doff_end = knit_end + timedelta(minutes=20)
        m.add_activities([
            Knit(start=_START, end=knit_end, item=_ITEM_A, lbs=100.0),
            Doff(start=knit_end, end=doff_end),
        ])
        self.assertEqual(m.next_runout,
                         _START + timedelta(hours=5, minutes=20))

    def test_after_rethread_pushes_runout_later(self):
        # TapeOut top, then re-thread top (Hanging + Threading) -> 500 lbs.
        # After: top=500, btm=300, as_of=t3. usable
        # min((500-5)/0.4,(300-5)/0.6)=min(1237.5, 491.67)=491.67 ->
        # floor(4.9167)=4 rolls. next_runout = t3 + 4*1h20m = t3 + 5h20m.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        t0 = _START
        t1 = t0 + timedelta(minutes=20)   # TapeOut top
        t2 = t1 + timedelta(hours=1)      # Hanging top
        t3 = t2 + timedelta(hours=2)      # Threading top
        m.add_activities([
            TapeOut(start=t0, end=t1, bars='top'),
            Hanging(start=t1, end=t2, bars='top',
                    top_beam=_TOP_BEAM, top_lbs=500.0),
            Threading(start=t2, end=t3, bars='top'),
        ])
        self.assertEqual(m.next_runout,
                         t3 + timedelta(hours=5, minutes=20))

    def test_after_changeover_uses_new_item_pcts_and_rate(self):
        # PatternChange A->C (cross-family on a legacy machine). C:
        # top_pct=0.2, btm_pct=0.8, rate=50, tgt_wt=150. usable
        # min((200-5)/0.2,(300-5)/0.8)=min(975,368.75)=368.75 ->
        # floor(368.75/150)=2 rolls. Per-roll = 150/50 + 20/60 = 3h20m;
        # 2 rolls = 6h40m.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0)
        end = _START + timedelta(minutes=15)
        m.add_activities([
            PatternChange(start=_START, end=end,
                          from_item=_ITEM_A, to_item=_ITEM_C),
        ])
        self.assertEqual(m.next_runout,
                         end + timedelta(hours=6, minutes=40))

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
        # floor(10/1)=10 rolls. Per-roll = 1/1 + 20/60 = 1h20m; 10 rolls =
        # 13h20m work-hours offset. offset(Mon 9:00, 13h20m): 8h fits Mon
        # (until 17:00); 5h20m remaining -> Tue 8:00 + 5h20m = Tue 13:20.
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
        self.assertEqual(m.next_runout, datetime(2026, 5, 19, 13, 20))


# ---------------------------- PHASE 2 -----------------------------------

# Cross-yarn / cross-family items. The old same-yarn + same-family
# restriction is gone (Phase 3 handles arbitrary transitions); these are
# kept for the Phase 3 changeover-preamble tests.
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
# Second large item — same yarn + family as BIG, distinct SKU. Used for the
# 'next_runout' interrupted-first-roll case, where the new item's per-bar
# roll draw (120 top / 180 btm) must exceed MAX_BEAM_WASTE_LBS so its first
# roll can straddle a mid-roll re-thread while both bars sit above the
# max-waste line.
_ITEM_BIG2 = Greige(
    'AU_BIG2', family='A', tgt_wt=300.0,
    top_beam='40D BLACK 1000X4', top_pct=0.4,
    btm_beam='60D WHITE 1000X4', btm_pct=0.6,
    safety=1000.0, machines={'M1': 100.0},
)


_CHANGEOVERS = (StyleChange, RunnerChange, PatternChange)


def _shape(plan):
    """Tuple-ize a plan's activity stream for structural comparison,
    dropping the auto-incrementing activity ids. Accepts a `ProductionPlan`
    or a raw iterable of activities. Each tuple's leading entry is the
    activity type name; remaining entries are the fields we care about per
    type. A `Hanging` carries its per-bar loaded lbs (0.0 for an untouched
    bar); a changeover carries its class name plus from/to item ids."""
    activities = getattr(plan, 'activities', plan)
    out = []
    for a in activities:
        if isinstance(a, Knit):
            out.append(('Knit', a.lbs, a.item.id))
        elif isinstance(a, Doff):
            out.append(('Doff',))
        elif isinstance(a, Waste):
            out.append(('Waste', a.bar, a.lbs, a.beam.id))
        elif isinstance(a, TapeOut):
            out.append(('TapeOut', a.bars))
        elif isinstance(a, Hanging):
            out.append(('Hanging', a.bars, a.top_lbs, a.btm_lbs))
        elif isinstance(a, Threading):
            out.append(('Threading', a.bars))
        elif isinstance(a, _CHANGEOVERS):
            out.append((type(a).__name__, a.from_item.id, a.to_item.id))
        elif isinstance(a, Idle):
            out.append(('Idle',))
        else:
            raise AssertionError(f'unknown activity type {type(a).__name__}')
    return out


def _kd(lbs, item_id):
    """Shape of one whole roll: a `Knit` of `lbs` followed by its `Doff`."""
    return [('Knit', lbs, item_id), ('Doff',)]


def _rethread(bars, top_lbs=0.0, btm_lbs=0.0):
    """Shape of a re-thread of `bars`: a `Hanging` (carrying the per-bar
    fresh lbs) then a `Threading`."""
    return [('Hanging', bars, top_lbs, btm_lbs), ('Threading', bars)]


def _knit_count(plan):
    """Number of `Knit` activities in a plan's activity stream."""
    return sum(1 for a in plan.activities if isinstance(a, Knit))


def _doff_count(plan):
    """Number of `Doff` activities in a plan's activity stream."""
    return sum(1 for a in plan.activities if isinstance(a, Doff))


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


# --- 2.1 Input acceptance — obsolete, not implemented -------------------
#
# The old same-yarn + same-family restriction (and its rejection cases) was
# lifted; plan_production now plans arbitrary transitions. The start_at
# validation that lived here moved to PlanProductionStartAtTests (§2.4).


# --- 2.2 Preamble shape (same-yarn + same-family transition) ------------

class PlanProductionPreambleTests(unittest.TestCase):

    def test_same_item_emits_no_preamble(self):
        # to_item == current_item → no preamble; only the production loop
        # (one roll = Knit + Doff).
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_A, lbs=100.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), _kd(100.0, 'AU0001'))

    def test_different_item_legacy_emits_runner_change_only(self):
        # Different item, same yarn + family, legacy machine -> exactly one
        # RunnerChange (same family => the lighter runner reconfigure, not a
        # PatternChange); no beam work.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0,
                          is_new=False)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), [
            ('RunnerChange', 'AU0001', 'AU0002'),
            *_kd(200.0, 'AU0002'),
        ])
        rc = plan.activities[0]
        self.assertEqual(rc.end - rc.start,
                         timedelta(hours=RUNNER_CHANGE_DURATION))

    def test_different_item_new_machine_emits_style_change_only(self):
        # Same transition on a new machine -> a StyleChange instead.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0,
                          is_new=True)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), [
            ('StyleChange', 'AU0001', 'AU0002'),
            *_kd(200.0, 'AU0002'),
        ])
        sc = plan.activities[0]
        self.assertEqual(sc.end - sc.start,
                         timedelta(hours=STYLE_CHANGE_DURATION))


# --- 2.3 Production loop ------------------------------------------------

class PlanProductionLoopTests(unittest.TestCase):

    def test_single_roll_no_exhaustion(self):
        # tgt_wt=100, lbs=100, beams have plenty of capacity. One roll =
        # Knit + Doff.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_A, lbs=100.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), _kd(100.0, 'AU0001'))
        _assert_single_job(self, plan, 'AU0001', 100.0, 1)
        self.assertEqual(_knit_count(plan), 1)
        self.assertEqual(_doff_count(plan), 1)

    def test_multiple_rolls_no_exhaustion(self):
        # 500 lbs = 5 rolls; beams have capacity. The loop flushes and doffs
        # at each roll boundary -> 5 Knit/Doff pairs (one Knit per roll), not
        # a single Knit for the full lbs.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_A, lbs=500.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), _kd(100.0, 'AU0001') * 5)
        _assert_single_job(self, plan, 'AU0001', 500.0, 5)
        self.assertEqual(_knit_count(plan), 5)
        self.assertEqual(_doff_count(plan), 5)

    def test_exhaust_at_roll_boundary_no_waste(self):
        # 2.3.3.1. _ITEM_BIG (tgt 300, top_pct 0.4 -> 120 yarn/roll). top=245
        # so usable_top hits exactly 0 at the 2-roll boundary (245-240-5=0);
        # it jumps the (0, MAX] window, so the gate re-threads top with NO
        # Waste. btm=3000 stays well above MAX throughout.
        m = _make_machine(init_item=_ITEM_BIG,
                          init_top_lbs=245.0, init_btm_lbs=3000.0)
        plan = m.plan_production(_ITEM_BIG, lbs=900.0,
                                 start_at='schedule_tail')
        self.assertEqual(_shape(plan), (
            _kd(300.0, 'AU_BIG') * 2
            + _rethread('top', top_lbs=2800.0)
            + _kd(300.0, 'AU_BIG')
        ))
        _assert_single_job(self, plan, 'AU_BIG', 900.0, 3)
        self.assertEqual(_knit_count(plan), 3)
        self.assertEqual(_doff_count(plan), 3)

    def test_exhaust_at_roll_boundary_coswaps_below_max_bar(self):
        # 2.3.3.2. btm=365 hits exactly 0 at the 2-roll boundary (re-thread);
        # top=305 has only 60 usable yarn there (305-240-5=60 < MAX), so the
        # gate co-swaps it -> a zero-duration Waste(top,60) alongside the
        # 'both' re-thread.
        m = _make_machine(init_item=_ITEM_BIG,
                          init_top_lbs=305.0, init_btm_lbs=365.0)
        plan = m.plan_production(_ITEM_BIG, lbs=900.0,
                                 start_at='schedule_tail')
        self.assertEqual(_shape(plan), (
            _kd(300.0, 'AU_BIG') * 2
            + [('Waste', 'top', 60.0, '40D BLACK 1000X4')]
            + _rethread('both', top_lbs=2800.0, btm_lbs=1800.0)
            + _kd(300.0, 'AU_BIG')
        ))
        # The Waste lbs are not part of the Job.
        _assert_single_job(self, plan, 'AU_BIG', 900.0, 3)
        self.assertEqual(_knit_count(plan), 3)
        self.assertEqual(_doff_count(plan), 3)

    def test_exhaust_mid_roll_single_rethread(self):
        # 2.3.4.1 straddle (also the §2.3.5 single-btm case). btm=305 hits
        # the floor 200 lbs into roll 2; top=3000 stays above MAX, so only
        # btm re-threads and the roll completes on the fresh beam as one
        # whole roll (one Doff) -- no Waste.
        m = _make_machine(init_item=_ITEM_BIG,
                          init_top_lbs=3000.0, init_btm_lbs=305.0)
        plan = m.plan_production(_ITEM_BIG, lbs=900.0,
                                 start_at='schedule_tail')
        self.assertEqual(_shape(plan), (
            _kd(300.0, 'AU_BIG')                       # roll 1
            + [('Knit', 200.0, 'AU_BIG')]              # roll 2, pre-swap
            + _rethread('btm', btm_lbs=1800.0)
            + [('Knit', 100.0, 'AU_BIG'), ('Doff',)]   # roll 2 completes
            + _kd(300.0, 'AU_BIG')                      # roll 3
        ))
        _assert_single_job(self, plan, 'AU_BIG', 900.0, 3)
        self.assertEqual(_knit_count(plan), 4)
        self.assertEqual(_doff_count(plan), 3)

    def test_exhaust_mid_roll_double_rethread_coswap(self):
        # 2.3.4.2 (other bar below MAX). btm=305 floors 200 lbs into roll 2;
        # top=255 has 50 usable yarn there (50 < MAX), so the runout co-swaps
        # top -> Waste(top,50) + a 'both' re-thread.
        m = _make_machine(init_item=_ITEM_BIG,
                          init_top_lbs=255.0, init_btm_lbs=305.0)
        plan = m.plan_production(_ITEM_BIG, lbs=900.0,
                                 start_at='schedule_tail')
        self.assertEqual(_shape(plan), (
            _kd(300.0, 'AU_BIG')
            + [('Knit', 200.0, 'AU_BIG'),
               ('Waste', 'top', 50.0, '40D BLACK 1000X4')]
            + _rethread('both', top_lbs=2800.0, btm_lbs=1800.0)
            + [('Knit', 100.0, 'AU_BIG'), ('Doff',)]
            + _kd(300.0, 'AU_BIG')
        ))
        _assert_single_job(self, plan, 'AU_BIG', 900.0, 3)
        self.assertEqual(_knit_count(plan), 4)
        self.assertEqual(_doff_count(plan), 3)

    def test_exhaust_mid_roll_both_bars_simultaneously(self):
        # 2.3.4.2 (both at floor mid-roll). top=235, btm=350 both reach the
        # floor 275 lbs into roll 2. A 'both' re-thread, no Waste.
        m = _make_machine(init_item=_ITEM_BIG,
                          init_top_lbs=235.0, init_btm_lbs=350.0)
        plan = m.plan_production(_ITEM_BIG, lbs=900.0,
                                 start_at='schedule_tail')
        self.assertEqual(_shape(plan), (
            _kd(300.0, 'AU_BIG')
            + [('Knit', 275.0, 'AU_BIG')]
            + _rethread('both', top_lbs=2800.0, btm_lbs=1800.0)
            + [('Knit', 25.0, 'AU_BIG'), ('Doff',)]
            + _kd(300.0, 'AU_BIG')
        ))
        _assert_single_job(self, plan, 'AU_BIG', 900.0, 3)
        self.assertEqual(_knit_count(plan), 4)
        self.assertEqual(_doff_count(plan), 3)

    def test_both_bars_exhaust_simultaneously_at_boundary(self):
        # 2.3.6. top=245, btm=365 both hit exactly 0 at the 2-roll boundary.
        # A 'both' re-thread, no Waste (both at the floor, nothing above it
        # to discard).
        m = _make_machine(init_item=_ITEM_BIG,
                          init_top_lbs=245.0, init_btm_lbs=365.0)
        plan = m.plan_production(_ITEM_BIG, lbs=900.0,
                                 start_at='schedule_tail')
        self.assertEqual(_shape(plan), (
            _kd(300.0, 'AU_BIG') * 2
            + _rethread('both', top_lbs=2800.0, btm_lbs=1800.0)
            + _kd(300.0, 'AU_BIG')
        ))
        _assert_single_job(self, plan, 'AU_BIG', 900.0, 3)
        self.assertEqual(_knit_count(plan), 3)
        self.assertEqual(_doff_count(plan), 3)

    def test_cascading_exhaustion_loops_more_than_twice(self):
        # 2.3.7. top=365, btm=365: btm floors at the 2-roll boundary
        # (re-thread btm), then top floors at the next boundary (re-thread
        # top). Clean boundaries throughout, so no Waste.
        m = _make_machine(init_item=_ITEM_BIG,
                          init_top_lbs=365.0, init_btm_lbs=365.0)
        plan = m.plan_production(_ITEM_BIG, lbs=1200.0,
                                 start_at='schedule_tail')
        self.assertEqual(_shape(plan), (
            _kd(300.0, 'AU_BIG') * 2
            + _rethread('btm', btm_lbs=1800.0)
            + _kd(300.0, 'AU_BIG')
            + _rethread('top', top_lbs=2800.0)
            + _kd(300.0, 'AU_BIG')
        ))
        _assert_single_job(self, plan, 'AU_BIG', 1200.0, 4)
        self.assertEqual(_knit_count(plan), 4)
        self.assertEqual(_doff_count(plan), 4)


# --- 2.4 start_at mode behavior -----------------------------------------

class PlanProductionStartAtTests(unittest.TestCase):

    def test_invalid_start_at_raises_value_error(self):
        m = _make_machine()
        with self.assertRaises(ValueError):
            m.plan_production(_ITEM_A, lbs=100.0, start_at='bogus')

    def test_schedule_tail_no_run_up(self):
        # No current-item Jobs ahead of the changeover; first activity is the
        # changeover (legacy machine, same family -> RunnerChange).
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_B, lbs=200.0,
                                 start_at='schedule_tail')
        self.assertEqual(_shape(plan), [
            ('RunnerChange', 'AU0001', 'AU0002'),
            *_kd(200.0, 'AU0002'),
        ])
        self.assertEqual(plan.activities[0].start, m.current_status.as_of)
        # schedule_tail mode: exactly one Job (the new item).
        _assert_single_job(self, plan, 'AU0002', 200.0, 1)

    def test_next_runout_clean_roll_boundary(self):
        # Sub-case 1: the previous item's beams hold an EXACT whole-roll
        # multiple, so the last run-up roll drains the limiting bar to the
        # floor and the spent bar is re-threaded in the PREAMBLE -> the new
        # item's first roll starts on a fresh beam with no partial wound.
        # A: top=205 -> usable (205-5)/0.4=500 = 5 rolls; btm=305 ->
        # (305-5)/0.6=500 = 5 rolls (both floor simultaneously). After the
        # run-up both bars sit at the floor (top=btm=5), so the preamble
        # re-threads 'both' then changes over; B (tgt 200) then knits 2 clean
        # rolls on the fresh beams.
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=205.0, init_btm_lbs=305.0)
        plan = m.plan_production(_ITEM_B, lbs=400.0, start_at='next_runout')
        self.assertEqual(_shape(plan), (
            _kd(100.0, 'AU0001') * 5                       # run-up: 5 rolls A
            + _rethread('both', top_lbs=2800.0, btm_lbs=1800.0)
            + [('RunnerChange', 'AU0001', 'AU0002')]
            + _kd(200.0, 'AU0002') * 2                     # 2 clean rolls of B
        ))
        # Two Jobs: run-up Job (A) then the new item's Job (B).
        self.assertEqual([(j.item.id, j.total_rolls, j.total_lbs)
                          for j in plan.jobs],
                         [('AU0001', 5, 500.0), ('AU0002', 2, 400.0)])
        # The run-up itself produced no Waste / beam work before the
        # changeover; the re-thread is the preamble's.
        co_idx = next(i for i, a in enumerate(plan.activities)
                      if isinstance(a, _CHANGEOVERS))
        run_up = plan.activities[:co_idx]
        self.assertFalse(any(isinstance(a, (Waste, Hanging, Threading))
                             for a in run_up[:10]))  # the 5 Knit/Doff pairs

    def test_next_runout_interrupted_first_roll(self):
        # Sub-case 2: the last run-up roll exhausts NO bar -- both stay above
        # MAX_BEAM_WASTE_LBS (so neither re-threads in the preamble and the
        # pre-roll gate does not pre-swap) but with less than one whole
        # next-item roll of usable yarn. The new item's FIRST roll straddles
        # a mid-roll re-thread. Current BIG (tgt 300): top=355 ->
        # usable (355-5)/0.4=875 = 2 rolls (limits); btm=2000 has slack.
        # After 2 rolls: top=115 (usable 110: >MAX 100 but < the 120 a BIG2
        # top-roll needs), btm=1640. Preamble keeps both (matching yarn) and
        # emits only the changeover; BIG2's first roll winds 275 lbs, top
        # floors, top re-threads, then 25 lbs finish the roll.
        m = _make_machine(init_item=_ITEM_BIG,
                          init_top_lbs=355.0, init_btm_lbs=2000.0)
        plan = m.plan_production(_ITEM_BIG2, lbs=600.0,
                                 start_at='next_runout')
        self.assertEqual(_shape(plan), (
            _kd(300.0, 'AU_BIG') * 2                       # run-up: 2 rolls
            + [('RunnerChange', 'AU_BIG', 'AU_BIG2')]      # preamble: no beam work
            + [('Knit', 275.0, 'AU_BIG2')]                 # first roll, pre-swap
            + _rethread('top', top_lbs=2800.0)
            + [('Knit', 25.0, 'AU_BIG2'), ('Doff',)]       # first roll completes
            + _kd(300.0, 'AU_BIG2')                        # second roll
        ))
        self.assertEqual([(j.item.id, j.total_rolls, j.total_lbs)
                          for j in plan.jobs],
                         [('AU_BIG', 2, 600.0), ('AU_BIG2', 2, 600.0)])
        # No beam work in the preamble: both bars stayed above the floor and
        # matched, so nothing is re-threaded before the first BIG2 Knit.
        co_idx = next(i for i, a in enumerate(plan.activities)
                      if isinstance(a, _CHANGEOVERS))
        first_knit_after = next(i for i, a in enumerate(plan.activities)
                                if i > co_idx and isinstance(a, Knit))
        self.assertFalse(any(
            isinstance(a, (Hanging, Threading, Waste))
            for a in plan.activities[co_idx:first_knit_after]
        ))

    def test_next_runout_run_up_below_one_roll_yields_one_job(self):
        # Current item A (tgt 100). producible = (16-5)/0.4 = 27.5 fabric
        # lbs < tgt_wt, so the run-up makes no whole roll: it emits NOTHING
        # (no Knit, no Doff, no Waste) and creates no run-up Job. Exactly one
        # Job is produced -- the new item's. (The leftover top beam is
        # swapped later, inside B's production loop.)
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=16.0, init_btm_lbs=2000.0)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='next_runout')
        # The run-up emitted nothing before the changeover.
        co_idx = next(i for i, a in enumerate(plan.activities)
                      if isinstance(a, _CHANGEOVERS))
        self.assertFalse(any(
            isinstance(a, (Knit, Doff, Waste))
            for a in plan.activities[:co_idx]
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

        committed = m_plan.current_status
        self.assertEqual(committed.as_of, manual_status.as_of)
        self.assertEqual(committed.current_item, manual_status.current_item)
        self.assertEqual(committed.is_idle, manual_status.is_idle)
        for bar in ('top', 'btm'):
            self.assertEqual(committed.beam(bar), manual_status.beam(bar),
                             f'{bar} beam')
            self.assertEqual(committed.lbs_remaining(bar),
                             manual_status.lbs_remaining(bar), f'{bar} lbs')
            self.assertEqual(committed.threaded(bar),
                             manual_status.threaded(bar), f'{bar} threaded')
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

    def test_knit_duration_matches_rate(self):
        # 200 lbs of B at rate 100 lbs/h → 2h. (One roll, so one Knit.)
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='schedule_tail')
        knit = next(a for a in plan.activities if isinstance(a, Knit))
        self.assertEqual(knit.end - knit.start, timedelta(hours=2))

    def test_doff_duration_matches_module_constant(self):
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_A, lbs=100.0, start_at='schedule_tail')
        doff = next(a for a in plan.activities if isinstance(a, Doff))
        self.assertEqual(doff.end - doff.start,
                         timedelta(hours=DOFF_DURATION))

    def test_runner_change_duration_legacy_machine(self):
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0,
                          is_new=False)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='schedule_tail')
        rc = next(a for a in plan.activities if isinstance(a, RunnerChange))
        self.assertEqual(rc.end - rc.start,
                         timedelta(hours=RUNNER_CHANGE_DURATION))

    def test_style_change_duration_new_machine(self):
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0,
                          is_new=True)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='schedule_tail')
        sc = next(a for a in plan.activities if isinstance(a, StyleChange))
        self.assertEqual(sc.end - sc.start,
                         timedelta(hours=STYLE_CHANGE_DURATION))

    def test_single_rethread_durations(self):
        # A mid-roll single-bar (btm) re-thread: Hanging then Threading, each
        # at the single-bar duration constant.
        m = _make_machine(init_item=_ITEM_BIG,
                          init_top_lbs=3000.0, init_btm_lbs=305.0)
        plan = m.plan_production(_ITEM_BIG, lbs=900.0,
                                 start_at='schedule_tail')
        hang = next(a for a in plan.activities if isinstance(a, Hanging))
        thread = next(a for a in plan.activities if isinstance(a, Threading))
        self.assertEqual(hang.end - hang.start,
                         timedelta(hours=HANGING_SINGLE_DURATION))
        self.assertEqual(thread.end - thread.start,
                         timedelta(hours=THREADING_SINGLE_DURATION))

    def test_both_rethread_durations(self):
        # A simultaneous 'both' re-thread uses the 'both' duration constants.
        m = _make_machine(init_item=_ITEM_BIG,
                          init_top_lbs=245.0, init_btm_lbs=365.0)
        plan = m.plan_production(_ITEM_BIG, lbs=900.0,
                                 start_at='schedule_tail')
        hang = next(a for a in plan.activities if isinstance(a, Hanging))
        thread = next(a for a in plan.activities if isinstance(a, Threading))
        self.assertEqual(hang.bars, 'both')
        self.assertEqual(hang.end - hang.start,
                         timedelta(hours=HANGING_BOTH_DURATION))
        self.assertEqual(thread.end - thread.start,
                         timedelta(hours=THREADING_BOTH_DURATION))

    def test_activity_end_respects_workcal_gap(self):
        # Weekday 8-17 workcal; _START is Mon 9:00. Request 1000 lbs of A
        # (10 rolls) at rate 100. Each roll = 1h Knit + 20min Doff = 80min;
        # 6 rolls fill Mon 9:00-17:00 (480min), rolls 7-10 run Tue from 8:00
        # (4*80=320min) -> last Doff ends Tue 13:20.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0,
                          workcal=_WEEKDAY_9H)
        plan = m.plan_production(_ITEM_A, lbs=1000.0,
                                 start_at='schedule_tail')
        self.assertEqual(plan.activities[0].start, _START)
        self.assertEqual(plan.activities[-1].end, datetime(2026, 5, 19, 13, 20))


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
        # First is Idle; second is the changeover (legacy -> RunnerChange).
        self.assertIsInstance(plan.activities[0], Idle)
        self.assertIsInstance(plan.activities[1], RunnerChange)

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

# --- 3.1 Changeover preamble — per-bar resolution -----------------------

class PlanProductionChangeoverShapeTests(unittest.TestCase):
    # All on a legacy machine (default): same-family changeovers emit a
    # RunnerChange, cross-family a PatternChange.

    def test_different_top_yarn_same_family(self):
        # current A → D: top yarn differs (30D RED), btm yarn matches.
        # TapeOut('top') + re-thread top + RunnerChange (same family).
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_D, lbs=100.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), (
            [('TapeOut', 'top')]
            + _rethread('top', top_lbs=2800.0)
            + [('RunnerChange', 'AU0001', 'AU0004')]
            + _kd(100.0, 'AU0004')
        ))

    def test_different_btm_yarn_same_family(self):
        # current A → E: btm yarn differs (90D GREEN), top yarn matches.
        # TapeOut('btm') + re-thread btm + RunnerChange.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_E, lbs=100.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), (
            [('TapeOut', 'btm')]
            + _rethread('btm', btm_lbs=1800.0)
            + [('RunnerChange', 'AU0001', 'AU0005')]
            + _kd(100.0, 'AU0005')
        ))

    def test_different_yarn_on_both_bars_same_family(self):
        # current A → G: both yarns differ, same family A. One TapeOut('both')
        # + a single 'both' re-thread + RunnerChange.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_G, lbs=100.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), (
            [('TapeOut', 'both')]
            + _rethread('both', top_lbs=2800.0, btm_lbs=1800.0)
            + [('RunnerChange', 'AU0001', 'AU0007')]
            + _kd(100.0, 'AU0007')
        ))

    def test_same_yarn_different_family(self):
        # current A → C: same yarn on both bars, cross-family. PatternChange
        # only (legacy cross-family); no beam work.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_C, lbs=150.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), (
            [('PatternChange', 'AU0001', 'AU0003')]
            + _kd(150.0, 'AU0003')
        ))

    def test_different_top_yarn_different_family(self):
        # current A → H: top yarn differs, btm matches, cross-family Q.
        # TapeOut('top') + re-thread top + PatternChange.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_H, lbs=100.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), (
            [('TapeOut', 'top')]
            + _rethread('top', top_lbs=2800.0)
            + [('PatternChange', 'AU0001', 'AU0008')]
            + _kd(100.0, 'AU0008')
        ))

    def test_different_yarn_on_both_bars_different_family(self):
        # current A → F: both yarns differ, cross-family Q.
        # TapeOut('both') + 'both' re-thread + PatternChange.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_F, lbs=100.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), (
            [('TapeOut', 'both')]
            + _rethread('both', top_lbs=2800.0, btm_lbs=1800.0)
            + [('PatternChange', 'AU0001', 'AU0006')]
            + _kd(100.0, 'AU0006')
        ))

    def test_mismatched_bar_below_max_is_wasted(self):
        # 3.1.3. A -> D (top yarn differs 30D, btm matches 60D). top has only
        # 50 lbs -> usable 45 <= MAX_BEAM_WASTE_LBS, so its mismatched residue
        # is discarded as a zero-duration Waste(top,45) rather than preserved
        # with a TapeOut. The Waste is attributed to the outgoing yarn (40D).
        m = _make_machine(init_top_lbs=50.0, init_btm_lbs=2800.0)
        plan = m.plan_production(_ITEM_D, lbs=100.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), (
            [('Waste', 'top', 45.0, '40D BLACK 1000X4')]
            + _rethread('top', top_lbs=2800.0)
            + [('RunnerChange', 'AU0001', 'AU0004')]
            + _kd(100.0, 'AU0004')
        ))

    def test_empty_bar_gets_rethread_only(self):
        # 3.1.4. A -> D, top at the floor (5 lbs -> usable 0). An empty/at-
        # floor bar is re-threaded with NO TapeOut and NO Waste (nothing
        # worth preserving or discarding). btm matches -> kept.
        m = _make_machine(init_top_lbs=5.0, init_btm_lbs=2800.0)
        plan = m.plan_production(_ITEM_D, lbs=100.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), (
            _rethread('top', top_lbs=2800.0)
            + [('RunnerChange', 'AU0001', 'AU0004')]
            + _kd(100.0, 'AU0004')
        ))

    def test_mixed_tape_out_and_waste_no_both(self):
        # 3.1.6. A -> G (both yarns differ). top is full (usable > MAX) so it
        # tapes out to preserve; btm has only 50 lbs (usable 45 <= MAX) so it
        # wastes. Only one bar tapes -> single TapeOut('top'), NOT 'both';
        # both bars re-thread together.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=50.0)
        plan = m.plan_production(_ITEM_G, lbs=100.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), (
            [('TapeOut', 'top'),
             ('Waste', 'btm', 45.0, '60D WHITE 1000X4')]
            + _rethread('both', top_lbs=2800.0, btm_lbs=1800.0)
            + [('RunnerChange', 'AU0001', 'AU0007')]
            + _kd(100.0, 'AU0007')
        ))

    def test_matching_near_empty_bar_kept_then_swapped_in_loop(self):
        # 3.1.7. A -> E (top matches 40D, btm differs 90D). top has only 50
        # lbs but its yarn MATCHES E, so the preamble keeps it (no Waste, no
        # TapeOut) -- the near-empty swap is deferred to the production
        # loop's pre-roll gate, which then wastes it. btm (mismatched, full)
        # tapes out in the preamble.
        m = _make_machine(init_top_lbs=50.0, init_btm_lbs=2800.0)
        plan = m.plan_production(_ITEM_E, lbs=100.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), (
            [('TapeOut', 'btm')]                 # preamble: btm mismatched/full
            + _rethread('btm', btm_lbs=1800.0)
            + [('RunnerChange', 'AU0001', 'AU0005')]
            + [('Waste', 'top', 45.0, '40D BLACK 1000X4')]  # loop: matching near-empty top
            + _rethread('top', top_lbs=2800.0)
            + _kd(100.0, 'AU0005')
        ))


# --- 3.2 'next_runout' with non-trivial changeovers ---------------------

class PlanProductionNextRunoutChangeoverTests(unittest.TestCase):

    def test_both_bars_mismatched_above_max_tape_out_both(self):
        # 3.2.1 -- the headline case the OLD drain-to-empty model made
        # impossible. Current _ITEM_BIG (tgt 300) run up from 485/665:
        # usable min((485-5)/0.4, (665-5)/0.6)=min(1200,1100)=1100 ->
        # floor(1100/300)=3 rolls. Both bars are left with 125 lbs
        # (usable 120 > MAX) of MISMATCHED yarn (BIG is 40D/60D, F is
        # 30D/90D), so the preamble tapes BOTH out together -> TapeOut('both')
        # IS reachable in next_runout mode. BIG -> F is cross-family
        # (A -> Q) on a legacy machine -> PatternChange.
        m = _make_machine(init_item=_ITEM_BIG,
                          init_top_lbs=485.0, init_btm_lbs=665.0)
        plan = m.plan_production(_ITEM_F, lbs=100.0, start_at='next_runout')
        self.assertEqual(_shape(plan), (
            _kd(300.0, 'AU_BIG') * 3             # run-up: 3 whole rolls
            + [('TapeOut', 'both')]
            + _rethread('both', top_lbs=2800.0, btm_lbs=1800.0)
            + [('PatternChange', 'AU_BIG', 'AU0006')]
            + _kd(100.0, 'AU0006')
        ))
        self.assertEqual([(j.item.id, j.total_rolls, j.total_lbs)
                          for j in plan.jobs],
                         [('AU_BIG', 3, 900.0), ('AU0006', 1, 100.0)])

    def test_limiting_bar_wasted_other_bar_taped(self):
        # 3.2.2. A (tgt 100) run up from 200/2000 -> 4 rolls (400 lbs),
        # leaving top=40 (usable 35) and btm=1760 (usable 1755). A -> G both
        # yarns differ (same family): the limiting top (usable 35 <= MAX) is
        # wasted, while the full btm (usable 1755 > MAX) is preserved with a
        # single TapeOut('btm'); both re-thread together.
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=200.0, init_btm_lbs=2000.0)
        plan = m.plan_production(_ITEM_G, lbs=100.0, start_at='next_runout')
        self.assertEqual(_shape(plan), (
            _kd(100.0, 'AU0001') * 4
            + [('TapeOut', 'btm'),                       # other bar preserved
               ('Waste', 'top', 35.0, '40D BLACK 1000X4')]  # limiting bar discarded
            + _rethread('both', top_lbs=2800.0, btm_lbs=1800.0)
            + [('RunnerChange', 'AU0001', 'AU0007')]
            + _kd(100.0, 'AU0007')
        ))

    def test_one_bar_matches_is_kept(self):
        # 3.2.3. A -> D (btm yarn matches 60D, top differs, same family). Run
        # up 200/2000 -> 4 rolls; top leftover (usable 35, mismatched) is
        # wasted and re-threaded, btm leftover (matching) is kept.
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=200.0, init_btm_lbs=2000.0)
        plan = m.plan_production(_ITEM_D, lbs=100.0, start_at='next_runout')
        self.assertEqual(_shape(plan), (
            _kd(100.0, 'AU0001') * 4
            + [('Waste', 'top', 35.0, '40D BLACK 1000X4')]
            + _rethread('top', top_lbs=2800.0)
            + [('RunnerChange', 'AU0001', 'AU0004')]
            + _kd(100.0, 'AU0004')
        ))

    def test_leftover_bar_at_floor_gets_rethread_only(self):
        # 3.2.4. top=205 makes the run-up land top exactly at the floor:
        # usable (205-5)/0.4=500 = 5 whole rolls; after, top=5 (usable 0).
        # A -> D: the at-floor top is re-threaded with NO Waste (nothing above
        # the floor to discard); btm matches and is kept.
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=205.0, init_btm_lbs=2000.0)
        plan = m.plan_production(_ITEM_D, lbs=100.0, start_at='next_runout')
        self.assertEqual(_shape(plan), (
            _kd(100.0, 'AU0001') * 5             # 5 whole rolls
            + _rethread('top', top_lbs=2800.0)   # at-floor re-thread, no Waste
            + [('RunnerChange', 'AU0001', 'AU0004')]
            + _kd(100.0, 'AU0004')
        ))

    def test_run_up_emits_whole_rolls_and_no_waste(self):
        # 3.2.6 regression. The run-up is exactly whole rolls of the current
        # item, each a Knit + Doff, with no Waste/beam work interleaved; all
        # leftover-yarn handling is the preamble's job (here a Waste +
        # re-thread of the mismatched top, which begins only after the
        # run-up). Isolate the run-up as the leading Knit(A)/Doff run.
        m = _make_machine(init_item=_ITEM_A,
                          init_top_lbs=200.0, init_btm_lbs=2000.0)
        plan = m.plan_production(_ITEM_D, lbs=100.0, start_at='next_runout')
        run_up = []
        for a in plan.activities:
            if (isinstance(a, Knit) and a.item is _ITEM_A) or isinstance(a, Doff):
                run_up.append(a)
            else:
                break
        knits = [a for a in run_up if isinstance(a, Knit)]
        self.assertTrue(knits)
        self.assertTrue(all(k.lbs == _ITEM_A.tgt_wt for k in knits))
        run_up_job = plan.jobs[0]
        self.assertEqual(run_up_job.item.id, 'AU0001')
        self.assertTrue(all(r.lbs == _ITEM_A.tgt_wt for r in run_up_job.rolls))
        # Each whole roll is exactly one Knit + one Doff with nothing
        # interleaved -- a stray Waste/beam activity would shorten this run.
        self.assertEqual(len(knits), run_up_job.total_rolls)
        self.assertEqual(len(run_up), 2 * run_up_job.total_rolls)

    def test_changeover_type_matches_family_comparison(self):
        # next_runout into a cross-family item (same yarn) -> PatternChange on
        # a legacy machine; into a same-family item -> RunnerChange.
        m_cross = _make_machine(init_item=_ITEM_A,
                                init_top_lbs=200.0, init_btm_lbs=2000.0)
        plan_cross = m_cross.plan_production(_ITEM_C, lbs=150.0,
                                             start_at='next_runout')
        self.assertTrue(any(isinstance(a, PatternChange)
                            for a in plan_cross.activities))
        self.assertFalse(any(isinstance(a, (StyleChange, RunnerChange))
                             for a in plan_cross.activities))
        m_same = _make_machine(init_item=_ITEM_A,
                               init_top_lbs=200.0, init_btm_lbs=2000.0)
        plan_same = m_same.plan_production(_ITEM_B, lbs=200.0,
                                           start_at='next_runout')
        self.assertTrue(any(isinstance(a, RunnerChange)
                            for a in plan_same.activities))
        self.assertFalse(any(isinstance(a, (StyleChange, PatternChange))
                             for a in plan_same.activities))


# --- 3.3 Changeover type and duration -----------------------------------

class PlanProductionChangeoverTypeTests(unittest.TestCase):
    """The changeover class is selected by `is_new` + the pattern-family
    comparison; each class uses its own module-level duration constant."""

    def _changeover(self, plan):
        return next(a for a in plan.activities if isinstance(a, _CHANGEOVERS))

    def test_is_new_attribute_round_trip(self):
        self.assertFalse(_make_machine().is_new)
        self.assertTrue(_make_machine(is_new=True).is_new)

    def test_new_machine_same_family_style_change(self):
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0,
                          is_new=True)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='schedule_tail')
        co = self._changeover(plan)
        self.assertIsInstance(co, StyleChange)
        self.assertEqual(co.end - co.start,
                         timedelta(hours=STYLE_CHANGE_DURATION))

    def test_new_machine_cross_family_still_style_change(self):
        # A new machine emits StyleChange regardless of the family change.
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0,
                          is_new=True)
        plan = m.plan_production(_ITEM_C, lbs=150.0, start_at='schedule_tail')
        co = self._changeover(plan)
        self.assertIsInstance(co, StyleChange)
        self.assertEqual(co.end - co.start,
                         timedelta(hours=STYLE_CHANGE_DURATION))

    def test_legacy_same_family_runner_change(self):
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0,
                          is_new=False)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='schedule_tail')
        co = self._changeover(plan)
        self.assertIsInstance(co, RunnerChange)
        self.assertEqual(co.end - co.start,
                         timedelta(hours=RUNNER_CHANGE_DURATION))

    def test_legacy_cross_family_pattern_change(self):
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0,
                          is_new=False)
        plan = m.plan_production(_ITEM_C, lbs=150.0, start_at='schedule_tail')
        co = self._changeover(plan)
        self.assertIsInstance(co, PatternChange)
        self.assertEqual(co.end - co.start,
                         timedelta(hours=PATTERN_CHANGE_DURATION))


# --- 3.4 TapeOut duration -----------------------------------------------

class PlanProductionTapeOutDurationTests(unittest.TestCase):

    def test_single_tape_out_uses_single_duration(self):
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_D, lbs=100.0, start_at='schedule_tail')
        to = next(a for a in plan.activities if isinstance(a, TapeOut))
        self.assertEqual(to.bars, 'top')
        self.assertEqual(to.end - to.start,
                         timedelta(hours=TAPE_OUT_SINGLE_DURATION))

    def test_both_tape_out_uses_both_duration(self):
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_F, lbs=100.0, start_at='schedule_tail')
        to = next(a for a in plan.activities if isinstance(a, TapeOut))
        self.assertEqual(to.bars, 'both')
        self.assertEqual(to.end - to.start,
                         timedelta(hours=TAPE_OUT_BOTH_DURATION))


# --- 3.5 Regression: Phase 2 cases still match --------------------------

class PlanProductionPhase2RegressionTests(unittest.TestCase):
    """Previously-accepted same-yarn + same-family inputs still emit the
    same activity sequence under the complete `plan_production`."""

    def test_same_item_no_preamble(self):
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_A, lbs=300.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), _kd(100.0, 'AU0001') * 3)

    def test_same_yarn_same_family_changeover_only(self):
        m = _make_machine(init_top_lbs=2800.0, init_btm_lbs=1800.0)
        plan = m.plan_production(_ITEM_B, lbs=200.0, start_at='schedule_tail')
        self.assertEqual(_shape(plan), [
            ('RunnerChange', 'AU0001', 'AU0002'),
            *_kd(200.0, 'AU0002'),
        ])


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
        # Huge beams, 24/7 workcal. Each whole roll costs its knit time plus a
        # Doff: 1h + 20min = 4/3h per roll. 168h / (4/3h) = 126 rolls ->
        # 12600 lbs (the per-roll Doff is why this isn't the raw 168×100).
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=_W21_START)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_A, *_W21), 12600.0)

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
        # beam swaps. Each roll now also costs a Doff (1/3h), and each swap is
        # a re-thread (Hanging + Threading) rather than a single BeamLoad, so
        # fewer whole rolls fit than under the old model: 11200 lbs.
        m = _make_machine(init_top_lbs=200.0, init_btm_lbs=300.0,
                          start=_W21_START)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_A, *_W21), 11200.0)


# --- 4.2 Preamble required ----------------------------------------------

class ProducibleLbsPreambleTests(unittest.TestCase):

    def test_preamble_fits_and_leaves_time(self):
        # Current = A, request B (same yarn, same family) -> a single
        # RunnerChange (legacy machine) of 45min, no beam work. After it, B is
        # produced one roll at a time, each 2h knit (200 lbs at 100/h) + 20min
        # Doff = 7/3h per roll. 71 whole rolls fit before week_end -> 71 × 200
        # = 14200 lbs.
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=_W21_START)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_B, *_W21), 14200.0)

    def test_preamble_alone_exceeds_window_returns_zero(self):
        # as_of 3h before week_end. Preamble for A → F (different yarn on both
        # bars, cross-family) = TapeOut('both', 3h) + re-thread both
        # (Hanging 1.5h + Threading 3.5h) + PatternChange (1.5h) = 9.5h. Far
        # exceeds the 3h window.
        as_of = _W21_END - timedelta(hours=3)
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=as_of)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_F, *_W21), 0.0)

    def test_preamble_fits_but_no_full_roll_returns_zero(self):
        # as_of 1.5h before week_end. A → C is cross-family with same yarn, so
        # the preamble is just a PatternChange (1.5h) with no beam work. That
        # exactly fills the 1.5h window, leaving no time to knit a roll.
        as_of = _W21_END - timedelta(hours=1, minutes=30)
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=as_of)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_C, *_W21), 0.0)


# --- 4.3 Workcal alignment ----------------------------------------------

class ProducibleLbsWorkcalAlignmentTests(unittest.TestCase):

    def test_as_of_before_week_starts(self):
        # as_of one day before week_start (Sun before W21). With 24/7 workcal
        # the implicit idle bridges 24h, then the full 168h production window.
        # Result equals the as_of == week_start case: 126 rolls -> 12600 lbs.
        as_of = _W21_START - timedelta(days=1)
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=as_of)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_A, *_W21), 12600.0)

    def test_as_of_strictly_inside_week(self):
        # as_of = Wed 12:00 of W21. Window: Wed 12:00 → next Mon 00:00 =
        # 108h. 108h / (4/3h per roll) = 81 rolls -> 8100 lbs (huge beams,
        # no preamble).
        as_of = datetime(2026, 5, 20, 12, 0)   # Wed of W21
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=as_of)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_A, *_W21), 8100.0)

    def test_as_of_past_week_end_returns_zero(self):
        as_of = _W21_END + timedelta(hours=1)
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=as_of)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_A, *_W21), 0.0)

    def test_non_work_hours_excluded_under_weekday_workcal(self):
        # Weekday 9h workcal: 5 days × 9h = 45 work hours in a week. At 4/3h
        # per roll (knit + Doff), 34 whole rolls fit (the 34th knit ends
        # exactly at the 45h budget; its Doff spills past) -> 3400 lbs.
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=_W21_START, workcal=_WEEKDAY_9H)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_A, *_W21), 3400.0)

    def test_iso_cross_year_week_resolves_correctly(self):
        # ISO 2026-W01 starts Mon Dec 29 2025. as_of in late Dec 2025; the
        # bridge spans the year boundary into the W01 window. 126 rolls in
        # the 168h window -> 12600 lbs.
        as_of = datetime(2025, 12, 27, 0, 0)   # Sat before W01 Monday
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=as_of)
        self.assertEqual(m.producible_lbs_in_week(_ITEM_A, 2026, 1), 12600.0)


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
        # effectively begins 2 days into the window. 168h - 48h = 120h of
        # budget; 120h / (4/3h per roll) = 90 rolls -> 9000 lbs (huge beams).
        m = _make_machine(init_top_lbs=100_000.0, init_btm_lbs=100_000.0,
                          start=_W21_START)
        start = _W21_START + timedelta(hours=48)
        self.assertEqual(
            m.producible_lbs_in_week(_ITEM_A, *_W21, start=start),
            9000.0,
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
