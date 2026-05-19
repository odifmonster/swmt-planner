#!/usr/bin/env python

import unittest
from datetime import datetime, timedelta
from typing import Literal

from swmtplanner.products import Greige, BeamSet
from swmtplanner.schedule import Machine
from swmtplanner.support import WorkCal
from swmtplanner.demand.rlsitem import RlsItem
from swmtplanner.planners.infinite import State, Move
from swmtplanner.planners.infinite.coordination import (
    OrderKey, ScoringContext,
    assign_priorities, build_new_machine_avail, build_context,
)


# --- Fixtures -----------------------------------------------------------
#
# Most of these tests only need rls_items (assign_priorities); the
# `build_new_machine_avail` section needs real `Machine` instances so
# `state.machines[id].is_new` resolves.

_START = datetime(2026, 5, 18, 0, 0)

# 24/7 workcal + simple beam/change durations for the machine fixture.
# Only `Machine.is_new` is read by `build_new_machine_avail`, so the
# operational details don't matter — they just need to be valid.
_24_7 = WorkCal(work_days=(0, 1, 2, 3, 4, 5, 6),
                day_start=0, day_end=24, holidays=())
_TOP_BEAM = BeamSet('40D BLACK 1000X4')
_BTM_BEAM = BeamSet('60D WHITE 1000X4')
_SIMPLE_CHANGE = timedelta(minutes=15)
_FAMILY_CHANGE = timedelta(hours=1)


def _greige(item_id: str, safety: float) -> Greige:
    """Build a Greige with the given id and safety target. Other fields
    are stable across tests since `assign_priorities` only reads
    `id` (via `OrderKey`) and `safety` (via the safety view)."""
    return Greige(
        item_id, family='A', tgt_wt=100.0,
        top_beam='40D BLACK 1000X4', top_pct=0.5,
        btm_beam='60D WHITE 1000X4', btm_pct=0.5,
        safety=safety, machines={'M1': 100.0},
    )


def _rls(
    item: Greige, weekly: list[float], on_hand: float = 0.0,
) -> RlsItem:
    return RlsItem(
        item=item, start_date=_START, on_hand_lbs=on_hand,
        lead_time=timedelta(0),
        weekly_lbs_needed=weekly,
    )


def _make_state(
    rls_items: dict[str, RlsItem] | None = None,
    machines: dict[str, Machine] | None = None,
    reference_week_idx: int = 1,
) -> State:
    return State(
        machines=machines if machines is not None else {},
        rls_items=rls_items if rls_items is not None else {},
        start_date=_START, window_end=_START,
        reference_week_idx=reference_week_idx,
    )


def _machine(
    machine_id: str, is_new: bool, init_item: Greige,
    start: datetime = _START,
) -> Machine:
    """A bare Machine sufficient for the coordination tests. With
    `init_top_lbs == init_btm_lbs == 1e6` and an item rate of 100 lbs/hr
    split 50/50, `next_runout` sits ~20,000 work-hours after `start` —
    cleanly distinct from `next_job_end == start` for the dp_time
    tests."""
    return Machine(
        machine_id, init_item, start,
        _TOP_BEAM, 1e6, _BTM_BEAM, 1e6,
        _24_7, _SIMPLE_CHANGE, _FAMILY_CHANGE,
        is_new=is_new,
    )


def _move(
    machine_id: str, item: Greige,
    start_at: Literal['next_job_end', 'next_runout'] = 'next_job_end',
    idle_for: timedelta = timedelta(0),
) -> Move:
    """A bare Move sufficient for the coordination tests — the
    coordination functions only read `machine_id`, `item`, and (for
    `build_context`) `start_at`. Other fields take placeholder
    values."""
    return Move(
        machine_id=machine_id, item=item, lbs=0.0,
        start_at=start_at, idle_for=idle_for,
        plan=[], week_idx=None,
    )


def _reg_key(item_id: str, week_idx: int) -> OrderKey:
    return OrderKey(item_id=item_id, week_idx=week_idx)


def _safety_key(item_id: str) -> OrderKey:
    return OrderKey(item_id=item_id, week_idx=None)


# --- 1.1 assign_priorities ----------------------------------------------

class AssignPrioritiesTests(unittest.TestCase):

    def test_empty_state(self):
        # 1.1.1: state.rls_items == {} → {}.
        state = _make_state(rls_items={})
        self.assertEqual(assign_priorities(state), {})

    def test_only_urgent_regulars_sorted_by_due_date(self):
        # 1.1.2: items with safety=0 (no safety orders) and unmet
        # urgent demand at different weeks. Verify primary sort on
        # due_date ascending.
        item_p = _greige('AU_P', safety=0.0)
        item_q = _greige('AU_Q', safety=0.0)
        # P: week 0 unmet (due_date earliest); Q: week 1 unmet.
        rls_p = _rls(item=item_p, weekly=[100, 0, 0, 0])
        rls_q = _rls(item=item_q, weekly=[0, 100, 0, 0])
        state = _make_state({'AU_P': rls_p, 'AU_Q': rls_q})

        ranks = assign_priorities(state)
        self.assertEqual(ranks[_reg_key('AU_P', 0)], 1)
        self.assertEqual(ranks[_reg_key('AU_Q', 1)], 2)

    def test_only_safety_orders_sorted_by_relative_depletion(self):
        # 1.1.3: items with all weekly demand met but safety pool
        # below target. Verify sort by ratio = pool / target asc
        # (largest relative depletion first).
        #
        # P: safety=100, weekly=[100,0,0,0], on_hand=100
        #    → bucket 1 takes all 100 to week 0; bucket 2 gets 0.
        #    → pool=0, gap=100, ratio=0.0.
        item_p = _greige('AU_P', safety=100.0)
        rls_p = _rls(item=item_p, weekly=[100, 0, 0, 0], on_hand=100.0)
        # Q: safety=100, weekly=[0,0,0,0], on_hand=50
        #    → bucket 1 needs 0; bucket 2 takes 50 to safety.
        #    → pool=50, gap=50, ratio=0.5.
        item_q = _greige('AU_Q', safety=100.0)
        rls_q = _rls(item=item_q, weekly=[0, 0, 0, 0], on_hand=50.0)
        state = _make_state({'AU_P': rls_p, 'AU_Q': rls_q})

        ranks = assign_priorities(state)
        self.assertEqual(ranks[_safety_key('AU_P')], 1)
        self.assertEqual(ranks[_safety_key('AU_Q')], 2)

    def test_only_future_regulars_sorted_by_due_date(self):
        # 1.1.4: items with unmet demand only at week 2 or 3 (future,
        # since reference_week_idx=1), safety pool trivially at target
        # (safety=0). Verify (due_date asc) sort.
        item_p = _greige('AU_P', safety=0.0)
        item_q = _greige('AU_Q', safety=0.0)
        rls_p = _rls(item=item_p, weekly=[0, 0, 100, 0])  # week 2 unmet
        rls_q = _rls(item=item_q, weekly=[0, 0, 0, 100])  # week 3 unmet
        state = _make_state({'AU_P': rls_p, 'AU_Q': rls_q})

        ranks = assign_priorities(state)
        self.assertEqual(ranks[_reg_key('AU_P', 2)], 1)
        self.assertEqual(ranks[_reg_key('AU_Q', 3)], 2)

    def test_all_three_buckets_global_ordering(self):
        # 1.1.5: items spanning all three buckets. Verify every urgent
        # rank < every safety rank < every future rank.
        item_u = _greige('AU_U', safety=0.0)
        rls_u = _rls(item=item_u, weekly=[100, 0, 0, 0])  # urgent
        item_s = _greige('AU_S', safety=100.0)
        rls_s = _rls(item=item_s, weekly=[0, 0, 0, 0],
                     on_hand=50.0)  # safety only
        item_f = _greige('AU_F', safety=0.0)
        rls_f = _rls(item=item_f, weekly=[0, 0, 0, 100])  # future
        state = _make_state({
            'AU_U': rls_u, 'AU_S': rls_s, 'AU_F': rls_f,
        })

        ranks = assign_priorities(state)
        rank_u = ranks[_reg_key('AU_U', 0)]
        rank_s = ranks[_safety_key('AU_S')]
        rank_f = ranks[_reg_key('AU_F', 3)]
        self.assertLess(rank_u, rank_s)
        self.assertLess(rank_s, rank_f)

    def test_tie_breaker_equal_due_date_in_regular_bucket(self):
        # 1.1.6: two urgent regulars at the same due_date but with
        # different safety ratios. The lower-ratio item ranks first.
        #
        # The bucket rule fills earlier demand before safety, so we
        # can't co-locate "urgent week-0 unmet" with "non-zero safety
        # pool". Instead, both items use weekly=[200,200,0,0] so
        # bucket 1 (week 0) is fully filled by on_hand, leaving
        # bucket 2 to determine the safety state, and week 1 unmet.
        # Week 1 is urgent at reference_week_idx=1.
        #
        # P: safety=100, on_hand=300
        #    → week 0 filled (200), safety filled (100, ratio=1.0),
        #      week 1 unmet (200). No safety order.
        item_p = _greige('AU_P', safety=100.0)
        rls_p = _rls(item=item_p, weekly=[200, 200, 0, 0],
                     on_hand=300.0)
        # Q: safety=100, on_hand=250
        #    → week 0 filled (200), safety partial (50, ratio=0.5),
        #      week 1 unmet (200). Plus SafetyOrder gap=50.
        item_q = _greige('AU_Q', safety=100.0)
        rls_q = _rls(item=item_q, weekly=[200, 200, 0, 0],
                     on_hand=250.0)
        state = _make_state({'AU_P': rls_p, 'AU_Q': rls_q})

        ranks = assign_priorities(state)
        # Both week-1 regulars; same due_date. Q's ratio is lower →
        # ranks ahead of P in the urgent bucket.
        self.assertLess(
            ranks[_reg_key('AU_Q', 1)], ranks[_reg_key('AU_P', 1)],
        )

    def test_tie_breaker_equal_absolute_safety_gap(self):
        # 1.1.7: two safety orders with the same absolute
        # safety_target - safety_pool gap but different targets.
        # Verify the sort is on the ratio (pool / target), not the
        # absolute gap.
        #
        # P: safety=200, on_hand=100 → pool=100, gap=100, ratio=0.5
        item_p = _greige('AU_P', safety=200.0)
        rls_p = _rls(item=item_p, weekly=[0, 0, 0, 0], on_hand=100.0)
        # Q: safety=400, on_hand=300 → pool=300, gap=100, ratio=0.75
        item_q = _greige('AU_Q', safety=400.0)
        rls_q = _rls(item=item_q, weekly=[0, 0, 0, 0], on_hand=300.0)
        state = _make_state({'AU_P': rls_p, 'AU_Q': rls_q})

        ranks = assign_priorities(state)
        # Same absolute gap, but P's ratio (0.5) < Q's (0.75).
        self.assertEqual(ranks[_safety_key('AU_P')], 1)
        self.assertEqual(ranks[_safety_key('AU_Q')], 2)

    def test_safety_target_zero_corner_case(self):
        # 1.1.8: an item with safety=0 has its ratio resolved to 0.0
        # by the divide-by-zero convention. Its regular orders sort
        # first in the bucket's ratio tie-breaker against a safety>0
        # item. Safety orders never appear for safety=0 items
        # (gap = 0 - 0 = 0).
        #
        # P: safety=0, weekly=[0,100,0,0] → week 1 unmet, no safety.
        item_p = _greige('AU_P', safety=0.0)
        rls_p = _rls(item=item_p, weekly=[0, 100, 0, 0])
        # Q: safety=100, weekly=[0,200,0,0], on_hand=100
        #    → week 0 needs 0; bucket 2 fills safety (pool=100=target);
        #      week 1 unmet (200). No safety order. Ratio=1.0.
        item_q = _greige('AU_Q', safety=100.0)
        rls_q = _rls(item=item_q, weekly=[0, 200, 0, 0], on_hand=100.0)
        state = _make_state({'AU_P': rls_p, 'AU_Q': rls_q})

        ranks = assign_priorities(state)
        # Both week-1 regulars (same due_date). P's ratio is 0.0 by
        # convention; Q's is 1.0. P ranks first.
        self.assertLess(
            ranks[_reg_key('AU_P', 1)], ranks[_reg_key('AU_Q', 1)],
        )
        # P's safety=0 → no SafetyOrder generated.
        self.assertNotIn(_safety_key('AU_P'), ranks)

    def test_ranks_contiguous_starting_at_one(self):
        # 1.1.9: for N eligible orders the returned ranks are exactly
        # {1, 2, …, N} — no gaps, no duplicates. Setup: 2 urgent +
        # 2 safety + 2 future = 6 eligible orders.
        u1 = _greige('AU_U1', safety=0.0)
        rls_u1 = _rls(item=u1, weekly=[100, 0, 0, 0])
        u2 = _greige('AU_U2', safety=0.0)
        rls_u2 = _rls(item=u2, weekly=[0, 100, 0, 0])
        s1 = _greige('AU_S1', safety=100.0)
        rls_s1 = _rls(item=s1, weekly=[0, 0, 0, 0], on_hand=20.0)
        s2 = _greige('AU_S2', safety=100.0)
        rls_s2 = _rls(item=s2, weekly=[0, 0, 0, 0], on_hand=80.0)
        f1 = _greige('AU_F1', safety=0.0)
        rls_f1 = _rls(item=f1, weekly=[0, 0, 100, 0])
        f2 = _greige('AU_F2', safety=0.0)
        rls_f2 = _rls(item=f2, weekly=[0, 0, 0, 100])
        state = _make_state({
            'AU_U1': rls_u1, 'AU_U2': rls_u2,
            'AU_S1': rls_s1, 'AU_S2': rls_s2,
            'AU_F1': rls_f1, 'AU_F2': rls_f2,
        })

        ranks = assign_priorities(state)
        # 6 distinct ranks 1..6.
        self.assertEqual(set(ranks.values()), {1, 2, 3, 4, 5, 6})
        self.assertEqual(len(ranks), 6)
        # Bucket boundaries: urgent ranks {1,2}, safety {3,4},
        # future {5,6}.
        urgent_ranks = {
            ranks[_reg_key('AU_U1', 0)],
            ranks[_reg_key('AU_U2', 1)],
        }
        safety_ranks = {
            ranks[_safety_key('AU_S1')],
            ranks[_safety_key('AU_S2')],
        }
        future_ranks = {
            ranks[_reg_key('AU_F1', 2)],
            ranks[_reg_key('AU_F2', 3)],
        }
        self.assertEqual(urgent_ranks, {1, 2})
        self.assertEqual(safety_ranks, {3, 4})
        self.assertEqual(future_ranks, {5, 6})

    def test_reference_week_advance_shifts_regular_safety_boundary(self):
        # 1.1.10: same rls_items, different reference_week_idx values.
        # AU_R has a week-2 regular order (safety=0 → no safety order).
        # AU_S has a safety order only (no demand, partial safety pool).
        item_r = _greige('AU_R', safety=0.0)
        rls_r = _rls(item=item_r, weekly=[0, 0, 100, 0])
        item_s = _greige('AU_S', safety=100.0)
        rls_s = _rls(item=item_s, weekly=[0, 0, 0, 0], on_hand=50.0)
        rls_items = {'AU_R': rls_r, 'AU_S': rls_s}

        # reference_week_idx == 1 (default): week 2 is future →
        # safety ranks ahead of the regular.
        ranks = assign_priorities(
            _make_state(rls_items, reference_week_idx=1),
        )
        self.assertLess(
            ranks[_safety_key('AU_S')], ranks[_reg_key('AU_R', 2)],
        )

        # reference_week_idx == 2: week 2 is now urgent → regular
        # ranks ahead of safety. Same rls_items, only the lever moved.
        ranks = assign_priorities(
            _make_state(rls_items, reference_week_idx=2),
        )
        self.assertLess(
            ranks[_reg_key('AU_R', 2)], ranks[_safety_key('AU_S')],
        )

    def test_reference_week_advance_promotes_multiple_futures(self):
        # 1.1.11: regulars at weeks 1, 2, 3 plus a safety order on a
        # fourth item. Each step of reference_week_idx pulls exactly
        # one regular across the safety boundary.
        item_w1 = _greige('AU_W1', safety=0.0)
        rls_w1 = _rls(item=item_w1, weekly=[0, 100, 0, 0])
        item_w2 = _greige('AU_W2', safety=0.0)
        rls_w2 = _rls(item=item_w2, weekly=[0, 0, 100, 0])
        item_w3 = _greige('AU_W3', safety=0.0)
        rls_w3 = _rls(item=item_w3, weekly=[0, 0, 0, 100])
        item_s = _greige('AU_S', safety=100.0)
        rls_s = _rls(item=item_s, weekly=[0, 0, 0, 0], on_hand=50.0)
        rls_items = {
            'AU_W1': rls_w1, 'AU_W2': rls_w2,
            'AU_W3': rls_w3, 'AU_S': rls_s,
        }
        safety = _safety_key('AU_S')
        reg1 = _reg_key('AU_W1', 1)
        reg2 = _reg_key('AU_W2', 2)
        reg3 = _reg_key('AU_W3', 3)

        # reference_week_idx == 1: only week 1 urgent; weeks 2, 3
        # future. Safety sits between them.
        ranks = assign_priorities(
            _make_state(rls_items, reference_week_idx=1),
        )
        self.assertLess(ranks[reg1], ranks[safety])
        self.assertLess(ranks[safety], ranks[reg2])
        self.assertLess(ranks[safety], ranks[reg3])

        # reference_week_idx == 2: weeks 1 and 2 urgent (both ahead of
        # safety); week 3 still future (behind safety).
        ranks = assign_priorities(
            _make_state(rls_items, reference_week_idx=2),
        )
        self.assertLess(ranks[reg1], ranks[safety])
        self.assertLess(ranks[reg2], ranks[safety])
        self.assertLess(ranks[safety], ranks[reg3])

        # reference_week_idx == 3: all three regulars urgent → all
        # rank ahead of safety; the future bucket is empty.
        ranks = assign_priorities(
            _make_state(rls_items, reference_week_idx=3),
        )
        self.assertLess(ranks[reg1], ranks[safety])
        self.assertLess(ranks[reg2], ranks[safety])
        self.assertLess(ranks[reg3], ranks[safety])


# --- 1.2 build_new_machine_avail ----------------------------------------

class BuildNewMachineAvailTests(unittest.TestCase):

    def test_empty_candidate_list(self):
        # 1.2.1: empty candidates → {}.
        item_a = _greige('AU_A', 0.0)
        m_new = _machine('M_new', is_new=True, init_item=item_a)
        state = _make_state(machines={'M_new': m_new})
        self.assertEqual(build_new_machine_avail(state, []), {})

    def test_single_new_machine_candidate(self):
        # 1.2.2: one move on a new machine → {A: True}.
        item_a = _greige('AU_A', 0.0)
        m_new = _machine('M_new', is_new=True, init_item=item_a)
        state = _make_state(machines={'M_new': m_new})

        result = build_new_machine_avail(state, [_move('M_new', item_a)])
        self.assertEqual(result, {item_a: True})

    def test_single_old_machine_candidate(self):
        # 1.2.3: one move on a legacy machine → {A: False}.
        item_a = _greige('AU_A', 0.0)
        m_old = _machine('M_old', is_new=False, init_item=item_a)
        state = _make_state(machines={'M_old': m_old})

        result = build_new_machine_avail(state, [_move('M_old', item_a)])
        self.assertEqual(result, {item_a: False})

    def test_mixed_candidates_true_wins_regardless_of_order(self):
        # 1.2.4: two candidates for item A (one new, one old). The
        # True survives regardless of iteration order in `candidates`.
        item_a = _greige('AU_A', 0.0)
        m_new = _machine('M_new', is_new=True, init_item=item_a)
        m_old = _machine('M_old', is_new=False, init_item=item_a)
        state = _make_state(machines={'M_new': m_new, 'M_old': m_old})
        move_new = _move('M_new', item_a)
        move_old = _move('M_old', item_a)

        # New first.
        self.assertEqual(
            build_new_machine_avail(state, [move_new, move_old]),
            {item_a: True},
        )
        # Old first — still True.
        self.assertEqual(
            build_new_machine_avail(state, [move_old, move_new]),
            {item_a: True},
        )

    def test_multiple_items_mixed_availability(self):
        # 1.2.5: three items: A has both new and old, B has only old,
        # C has only new.
        item_a = _greige('AU_A', 0.0)
        item_b = _greige('AU_B', 0.0)
        item_c = _greige('AU_C', 0.0)
        m_new_a = _machine('M_new_A', is_new=True, init_item=item_a)
        m_old_a = _machine('M_old_A', is_new=False, init_item=item_a)
        m_old_b = _machine('M_old_B', is_new=False, init_item=item_b)
        m_new_c = _machine('M_new_C', is_new=True, init_item=item_c)
        state = _make_state(machines={
            'M_new_A': m_new_a, 'M_old_A': m_old_a,
            'M_old_B': m_old_b, 'M_new_C': m_new_c,
        })
        candidates = [
            _move('M_new_A', item_a),
            _move('M_old_A', item_a),
            _move('M_old_B', item_b),
            _move('M_new_C', item_c),
        ]

        result = build_new_machine_avail(state, candidates)
        self.assertEqual(result, {
            item_a: True, item_b: False, item_c: True,
        })

    def test_items_absent_from_candidate_pool(self):
        # 1.2.6: state has rls_items for both D and E (though
        # build_new_machine_avail doesn't read rls_items), but the
        # candidate list only references E. D is NOT a key in the
        # output dict — callers using `.get(item, False)` see False
        # for D naturally.
        item_d = _greige('AU_D', 0.0)
        item_e = _greige('AU_E', 0.0)
        m_old = _machine('M_old', is_new=False, init_item=item_e)
        state = _make_state(
            rls_items={
                'AU_D': _rls(item=item_d, weekly=[100, 0, 0, 0]),
                'AU_E': _rls(item=item_e, weekly=[100, 0, 0, 0]),
            },
            machines={'M_old': m_old},
        )

        result = build_new_machine_avail(state, [_move('M_old', item_e)])
        self.assertEqual(result, {item_e: False})
        self.assertNotIn(item_d, result)


# --- 1.3 build_context --------------------------------------------------

class BuildContextTests(unittest.TestCase):

    def test_standard_composition(self):
        # 1.3.1: ctx fields match the three subordinate functions plus
        # earliest_dp_time = min(dp_time(c) for c in candidates).
        item_a = _greige('AU_A', safety=0.0)
        item_b = _greige('AU_B', safety=0.0)
        rls_a = _rls(item=item_a, weekly=[100, 0, 0, 0])   # urgent reg
        rls_b = _rls(item=item_b, weekly=[0, 0, 0, 100])   # future reg
        t0 = _START
        t1 = _START + timedelta(hours=1)
        m_new = _machine('M_new', is_new=True, init_item=item_a, start=t0)
        m_old = _machine('M_old', is_new=False, init_item=item_b, start=t1)
        state = _make_state(
            rls_items={'AU_A': rls_a, 'AU_B': rls_b},
            machines={'M_new': m_new, 'M_old': m_old},
        )
        candidates = [_move('M_new', item_a), _move('M_old', item_b)]

        ctx = build_context(state, candidates)
        self.assertIsInstance(ctx, ScoringContext)
        self.assertEqual(ctx.priorities, assign_priorities(state))
        self.assertEqual(
            ctx.new_machine_avail,
            build_new_machine_avail(state, candidates),
        )
        # M_new's next_job_end (t0) is earliest across the two
        # candidates.
        self.assertEqual(ctx.earliest_dp_time, t0)

    def test_dp_time_resolution_per_start_at(self):
        # 1.3.2: same machine, one candidate per start_at value.
        # `next_job_end` candidate's dp_time = machine.next_job_end;
        # `next_runout` candidate's dp_time = machine.next_runout
        # (which is much later for this fixture).
        item_a = _greige('AU_A', safety=0.0)
        rls_a = _rls(item=item_a, weekly=[100, 0, 0, 0])
        m = _machine('M1', is_new=False, init_item=item_a)
        state = _make_state(
            rls_items={'AU_A': rls_a}, machines={'M1': m},
        )
        # Sanity check the fixture: the two times are distinct.
        self.assertGreater(m.next_runout, m.next_job_end)

        # Single next_job_end candidate.
        ctx = build_context(
            state, [_move('M1', item_a, start_at='next_job_end')],
        )
        self.assertEqual(ctx.earliest_dp_time, m.next_job_end)

        # Single next_runout candidate.
        ctx = build_context(
            state, [_move('M1', item_a, start_at='next_runout')],
        )
        self.assertEqual(ctx.earliest_dp_time, m.next_runout)

    def test_earliest_dp_across_multiple_machines(self):
        # 1.3.3: three machines with staggered start times, one
        # candidate each. earliest_dp_time picks the smallest.
        item_a = _greige('AU_A', safety=0.0)
        rls_a = _rls(item=item_a, weekly=[100, 0, 0, 0])
        t0 = _START
        t1 = _START + timedelta(hours=1)
        t2 = _START + timedelta(hours=2)
        m0 = _machine('M0', is_new=False, init_item=item_a, start=t0)
        m1 = _machine('M1', is_new=False, init_item=item_a, start=t1)
        m2 = _machine('M2', is_new=False, init_item=item_a, start=t2)
        state = _make_state(
            rls_items={'AU_A': rls_a},
            machines={'M0': m0, 'M1': m1, 'M2': m2},
        )
        # Listed out of order — earliest_dp_time should still be t0.
        candidates = [
            _move('M2', item_a),
            _move('M0', item_a),
            _move('M1', item_a),
        ]

        ctx = build_context(state, candidates)
        self.assertEqual(ctx.earliest_dp_time, t0)

    def test_carrying_avoidance_idle_ignored_in_dp_time(self):
        # 1.3.4: a candidate with idle_for > 0 doesn't shift its
        # dp_time. The function reads machine.next_job_end directly,
        # not effective_start. Confirms idle isn't double-counted
        # between level_loading and idle_time.
        item_a = _greige('AU_A', safety=0.0)
        rls_a = _rls(item=item_a, weekly=[100, 0, 0, 0])
        m = _machine('M1', is_new=False, init_item=item_a)
        state = _make_state(
            rls_items={'AU_A': rls_a}, machines={'M1': m},
        )
        move_with_idle = _move(
            'M1', item_a, start_at='next_job_end',
            idle_for=timedelta(hours=24),
        )

        ctx = build_context(state, [move_with_idle])
        # dp_time == m.next_job_end, NOT m.next_job_end + 24h.
        self.assertEqual(ctx.earliest_dp_time, m.next_job_end)

    def test_empty_candidate_list_raises(self):
        # 1.3.5: build_context(state, []) raises ValueError via
        # min(...) on the empty dp_time generator. Programmer-error
        # contract — the main loop never calls build_context on an
        # empty pool.
        state = _make_state()
        with self.assertRaises(ValueError):
            build_context(state, [])


if __name__ == '__main__':
    unittest.main()
