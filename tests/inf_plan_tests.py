#!/usr/bin/env python

import unittest
from datetime import datetime, timedelta

from swmtplanner.products import Greige, BeamSet
from swmtplanner.schedule import (
    Machine, Job, Waste, TapeOut, BeamLoad, StyleChange, Idle,
)
from swmtplanner.demand.rlsitem import RlsItem
from swmtplanner.support import WorkCal
from swmtplanner.planners.infinite import (
    State, Move, CostWeights, Costing,
    DecisionPoint, RegularOrder, SafetyOrder,
    eligible_decision_points, eligible_orders, enumerate_candidates,
    PlanReport, plan,
)


# --- Fixtures -----------------------------------------------------------

# 24/7 workcal so clock-time arithmetic matches work-hour arithmetic.
_24_7 = WorkCal(work_days=(0, 1, 2, 3, 4, 5, 6),
                day_start=0, day_end=24, holidays=())

# Two items in the same family with the same yarn on each bar — that
# means transitions between them require only a StyleChange (no
# tape-outs / beam-loads), keeping the 1.1.4 canonical-plan setup
# focused on the run-up → transition → new-item flow.
_ITEM_A = Greige(
    'AU0001', family='A', tgt_wt=100.0,
    top_beam='40D BLACK 1000X4', top_pct=0.5,
    btm_beam='60D WHITE 1000X4', btm_pct=0.5,
    safety=500.0, machines={'M1': 100.0, 'M2': 100.0},
)
_ITEM_B = Greige(
    'AU0002', family='A', tgt_wt=100.0,
    top_beam='40D BLACK 1000X4', top_pct=0.5,
    btm_beam='60D WHITE 1000X4', btm_pct=0.5,
    safety=300.0, machines={'M1': 100.0, 'M2': 100.0},
)

_TOP_BEAM = BeamSet('40D BLACK 1000X4')
_BTM_BEAM = BeamSet('60D WHITE 1000X4')

_START = datetime(2026, 5, 18, 0, 0)
_SIMPLE_CHANGE = timedelta(minutes=15)
_FAMILY_CHANGE = timedelta(hours=1)


# --- 1.3 fixtures: items with safety=0 (so the safety pool is trivially
# at target, isolating the demand-side bucket logic) and per-family
# machine assignments for the multi-family enumerate_candidates tests.

# Family A items, both runnable on M1/M2. Same yarn on both bars
# (40D/60D), so transitions between them are simple style changes.
_T1 = Greige(
    'AU_T1', family='A', tgt_wt=100.0,
    top_beam='40D BLACK 1000X4', top_pct=0.5,
    btm_beam='60D WHITE 1000X4', btm_pct=0.5,
    safety=0.0, machines={'M1': 100.0, 'M2': 100.0},
)
_T2 = Greige(
    'AU_T2', family='A', tgt_wt=100.0,
    top_beam='40D BLACK 1000X4', top_pct=0.5,
    btm_beam='60D WHITE 1000X4', btm_pct=0.5,
    safety=0.0, machines={'M1': 100.0, 'M2': 100.0},
)
# Family C item, runs only on M3 — used to verify the per-machine
# eligibility check filters out machines in other family classes.
_TC = Greige(
    'AU_TC', family='C', tgt_wt=100.0,
    top_beam='40D BLACK 1000X4', top_pct=0.5,
    btm_beam='60D WHITE 1000X4', btm_pct=0.5,
    safety=0.0, machines={'M3': 100.0},
)
# Family B item with different yarn on both bars — used as the
# "current" item for the full-changeover preamble cap test, where the
# preamble must include TapeOut('both') + two BeamLoads + a family
# StyleChange.
_TD = Greige(
    'AU_TD', family='B', tgt_wt=100.0,
    top_beam='30D RED 1000X4', top_pct=0.5,
    btm_beam='90D GREEN 1000X4', btm_pct=0.5,
    safety=0.0, machines={'M1': 100.0},
)


def _make_machine(
    machine_id: str = 'M1',
    init_item: Greige = _ITEM_A,
    init_top_lbs: float = 2800.0,
    init_btm_lbs: float = 1800.0,
    start: datetime = _START,
    is_new: bool = False,
) -> Machine:
    return Machine(
        machine_id, init_item, start,
        _TOP_BEAM, init_top_lbs, _BTM_BEAM, init_btm_lbs,
        _24_7, _SIMPLE_CHANGE, _FAMILY_CHANGE,
        is_new=is_new,
    )


def _make_rls_item(
    item: Greige = _ITEM_A,
    on_hand: float = 0.0,
    weekly: list[float] | None = None,
    lead_time: timedelta = timedelta(days=7),
) -> RlsItem:
    if weekly is None:
        weekly = [100.0, 100.0, 100.0, 100.0]
    return RlsItem(
        item=item, start_date=_START, on_hand_lbs=on_hand,
        lead_time=lead_time, weekly_lbs_needed=weekly,
    )


def _make_state(machines=None, rls_items=None, **kwargs) -> State:
    """Build a State with sensible defaults: one M1 machine running
    _ITEM_A, one AU0001 RlsItem with 100 lbs/week demand. Pass
    `machines` and `rls_items` to override; any other State field
    (start_date, window_end, window_advance_amount, etc.) can be passed
    as a kwarg."""
    if machines is None:
        machines = {'M1': _make_machine('M1')}
    if rls_items is None:
        rls_items = {'AU0001': _make_rls_item()}
    kwargs.setdefault('start_date', _START)
    kwargs.setdefault('window_end', _START)
    return State(machines=machines, rls_items=rls_items, **kwargs)


def _move_with_plan(
    plan: list,
    machine_id: str = 'M1',
    item: Greige = _ITEM_A,
) -> Move:
    """Convenience for the 1.1 tests, where only the plan matters: build
    a Move with the given plan and placeholder values for the
    bookkeeping fields the State doesn't touch."""
    return Move(
        machine_id=machine_id, item=item, lbs=0.0,
        start_at='next_job_end', idle_for=timedelta(0),
        plan=plan,
    )


def _big_beam_machine(
    machine_id: str = 'M1',
    init_item: Greige = _T1,
    start: datetime = _START,
    is_new: bool = False,
) -> Machine:
    """A machine whose initial beams hold so much yarn (1e6 lbs each)
    that no in-stream reload happens within the planning horizon. Used
    by the main-loop tests so that the per-week cap depends only on the
    week's wall-clock window and the per-machine eligibility — not on
    beam mechanics."""
    return Machine(
        machine_id, init_item, start,
        _TOP_BEAM, 1e6, _BTM_BEAM, 1e6,
        _24_7, _SIMPLE_CHANGE, _FAMILY_CHANGE,
        is_new=is_new,
    )


def _weights(**overrides) -> CostWeights:
    """Build CostWeights with all fields defaulting to 0.0 and the
    specified ones overridden. Lets each 1.2 test set only the weights
    its scenario exercises, so the score formula reduces to those
    weights times the corresponding quantities."""
    defaults = dict(
        lateness=0.0, drainage=0.0, carrying=0.0, excess=0.0,
        tape_out_single=0.0, tape_out_both=0.0,
        family_change=0.0, idle_time=0.0,
    )
    defaults.update(overrides)
    return CostWeights(**defaults)


# --- 1.1 State ----------------------------------------------------------

class StateTests(unittest.TestCase):
    """Section 1.1 of INF_PLAN_TEST_SPEC.md."""

    # ----- 1.1.1 Construction -----

    def test_construction_stores_required_fields(self):
        machines = {'M1': _make_machine('M1')}
        rls_items = {'AU0001': _make_rls_item()}
        start = datetime(2026, 6, 1, 0, 0)
        window = datetime(2026, 6, 2, 0, 0)
        state = State(
            machines=machines, rls_items=rls_items,
            start_date=start, window_end=window,
        )
        self.assertEqual(state.machines, machines)
        self.assertEqual(state.rls_items, rls_items)
        self.assertEqual(state.start_date, start)
        self.assertEqual(state.window_end, window)

    def test_window_advance_amount_default(self):
        self.assertEqual(
            _make_state().window_advance_amount, timedelta(hours=24),
        )

    def test_window_advance_amount_custom(self):
        self.assertEqual(
            _make_state(window_advance_amount=timedelta(hours=6))
                .window_advance_amount,
            timedelta(hours=6),
        )

    def test_carrying_avoidance_margin_default(self):
        self.assertEqual(
            _make_state().carrying_avoidance_margin, timedelta(hours=24),
        )

    def test_carrying_avoidance_margin_custom(self):
        self.assertEqual(
            _make_state(carrying_avoidance_margin=timedelta(hours=12))
                .carrying_avoidance_margin,
            timedelta(hours=12),
        )

    def test_candidate_threshold_default(self):
        self.assertEqual(_make_state().candidate_threshold, 1)

    def test_candidate_threshold_custom(self):
        self.assertEqual(
            _make_state(candidate_threshold=5).candidate_threshold, 5,
        )

    def test_planning_horizon_buffer_default(self):
        self.assertEqual(
            _make_state().planning_horizon_buffer, timedelta(weeks=4),
        )

    def test_planning_horizon_buffer_custom(self):
        self.assertEqual(
            _make_state(planning_horizon_buffer=timedelta(weeks=2))
                .planning_horizon_buffer,
            timedelta(weeks=2),
        )

    # ----- 1.1.2 commit_move per activity type -----

    def test_commit_move_with_job_routes_to_machine_and_rls_item(self):
        state = _make_state()
        rls = state.rls_items['AU0001']
        job = Job(
            start=_START, end=_START + timedelta(hours=1),
            item=_ITEM_A, lbs=100.0,
        )
        state.commit_move(_move_with_plan([job]))
        self.assertEqual(state.machines['M1'].activities, (job,))
        self.assertEqual(rls.jobs, (job,))

    def test_commit_move_with_waste_does_not_touch_rls_item(self):
        state = _make_state()
        rls = state.rls_items['AU0001']
        waste = Waste(
            start=_START, end=_START + timedelta(minutes=30),
            item=_ITEM_A, lbs=50.0,
        )
        state.commit_move(_move_with_plan([waste]))
        self.assertEqual(state.machines['M1'].activities, (waste,))
        self.assertEqual(rls.jobs, ())

    def test_commit_move_with_tape_out_top(self):
        state = _make_state()
        rls = state.rls_items['AU0001']
        tape_out = TapeOut(
            start=_START, end=_START + timedelta(hours=4), bars='top',
        )
        state.commit_move(_move_with_plan([tape_out]))
        self.assertEqual(state.machines['M1'].activities, (tape_out,))
        self.assertEqual(rls.jobs, ())

    def test_commit_move_with_tape_out_btm(self):
        state = _make_state()
        rls = state.rls_items['AU0001']
        tape_out = TapeOut(
            start=_START, end=_START + timedelta(hours=4), bars='btm',
        )
        state.commit_move(_move_with_plan([tape_out]))
        self.assertEqual(state.machines['M1'].activities, (tape_out,))
        self.assertEqual(rls.jobs, ())

    def test_commit_move_with_tape_out_both(self):
        state = _make_state()
        rls = state.rls_items['AU0001']
        tape_out = TapeOut(
            start=_START, end=_START + timedelta(hours=6), bars='both',
        )
        state.commit_move(_move_with_plan([tape_out]))
        self.assertEqual(state.machines['M1'].activities, (tape_out,))
        self.assertEqual(rls.jobs, ())

    def test_commit_move_with_beam_load_top(self):
        # Start with empty top so the BeamLoad is consistent with state.
        machine = _make_machine('M1', init_top_lbs=0.0, init_btm_lbs=1800.0)
        state = _make_state(machines={'M1': machine})
        rls = state.rls_items['AU0001']
        bl = BeamLoad(
            start=_START, end=_START + timedelta(hours=2),
            bar='top', beam=_TOP_BEAM, lbs=2800.0,
        )
        state.commit_move(_move_with_plan([bl]))
        self.assertEqual(state.machines['M1'].activities, (bl,))
        self.assertEqual(rls.jobs, ())

    def test_commit_move_with_beam_load_btm(self):
        machine = _make_machine('M1', init_top_lbs=2800.0, init_btm_lbs=0.0)
        state = _make_state(machines={'M1': machine})
        rls = state.rls_items['AU0001']
        bl = BeamLoad(
            start=_START, end=_START + timedelta(hours=2),
            bar='btm', beam=_BTM_BEAM, lbs=1800.0,
        )
        state.commit_move(_move_with_plan([bl]))
        self.assertEqual(state.machines['M1'].activities, (bl,))
        self.assertEqual(rls.jobs, ())

    def test_commit_move_with_simple_style_change(self):
        state = _make_state()
        rls = state.rls_items['AU0001']
        sc = StyleChange(
            start=_START, end=_START + _SIMPLE_CHANGE,
            from_item=_ITEM_A, to_item=_ITEM_B, is_family_change=False,
        )
        state.commit_move(_move_with_plan([sc]))
        self.assertEqual(state.machines['M1'].activities, (sc,))
        self.assertEqual(rls.jobs, ())

    def test_commit_move_with_family_style_change(self):
        # _ITEM_B shares family with _ITEM_A here; what matters for the
        # routing test is the is_family_change flag and that the
        # activity flows through commit_move untouched.
        state = _make_state()
        rls = state.rls_items['AU0001']
        sc = StyleChange(
            start=_START, end=_START + _FAMILY_CHANGE,
            from_item=_ITEM_A, to_item=_ITEM_B, is_family_change=True,
        )
        state.commit_move(_move_with_plan([sc]))
        self.assertEqual(state.machines['M1'].activities, (sc,))
        self.assertEqual(rls.jobs, ())

    def test_commit_move_with_idle(self):
        state = _make_state()
        rls = state.rls_items['AU0001']
        idle = Idle(start=_START, end=_START + timedelta(hours=6))
        state.commit_move(_move_with_plan([idle]))
        self.assertEqual(state.machines['M1'].activities, (idle,))
        self.assertEqual(rls.jobs, ())

    # ----- 1.1.3 Multiple commit_move calls accumulate -----

    def test_two_commits_on_same_machine_preserve_order(self):
        state = _make_state()
        t0 = _START
        t1 = t0 + timedelta(hours=1)
        t2 = t1 + timedelta(hours=1)
        j1 = Job(start=t0, end=t1, item=_ITEM_A, lbs=100.0)
        j2 = Job(start=t1, end=t2, item=_ITEM_A, lbs=100.0)
        state.commit_move(_move_with_plan([j1]))
        state.commit_move(_move_with_plan([j2]))
        self.assertEqual(state.machines['M1'].activities, (j1, j2))
        self.assertEqual(state.machines['M1'].next_job_end, t2)

    def test_commits_on_different_machines_are_independent(self):
        state = _make_state(machines={
            'M1': _make_machine('M1'), 'M2': _make_machine('M2'),
        })
        t0 = _START
        t1 = t0 + timedelta(hours=1)
        job = Job(start=t0, end=t1, item=_ITEM_A, lbs=100.0)
        state.commit_move(_move_with_plan([job], machine_id='M1'))
        self.assertEqual(state.machines['M1'].activities, (job,))
        self.assertEqual(state.machines['M2'].activities, ())

    def test_jobs_for_same_item_accumulate_in_rls_item(self):
        state = _make_state(machines={
            'M1': _make_machine('M1'), 'M2': _make_machine('M2'),
        })
        rls = state.rls_items['AU0001']
        t0 = _START
        t1 = t0 + timedelta(hours=1)
        j_m1 = Job(start=t0, end=t1, item=_ITEM_A, lbs=100.0)
        j_m2 = Job(start=t0, end=t1, item=_ITEM_A, lbs=200.0)
        state.commit_move(_move_with_plan([j_m1], machine_id='M1'))
        state.commit_move(_move_with_plan([j_m2], machine_id='M2'))
        self.assertEqual(set(rls.jobs), {j_m1, j_m2})

    def test_jobs_for_different_items_route_to_correct_rls_items(self):
        state = _make_state(
            machines={'M1': _make_machine('M1')},
            rls_items={
                'AU0001': _make_rls_item(item=_ITEM_A),
                'AU0002': _make_rls_item(item=_ITEM_B),
            },
        )
        rls_a = state.rls_items['AU0001']
        rls_b = state.rls_items['AU0002']
        t0 = _START
        t1 = t0 + timedelta(hours=1)
        t2 = t1 + timedelta(hours=1)
        j_a = Job(start=t0, end=t1, item=_ITEM_A, lbs=100.0)
        j_b = Job(start=t1, end=t2, item=_ITEM_B, lbs=100.0)
        state.commit_move(_move_with_plan([j_a], item=_ITEM_A))
        state.commit_move(_move_with_plan([j_b], item=_ITEM_B))
        self.assertEqual(rls_a.jobs, (j_a,))
        self.assertEqual(rls_b.jobs, (j_b,))

    # ----- 1.1.4 Canonical run-up + transition + new-item plan -----

    def test_canonical_run_up_transition_plan(self):
        # Partial beams (top=180, btm=2000) with top_pct=btm_pct=0.5
        # mean producible-to-runout = 360 lbs. With tgt_wt=100 that's 3
        # complete rolls (Job A, 300 lbs) + a partial 60-lb roll
        # (Waste A). Then BeamLoad top (natural exhaustion → no
        # TapeOut), StyleChange A→B (same yarn, simple), Job B for the
        # requested 100 lbs.
        machine = _make_machine('M1', init_top_lbs=180.0,
                                init_btm_lbs=2000.0)
        state = _make_state(
            machines={'M1': machine},
            rls_items={
                'AU0001': _make_rls_item(item=_ITEM_A),
                'AU0002': _make_rls_item(item=_ITEM_B),
            },
        )
        rls_a = state.rls_items['AU0001']
        rls_b = state.rls_items['AU0002']

        plan = machine.plan_production(
            _ITEM_B, lbs=100.0, start_at='next_runout',
        )
        a_jobs = [
            a for a in plan if isinstance(a, Job) and a.item == _ITEM_A
        ]
        b_jobs = [
            a for a in plan if isinstance(a, Job) and a.item == _ITEM_B
        ]
        # Sanity: plan really does contain run-up Job(s) of A and new
        # production Job(s) of B.
        self.assertGreater(len(a_jobs), 0)
        self.assertGreater(len(b_jobs), 0)

        pre_a_need = rls_a.replenishment_need_lbs
        pre_b_need = rls_b.replenishment_need_lbs

        move = Move(
            machine_id='M1', item=_ITEM_B, lbs=100.0,
            start_at='next_runout', idle_for=timedelta(0),
            plan=plan,
        )
        state.commit_move(move)

        # 1. Machine has the full plan in order; current_status reflects
        # the post-plan state (current_item swapped to B).
        self.assertEqual(machine.activities, tuple(plan))
        self.assertEqual(machine.current_status.current_item, _ITEM_B)

        # 2. rls_a contains the run-up Job(s) of A.
        self.assertEqual(set(rls_a.jobs), set(a_jobs))
        # 3. rls_b contains the new Job(s) of B.
        self.assertEqual(set(rls_b.jobs), set(b_jobs))

        # 4. Each rls_item's view trackers updated — replenishment_need
        # decreased on both items since jobs covered some demand.
        self.assertLess(rls_a.replenishment_need_lbs, pre_a_need)
        self.assertLess(rls_b.replenishment_need_lbs, pre_b_need)

    # ----- 1.1.5 advance_window -----

    def test_advance_window_extends_by_default_amount(self):
        state = _make_state(window_end=_START)
        state.advance_window()
        self.assertEqual(state.window_end, _START + timedelta(hours=24))

    def test_advance_window_cumulative(self):
        state = _make_state(window_end=_START)
        state.advance_window()
        state.advance_window()
        self.assertEqual(state.window_end, _START + timedelta(hours=48))

    def test_advance_window_custom_amount(self):
        state = _make_state(
            window_end=_START,
            window_advance_amount=timedelta(hours=6),
        )
        state.advance_window()
        self.assertEqual(state.window_end, _START + timedelta(hours=6))


# --- 1.2 Costing -------------------------------------------------------

class CostingTests(unittest.TestCase):
    """Section 1.2 of INF_PLAN_TEST_SPEC.md.

    Each test below sets up a state with the relevant activities/jobs,
    chooses weights with non-zero values only for the components under
    test, and verifies that `Costing.score(state)` equals the hand-
    summed weighted total. The underlying view-tracker math and per-
    activity status updates are tested elsewhere; coverage here is
    about the right quantities getting multiplied by the right weights
    and summed."""

    # ----- 1.2.1 lateness, drainage, single tape-out, idle -----

    def test_lateness_drainage_single_tapeout_idle(self):
        rls = _make_rls_item(item=_ITEM_A, on_hand=0.0)  # below safety
        machine = _make_machine('M1')
        state = _make_state(
            machines={'M1': machine}, rls_items={'AU0001': rls},
        )
        # Plan: TapeOut('top') 4h, BeamLoad(top) 2h, Idle 2h, Job 1h.
        # The Job ends 9h past week-0 due (= START) → lateness > 0.
        # rls's on_hand = 0 < safety target 500 → drainage > 0.
        t0 = _START
        t1 = t0 + timedelta(hours=4)
        t2 = t1 + timedelta(hours=2)
        t3 = t2 + timedelta(hours=2)
        t4 = t3 + timedelta(hours=1)
        plan = [
            TapeOut(start=t0, end=t1, bars='top'),
            BeamLoad(start=t1, end=t2, bar='top',
                     beam=_TOP_BEAM, lbs=2800.0),
            Idle(start=t2, end=t3),
            Job(start=t3, end=t4, item=_ITEM_A, lbs=100.0),
        ]
        state.commit_move(Move(
            machine_id='M1', item=_ITEM_A, lbs=100.0,
            start_at='next_job_end', idle_for=timedelta(0), plan=plan,
        ))

        weights = _weights(
            lateness=10.0, drainage=1.0,
            tape_out_single=100.0, idle_time=50.0,
        )
        costing = Costing(weights)

        # Sanity: each covered demand component is non-trivial.
        self.assertGreater(rls.raw_view.lateness, 0)
        self.assertGreater(rls.safety_view.drainage, 0)

        expected = (
            weights.lateness * rls.raw_view.lateness
            + weights.drainage * rls.safety_view.drainage
            + weights.tape_out_single * 1       # one TapeOut('top')
            + weights.idle_time * 2.0           # 2 work-hours of Idle
        )
        self.assertAlmostEqual(costing.score(state), expected)

    # ----- 1.2.2 tape_out_both + family_change -----

    def test_cross_yarn_cross_family_transition(self):
        machine = _make_machine('M1')
        t0 = _START
        t1 = t0 + timedelta(hours=6)     # TapeOut('both') = 6h
        t2 = t1 + timedelta(hours=2)     # BeamLoad(top) = 2h
        t3 = t2 + timedelta(hours=2)     # BeamLoad(btm) = 2h
        t4 = t3 + _FAMILY_CHANGE         # StyleChange(family) = 1h
        plan = [
            TapeOut(start=t0, end=t1, bars='both'),
            BeamLoad(start=t1, end=t2, bar='top',
                     beam=_TOP_BEAM, lbs=2800.0),
            BeamLoad(start=t2, end=t3, bar='btm',
                     beam=_BTM_BEAM, lbs=1800.0),
            StyleChange(start=t3, end=t4,
                        from_item=_ITEM_A, to_item=_ITEM_B,
                        is_family_change=True),
        ]
        # Empty rls_items so there are no demand-side contributions.
        state = _make_state(machines={'M1': machine}, rls_items={})
        state.commit_move(Move(
            machine_id='M1', item=_ITEM_B, lbs=0.0,
            start_at='next_job_end', idle_for=timedelta(0), plan=plan,
        ))

        weights = _weights(tape_out_both=15.0, family_change=5.0)
        costing = Costing(weights)

        expected = weights.tape_out_both * 1 + weights.family_change * 1
        self.assertAlmostEqual(costing.score(state), expected)

    # ----- 1.2.3 excess -----

    def test_excess(self):
        # On-hand 0; register a Job at start_date with 1500 lbs. Allocation:
        # bucket 1 (week 0 = 100) + bucket 2 (safety = 500) + bucket 3
        # (weeks 1-3 = 300, with carrying) + bucket 4 (excess = 600).
        # excess weight is the only non-zero one, so the test confirms
        # only that contribution.
        rls = _make_rls_item(item=_ITEM_A, on_hand=0.0)
        machine = _make_machine('M1')
        state = _make_state(
            machines={'M1': machine}, rls_items={'AU0001': rls},
        )
        job = Job(start=_START, end=_START, item=_ITEM_A, lbs=1500.0)
        state.commit_move(Move(
            machine_id='M1', item=_ITEM_A, lbs=1500.0,
            start_at='next_job_end', idle_for=timedelta(0), plan=[job],
        ))

        self.assertGreater(rls.safety_view.excess, 0)

        weights = _weights(excess=5.0)
        costing = Costing(weights)
        expected = weights.excess * rls.safety_view.excess
        self.assertAlmostEqual(costing.score(state), expected)

    # ----- 1.2.4 carrying -----

    def test_carrying(self):
        # Job at start_date with 900 lbs = bucket 1 + bucket 2 + bucket 3.
        # Bucket 3 fills orders 1-3 with chunk_time = start_date, all of
        # which are past lead_time worth of holding, so carrying > 0.
        # No leftover lbs → no excess. weights isolate carrying.
        rls = _make_rls_item(item=_ITEM_A, on_hand=0.0)
        machine = _make_machine('M1')
        state = _make_state(
            machines={'M1': machine}, rls_items={'AU0001': rls},
        )
        job = Job(start=_START, end=_START, item=_ITEM_A, lbs=900.0)
        state.commit_move(Move(
            machine_id='M1', item=_ITEM_A, lbs=900.0,
            start_at='next_job_end', idle_for=timedelta(0), plan=[job],
        ))

        self.assertGreater(rls.safety_view.carrying, 0)

        weights = _weights(carrying=2.0)
        costing = Costing(weights)
        expected = weights.carrying * rls.safety_view.carrying
        self.assertAlmostEqual(costing.score(state), expected)

    # ----- 1.2.5 score_after_move (equivalence + purity) -----

    def test_score_after_move_equivalence_and_purity(self):
        rls = _make_rls_item(item=_ITEM_A, on_hand=0.0)
        machine = _make_machine('M1')
        state = _make_state(
            machines={'M1': machine}, rls_items={'AU0001': rls},
        )
        weights = _weights(
            lateness=10.0, drainage=1.0, carrying=2.0, excess=5.0,
            tape_out_single=100.0, tape_out_both=150.0,
            family_change=50.0, idle_time=10.0,
        )
        costing = Costing(weights)

        plan = machine.plan_production(
            _ITEM_A, lbs=100.0, start_at='next_job_end',
        )
        move = Move(
            machine_id='M1', item=_ITEM_A, lbs=100.0,
            start_at='next_job_end', idle_for=timedelta(0), plan=plan,
        )

        # --- Purity: snapshot state, call score_after_move, verify
        # nothing changed.
        pre_activities = machine.activities
        pre_jobs = rls.jobs
        pre_lateness = rls.raw_view.lateness
        pre_drainage = rls.safety_view.drainage
        pre_carrying = rls.safety_view.carrying
        pre_excess = rls.safety_view.excess
        pre_safety_pool = rls.safety_view.safety_pool

        predicted = costing.score_after_move(state, move)

        self.assertEqual(machine.activities, pre_activities)
        self.assertEqual(rls.jobs, pre_jobs)
        self.assertEqual(rls.raw_view.lateness, pre_lateness)
        self.assertEqual(rls.safety_view.drainage, pre_drainage)
        self.assertEqual(rls.safety_view.carrying, pre_carrying)
        self.assertEqual(rls.safety_view.excess, pre_excess)
        self.assertEqual(rls.safety_view.safety_pool, pre_safety_pool)

        # --- Equivalence: commit the move and verify score(state)
        # matches the prediction.
        state.commit_move(move)
        self.assertAlmostEqual(predicted, costing.score(state))


# --- 1.3 Candidate enumeration --------------------------------------------

class CandidateEnumerationTests(unittest.TestCase):
    """Section 1.3 of INF_PLAN_TEST_SPEC.md.

    Covers `eligible_decision_points`, `eligible_orders`, and
    `enumerate_candidates`. The two listing functions get exhaustive
    scenario coverage (sections 1.3.1 and 1.3.2). For
    `enumerate_candidates` the tests fall into two groups:

    - Section 1.3.3.1 verifies filtering by per-machine eligibility and
      that carrying-avoidance idle is wired through correctly.
    - Section 1.3.3.2 verifies that `move.lbs` is bounded by
      `Machine.producible_lbs_in_week`'s in-week production cap. We
      assert against the cap that `producible_lbs_in_week` itself would
      return for the same `(item, year, week, start)` triple — that's
      what the enumerator should be using — and bound that cap against
      the spec's ideal-formula upper bound as a sanity check."""

    # ----- helpers -----

    def _assert_orders_match(self, actual, expected, places=6):
        """Approximate equality for lists of RegularOrder / SafetyOrder.
        Compares types, items (by identity), week metadata for
        RegularOrders, and `lbs` within float tolerance."""
        self.assertEqual(len(actual), len(expected))
        for a, e in zip(actual, expected):
            self.assertIs(type(a), type(e))
            self.assertIs(a.item, e.item)
            self.assertAlmostEqual(a.lbs, e.lbs, places=places)
            if isinstance(a, RegularOrder):
                self.assertEqual(a.week_idx, e.week_idx)
                self.assertEqual(a.due_date, e.due_date)

    # ===================================================================
    # 1.3.1 eligible_decision_points
    # ===================================================================

    def test_eligible_dps_empty_state(self):
        state = _make_state(machines={}, rls_items={})
        self.assertEqual(eligible_decision_points(state), [])

    def test_eligible_dps_all_out_of_window(self):
        # next_job_end == start_date == _START on a fresh machine; setting
        # window_end before _START leaves every DP out of window.
        machine = _make_machine('M1')
        state = _make_state(
            machines={'M1': machine}, rls_items={},
            window_end=_START - timedelta(hours=1),
        )
        self.assertEqual(eligible_decision_points(state), [])

    def test_eligible_dps_both_in_window_distinct(self):
        # Default beams (top=2800, btm=1800, top_pct=btm_pct=0.5,
        # rate=100) → next_runout = _START + 36h. With window_end at
        # next_runout both DPs are in window and distinct.
        machine = _make_machine('M1')
        runout = machine.next_runout
        state = _make_state(
            machines={'M1': machine}, rls_items={},
            window_end=runout,
        )
        self.assertEqual(set(eligible_decision_points(state)), {
            DecisionPoint('M1', 'next_job_end', _START),
            DecisionPoint('M1', 'next_runout', runout),
        })

    def test_eligible_dps_both_in_window_coinciding(self):
        # Empty beams → next_runout coincides with next_job_end.
        machine = _make_machine(
            'M1', init_top_lbs=0.0, init_btm_lbs=0.0,
        )
        state = _make_state(
            machines={'M1': machine}, rls_items={},
            window_end=_START + timedelta(hours=24),
        )
        # Only the next_job_end entry is emitted; the coincident
        # next_runout is deduplicated.
        self.assertEqual(eligible_decision_points(state), [
            DecisionPoint('M1', 'next_job_end', _START),
        ])

    def test_eligible_dps_only_next_job_end_in_window(self):
        # Default beams; window covers next_job_end (= _START) but ends
        # before next_runout (= _START + 36h).
        machine = _make_machine('M1')
        state = _make_state(
            machines={'M1': machine}, rls_items={},
            window_end=_START + timedelta(hours=10),
        )
        self.assertEqual(eligible_decision_points(state), [
            DecisionPoint('M1', 'next_job_end', _START),
        ])

    # ----- 1.3.1.6 multi-machine sub-cases -----

    def test_eligible_dps_multi_all_dps_in_window(self):
        m1 = _make_machine('M1')
        m2 = _make_machine('M2')
        runout = m1.next_runout
        state = _make_state(
            machines={'M1': m1, 'M2': m2}, rls_items={},
            window_end=runout,
        )
        self.assertEqual(set(eligible_decision_points(state)), {
            DecisionPoint('M1', 'next_job_end', _START),
            DecisionPoint('M1', 'next_runout', runout),
            DecisionPoint('M2', 'next_job_end', _START),
            DecisionPoint('M2', 'next_runout', runout),
        })

    def test_eligible_dps_multi_only_job_ends_in_window(self):
        m1 = _make_machine('M1')
        m2 = _make_machine('M2')
        state = _make_state(
            machines={'M1': m1, 'M2': m2}, rls_items={},
            window_end=_START + timedelta(hours=10),
        )
        self.assertEqual(set(eligible_decision_points(state)), {
            DecisionPoint('M1', 'next_job_end', _START),
            DecisionPoint('M2', 'next_job_end', _START),
        })

    def test_eligible_dps_multi_subset_with_both_dps(self):
        # M1: both DPs in window. M2: out of window entirely (started
        # past window_end).
        m1 = _make_machine('M1')
        m2 = _make_machine(
            'M2', start=_START + timedelta(hours=48),
        )
        state = _make_state(
            machines={'M1': m1, 'M2': m2}, rls_items={},
            window_end=m1.next_runout,
        )
        self.assertEqual(set(eligible_decision_points(state)), {
            DecisionPoint('M1', 'next_job_end', _START),
            DecisionPoint('M1', 'next_runout', m1.next_runout),
        })

    def test_eligible_dps_multi_subset_only_job_ends(self):
        # All machines in window for next_job_end only. M3 runs the
        # family-C item _TC (whose machines dict includes 'M3').
        m1 = _make_machine('M1')
        m2 = _make_machine('M2')
        m3 = _make_machine(
            'M3', init_item=_TC,
            start=_START + timedelta(hours=24),
        )
        state = _make_state(
            machines={'M1': m1, 'M2': m2, 'M3': m3}, rls_items={},
            window_end=_START + timedelta(hours=30),
        )
        self.assertEqual(set(eligible_decision_points(state)), {
            DecisionPoint('M1', 'next_job_end', _START),
            DecisionPoint('M2', 'next_job_end', _START),
            DecisionPoint('M3', 'next_job_end',
                          _START + timedelta(hours=24)),
        })

    def test_eligible_dps_multi_mix_of_dps(self):
        # M1: both DPs in window (default beams, runout at +36h).
        # M2: only next_job_end in window — huge beams push next_runout
        # far past window_end.
        # M3: out of window entirely (starts past window_end).
        m1 = _make_machine('M1')
        m2 = _make_machine('M2', init_top_lbs=1e6, init_btm_lbs=1e6)
        m3 = _make_machine(
            'M3', init_item=_TC,
            start=_START + timedelta(hours=48),
        )
        state = _make_state(
            machines={'M1': m1, 'M2': m2, 'M3': m3}, rls_items={},
            window_end=_START + timedelta(hours=36),
        )
        self.assertEqual(set(eligible_decision_points(state)), {
            DecisionPoint('M1', 'next_job_end', _START),
            DecisionPoint('M1', 'next_runout',
                          _START + timedelta(hours=36)),
            DecisionPoint('M2', 'next_job_end', _START),
        })

    # ===================================================================
    # 1.3.2 eligible_orders
    # ===================================================================

    def test_eligible_orders_fully_satisfied(self):
        # (a) on_hand covers all weekly demand and the safety target.
        rls_a = RlsItem(
            item=_ITEM_A, start_date=_START, on_hand_lbs=900.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 100.0, 100.0, 100.0],
        )
        state_a = _make_state(machines={}, rls_items={'AU0001': rls_a})
        self._assert_orders_match(eligible_orders(state_a), [])

        # (b) zero on_hand baseline; a single 900-lb job at week-0 due
        # drives the same end state (all 4 weeks filled, safety at 500).
        rls_b = RlsItem(
            item=_ITEM_A, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 100.0, 100.0, 100.0],
        )
        rls_b.register_jobs([
            Job(start=_START, end=_START, item=_ITEM_A, lbs=900.0),
        ])
        state_b = _make_state(machines={}, rls_items={'AU0001': rls_b})
        self._assert_orders_match(eligible_orders(state_b), [])

    def test_eligible_orders_unmet_week0_only(self):
        # safety=0 so safety pool is trivially at target (0). Both
        # configurations leave week 0 with 100 unmet lbs; weeks 1-3
        # contribute nothing (zero demand or zero remaining).
        item = Greige(
            'AU_S0', family='A', tgt_wt=100.0,
            top_beam='40D BLACK 1000X4', top_pct=0.5,
            btm_beam='60D WHITE 1000X4', btm_pct=0.5,
            safety=0.0, machines={'M1': 100.0},
        )
        expected = [
            RegularOrder(item=item, week_idx=0,
                         due_date=_START, lbs=100.0),
        ]

        # (a) week 0 has the unmet 100 lbs directly via the constructor.
        rls_a = RlsItem(
            item=item, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 0.0, 0.0, 0.0],
        )
        state_a = _make_state(machines={}, rls_items={item.id: rls_a})
        self._assert_orders_match(eligible_orders(state_a), expected)

        # (b) week 0 demand=300; a 200-lb job at week-0 due leaves 100
        # unmet.
        rls_b = RlsItem(
            item=item, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[300.0, 0.0, 0.0, 0.0],
        )
        rls_b.register_jobs([
            Job(start=_START, end=_START, item=item, lbs=200.0),
        ])
        state_b = _make_state(machines={}, rls_items={item.id: rls_b})
        self._assert_orders_match(eligible_orders(state_b), expected)

    def test_eligible_orders_safety_below_target_only(self):
        expected = [SafetyOrder(item=_ITEM_A, lbs=500.0)]

        # (a) Zero demand and zero on_hand on _ITEM_A (safety=500) leave
        # safety pool empty.
        rls_a = RlsItem(
            item=_ITEM_A, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[0.0, 0.0, 0.0, 0.0],
        )
        state_a = _make_state(machines={}, rls_items={'AU0001': rls_a})
        self._assert_orders_match(eligible_orders(state_a), expected)

        # (b) weekly=[100]*4; a job late to every order fills bucket 1
        # for all 4 weeks but leaves bucket 2 (safety) empty.
        rls_b = RlsItem(
            item=_ITEM_A, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 100.0, 100.0, 100.0],
        )
        late_t = _START + timedelta(weeks=10)
        rls_b.register_jobs([
            Job(start=late_t, end=late_t, item=_ITEM_A, lbs=400.0),
        ])
        state_b = _make_state(machines={}, rls_items={'AU0001': rls_b})
        self._assert_orders_match(eligible_orders(state_b), expected)

    def test_eligible_orders_both_unmet_and_shortfall(self):
        expected = [
            RegularOrder(item=_ITEM_A, week_idx=0,
                         due_date=_START, lbs=100.0),
            SafetyOrder(item=_ITEM_A, lbs=500.0),
        ]

        # (a) weekly=[100, 0, 0, 0], no on_hand → week 0 fully unmet and
        # safety at 0 (target 500).
        rls_a = RlsItem(
            item=_ITEM_A, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 0.0, 0.0, 0.0],
        )
        state_a = _make_state(machines={}, rls_items={'AU0001': rls_a})
        self._assert_orders_match(eligible_orders(state_a), expected)

        # (b) weekly=[100]*4, no jobs → every week unmet but only the
        # earliest one surfaces as a RegularOrder, and safety still
        # short by 500.
        rls_b = RlsItem(
            item=_ITEM_A, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 100.0, 100.0, 100.0],
        )
        state_b = _make_state(machines={}, rls_items={'AU0001': rls_b})
        self._assert_orders_match(eligible_orders(state_b), expected)

    def test_eligible_orders_earliest_unmet_selection(self):
        item = Greige(
            'AU_S0', family='A', tgt_wt=100.0,
            top_beam='40D BLACK 1000X4', top_pct=0.5,
            btm_beam='60D WHITE 1000X4', btm_pct=0.5,
            safety=0.0, machines={'M1': 100.0},
        )
        expected = [
            RegularOrder(item=item, week_idx=0,
                         due_date=_START, lbs=100.0),
        ]

        # (a) on_hand=100 partially fills week-0 demand of 200; weeks 1-3
        # are entirely unfilled but only the earliest one (week 0)
        # appears.
        rls_a = RlsItem(
            item=item, start_date=_START, on_hand_lbs=100.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[200.0, 100.0, 100.0, 100.0],
        )
        state_a = _make_state(machines={}, rls_items={item.id: rls_a})
        self._assert_orders_match(eligible_orders(state_a), expected)

        # (b) same end state via a 100-lb job at week-0 due instead of
        # on_hand.
        rls_b = RlsItem(
            item=item, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[200.0, 100.0, 100.0, 100.0],
        )
        rls_b.register_jobs([
            Job(start=_START, end=_START, item=item, lbs=100.0),
        ])
        state_b = _make_state(machines={}, rls_items={item.id: rls_b})
        self._assert_orders_match(eligible_orders(state_b), expected)

    def test_eligible_orders_multiple_items_mixed_states(self):
        # Item 1: fully satisfied (no orders contributed).
        # Item 2: unmet week-0 only (one RegularOrder).
        # Item 3: safety below target only (one SafetyOrder).
        safety0 = Greige(
            'AU_S0', family='A', tgt_wt=100.0,
            top_beam='40D BLACK 1000X4', top_pct=0.5,
            btm_beam='60D WHITE 1000X4', btm_pct=0.5,
            safety=0.0, machines={'M1': 100.0},
        )
        rls1 = RlsItem(
            item=_ITEM_A, start_date=_START, on_hand_lbs=900.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 100.0, 100.0, 100.0],
        )
        rls2 = RlsItem(
            item=safety0, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 0.0, 0.0, 0.0],
        )
        rls3 = RlsItem(
            item=_ITEM_B, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[0.0, 0.0, 0.0, 0.0],
        )
        state = _make_state(machines={}, rls_items={
            'AU0001': rls1, safety0.id: rls2, 'AU0002': rls3,
        })
        # eligible_orders iterates rls_items in insertion order; each
        # item's contribution lands in that order. _ITEM_B has
        # safety=300 (per the module-level fixture).
        self._assert_orders_match(eligible_orders(state), [
            RegularOrder(item=safety0, week_idx=0,
                         due_date=_START, lbs=100.0),
            SafetyOrder(item=_ITEM_B, lbs=300.0),
        ])

    # ===================================================================
    # 1.3.3.1 enumerate_candidates filtering and idling correctness
    # ===================================================================

    def test_enumerate_candidates_trivial(self):
        # Two items in the same family; one machine programmed for each
        # at the start state. Orders are small and target week 0, so no
        # carrying-avoidance idle. Items run on both machines, so each
        # item gets a candidate per machine; we assert the
        # programmed-machine candidate has plan == [Job(item)].
        m1 = _make_machine('M1', init_item=_T1)
        m2 = _make_machine('M2', init_item=_T2)
        rls_t1 = RlsItem(
            item=_T1, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 0.0, 0.0, 0.0],
        )
        rls_t2 = RlsItem(
            item=_T2, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 0.0, 0.0, 0.0],
        )
        state = _make_state(
            machines={'M1': m1, 'M2': m2},
            rls_items={_T1.id: rls_t1, _T2.id: rls_t2},
            window_end=_START,  # only next_job_end DPs in window
        )
        moves = enumerate_candidates(state)

        for item, programmed_mchn in [(_T1, 'M1'), (_T2, 'M2')]:
            matching = [
                mv for mv in moves
                if mv.item.id == item.id
                and mv.machine_id == programmed_mchn
            ]
            self.assertEqual(
                len(matching), 1,
                f'expected 1 candidate for ({programmed_mchn}, {item.id})',
            )
            mv = matching[0]
            self.assertEqual(len(mv.plan), 1)
            self.assertIsInstance(mv.plan[0], Job)
            self.assertEqual(mv.plan[0].item, item)
            self.assertEqual(mv.idle_for, timedelta(0))

        # No move anywhere idles.
        for mv in moves:
            self.assertEqual(mv.idle_for, timedelta(0))
            self.assertFalse(any(isinstance(a, Idle) for a in mv.plan))

    def test_enumerate_candidates_multi_family(self):
        # Three items in three families. Machines partition by family
        # class: M1 and M2 run family A only, M3 runs family C only.
        m1 = _make_machine('M1', init_item=_T1)
        m2 = _make_machine('M2', init_item=_T2)
        m3 = _make_machine('M3', init_item=_TC)
        rls_t1 = RlsItem(
            item=_T1, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 0.0, 0.0, 0.0],
        )
        rls_t2 = RlsItem(
            item=_T2, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 0.0, 0.0, 0.0],
        )
        rls_tc = RlsItem(
            item=_TC, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 0.0, 0.0, 0.0],
        )
        state = _make_state(
            machines={'M1': m1, 'M2': m2, 'M3': m3},
            rls_items={_T1.id: rls_t1, _T2.id: rls_t2, _TC.id: rls_tc},
            window_end=_START,
        )
        moves = enumerate_candidates(state)

        # Every move must be runnable on its target machine.
        for mv in moves:
            self.assertTrue(
                mv.item.can_run_on_mchn(mv.machine_id),
                f'{mv.item.id} cannot run on {mv.machine_id}',
            )
        # Pairings that span family classes should never appear.
        pairings = {(mv.machine_id, mv.item.id) for mv in moves}
        for invalid in [
            ('M1', _TC.id), ('M2', _TC.id),
            ('M3', _T1.id), ('M3', _T2.id),
        ]:
            self.assertNotIn(invalid, pairings)
        # And at least one valid pairing per item is present.
        for item, valid_mchns in [
            (_T1, ('M1', 'M2')),
            (_T2, ('M1', 'M2')),
            (_TC, ('M3',)),
        ]:
            self.assertTrue(
                any((m, item.id) in pairings for m in valid_mchns),
                f'no valid candidate for {item.id}',
            )

    def test_enumerate_candidates_idling(self):
        # Earliest unmet week is week 2 (due _START + 14d). With
        # lead_time=0 and the default 24h carrying-avoidance margin, the
        # target effective_start = (_START + 14d) - 24h = _START + 13d.
        # dp.time = _START → idle work-hours = 13 × 24 = 312.
        m1 = _make_machine('M1', init_item=_T1)
        rls = RlsItem(
            item=_T1, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[0.0, 0.0, 100.0, 0.0],
        )
        state = _make_state(
            machines={'M1': m1},
            rls_items={_T1.id: rls},
            window_end=_START,
        )
        moves = enumerate_candidates(state)
        self.assertEqual(len(moves), 1)
        mv = moves[0]
        self.assertEqual(mv.idle_for, timedelta(hours=312))
        # The plan should start with the Idle gap of matching duration.
        self.assertIsInstance(mv.plan[0], Idle)
        self.assertEqual(
            mv.plan[0].end - mv.plan[0].start, mv.idle_for,
        )

    # ===================================================================
    # 1.3.3.2 enumerate_candidates lbs cap (move.lbs reflects
    # producible_lbs_in_week)
    # ===================================================================

    def test_enumerate_candidates_cap_mid_week_tail(self):
        # Machine running _T1 starts mid-Monday of ISO week 21 (Mon
        # 12:00). Beams of 1e6 each preclude any in-stream reloads, so
        # the producible cap equals the spec's ideal formula:
        # floor(156 work-hours × 100 lbs/h / 100 lbs/roll) × 100
        # = 15600 lbs.
        start = _START + timedelta(hours=12)
        machine = Machine(
            'M1', _T1, start,
            _TOP_BEAM, 1e6, _BTM_BEAM, 1e6,
            _24_7, _SIMPLE_CHANGE, _FAMILY_CHANGE,
        )
        rls = RlsItem(
            item=_T1, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[1_000_000.0, 0.0, 0.0, 0.0],
        )
        state = _make_state(
            machines={'M1': machine},
            rls_items={_T1.id: rls},
            window_end=start,
        )
        moves = enumerate_candidates(state)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0].lbs, 15600.0)

    def test_enumerate_candidates_cap_full_changeover(self):
        # Machine starts at week_start running _TD (family B, 30D/90D)
        # with 1e6-each beams. Order is for _T1 (family A, 40D/60D) —
        # both yarns differ and families differ, so the preamble is the
        # canonical full changeover:
        #   TapeOut('both')=6h + 2×BeamLoad=4h + family_change=1h = 11h.
        # After the preamble, beams are reset to plant-standard fresh
        # lbs (2800 top low-denier, 1800 btm high-denier), so the
        # production loop will hit in-stream reloads. We assert
        # move.lbs equals the actual producible cap, and bound that cap
        # against the spec's ideal-formula upper bound (which assumes
        # no in-stream reloads).
        machine = Machine(
            'M1', _TD, _START,
            BeamSet('30D RED 1000X4'), 1e6,
            BeamSet('90D GREEN 1000X4'), 1e6,
            _24_7, _SIMPLE_CHANGE, _FAMILY_CHANGE,
        )
        rls = RlsItem(
            item=_T1, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[1_000_000.0, 0.0, 0.0, 0.0],
        )
        state = _make_state(
            machines={'M1': machine},
            rls_items={_T1.id: rls},
            window_end=_START,
        )
        moves = enumerate_candidates(state)
        self.assertEqual(len(moves), 1)
        mv = moves[0]

        expected_cap = machine.producible_lbs_in_week(
            _T1, 2026, 21, start=_START,
        )
        self.assertEqual(mv.lbs, expected_cap)
        # Spec's ideal-formula upper bound: (week - preamble) × rate.
        ideal_upper = (168 - 11) * 100  # 15700 lbs
        self.assertGreater(mv.lbs, 0)
        self.assertLessEqual(mv.lbs, ideal_upper)
        # Preamble shape sanity: TapeOut('both'), two BeamLoads, family
        # StyleChange — all present, in order, before the first Job.
        kinds = [type(a).__name__ for a in mv.plan]
        first_job = kinds.index('Job')
        preamble = mv.plan[:first_job]
        self.assertEqual(
            [type(a).__name__ for a in preamble],
            ['TapeOut', 'BeamLoad', 'BeamLoad', 'StyleChange'],
        )
        self.assertEqual(preamble[0].bars, 'both')
        self.assertTrue(preamble[-1].is_family_change)

    def test_enumerate_candidates_cap_carrying_avoidance_idle(self):
        # Order for week 2 (due _START + 14d) forces carrying-avoidance
        # idle to (_START + 14d - 24h margin) = _START + 13d. The
        # effective start lands in ISO week 22 (May 25 - Jun 1) with
        # only 24 work-hours remaining before week_end. Item matches
        # the machine's current item and beams are huge → no preamble
        # and no in-stream reloads, so the cap matches the spec
        # formula: 24 × 100 = 2400 lbs.
        machine = Machine(
            'M1', _T1, _START,
            _TOP_BEAM, 1e6, _BTM_BEAM, 1e6,
            _24_7, _SIMPLE_CHANGE, _FAMILY_CHANGE,
        )
        rls = RlsItem(
            item=_T1, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[0.0, 0.0, 1_000_000.0, 0.0],
        )
        state = _make_state(
            machines={'M1': machine},
            rls_items={_T1.id: rls},
            window_end=_START,
        )
        moves = enumerate_candidates(state)
        self.assertEqual(len(moves), 1)
        mv = moves[0]
        self.assertEqual(mv.lbs, 2400.0)
        self.assertEqual(mv.idle_for, timedelta(hours=312))
        # Plan: a single Idle of 312h, then directly into the
        # production Job (no preamble since current item matches).
        self.assertIsInstance(mv.plan[0], Idle)
        self.assertEqual(mv.plan[0].end - mv.plan[0].start, mv.idle_for)
        jobs = [a for a in mv.plan if isinstance(a, Job)]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].item, _T1)
        self.assertEqual(jobs[0].lbs, 2400.0)

    def test_enumerate_candidates_cap_next_runout_dp(self):
        # Partial beams (top=600, btm=1000 with top_pct=btm_pct=0.5,
        # rate=100) force next_runout to fall 12 work-hours into ISO
        # week 21: producible_before_runout = min(600/0.5, 1000/0.5) =
        # 1200 lbs at rate 100 → 12h. Order is for _T2 (same yarn,
        # same family as _T1), so the cap-simulation preamble is a
        # single simple StyleChange.
        #
        # The cap simulation idles from as_of to next_runout (so the
        # beam state is unchanged from initial — top=600 partial,
        # btm=1000 partial), which forces in-stream reloads in the
        # post-style-change production loop. We bound the cap against
        # the spec's ideal-formula upper bound (which assumes no
        # in-stream reloads) and verify the move's plan structure.
        machine = Machine(
            'M1', _T1, _START,
            _TOP_BEAM, 600.0, _BTM_BEAM, 1000.0,
            _24_7, _SIMPLE_CHANGE, _FAMILY_CHANGE,
        )
        rls = RlsItem(
            item=_T2, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[1_000_000.0, 0.0, 0.0, 0.0],
        )
        state = _make_state(
            machines={'M1': machine},
            rls_items={_T2.id: rls},
            window_end=machine.next_runout,
        )
        moves = enumerate_candidates(state)
        # Two DPs (next_job_end + next_runout); we focus on the
        # next_runout one.
        runout_moves = [
            mv for mv in moves if mv.start_at == 'next_runout'
        ]
        self.assertEqual(len(runout_moves), 1)
        mv = runout_moves[0]

        # move.lbs comes from producible_lbs_in_week with
        # start=next_runout; verify the wiring.
        expected_cap = machine.producible_lbs_in_week(
            _T2, 2026, 21,
            start=machine.next_runout,
        )
        self.assertEqual(mv.lbs, expected_cap)
        # Spec's ideal-formula upper bound: week_hours -
        # to_next_runout_hours - simple_change_hours, in lbs.
        # = (168 - 12 - 0.25) × 100, floored to whole rolls.
        ideal_upper = 15500.0
        self.assertGreater(mv.lbs, 0)
        self.assertLessEqual(mv.lbs, ideal_upper)
        self.assertEqual(mv.lbs % _T2.tgt_wt, 0)

        # Plan structure: 'next_runout' mode emits a run-up Job of the
        # current item (_T1), then the preamble for _T2 (which here
        # includes a BeamLoad for the bar emptied during run-up since
        # the actual commit-side plan doesn't idle), and a simple
        # StyleChange (not a family change), and finally _T2 production
        # Jobs.
        first_job = next(
            i for i, a in enumerate(mv.plan) if isinstance(a, Job)
        )
        self.assertEqual(mv.plan[first_job].item, _T1)
        style_changes = [
            a for a in mv.plan if isinstance(a, StyleChange)
        ]
        self.assertEqual(len(style_changes), 1)
        self.assertFalse(style_changes[0].is_family_change)
        # No tape-outs anywhere in the plan.
        self.assertFalse(any(isinstance(a, TapeOut) for a in mv.plan))


# --- 1.4 Main loop --------------------------------------------------------

class MainLoopTests(unittest.TestCase):
    """Section 1.4 of INF_PLAN_TEST_SPEC.md.

    These tests exercise `plan(state, costing)` — the greedy
    enumerate → score → commit-lowest loop. The lower-level operations
    (enumerate, score_after_move, commit_move, advance_window) are
    covered by earlier sections; here we verify orchestration:
    termination behavior, that the loop places everything it can, that
    capacity-bound scenarios surface the right shortfalls, that the
    window advances and stops at the horizon as documented, and that
    the returned `PlanReport` matches the post-loop `State`."""

    # ===================================================================
    # 1.4.1 Termination
    # ===================================================================

    def test_plan_empty_state(self):
        # No machines, no rls_items — loop has nothing to do.
        state = _make_state(machines={}, rls_items={})
        report = plan(state, Costing(_weights()))
        self.assertEqual(report.schedules, {})
        self.assertEqual(report.jobs_by_item, {})
        self.assertEqual(report.total_score, 0.0)
        self.assertEqual(report.cost_components_by_item, {})
        self.assertEqual(report.unmet_lbs_by_item_week, {})

    def test_plan_no_machines_unmet_remains(self):
        # rls_items present but no machines — no candidates ever; every
        # week's full demand surfaces in unmet_lbs_by_item_week.
        rls = _make_rls_item(item=_ITEM_A)  # weekly=[100]*4, on_hand=0
        state = _make_state(machines={}, rls_items={'AU0001': rls})
        report = plan(state, Costing(_weights()))
        self.assertEqual(report.schedules, {})
        self.assertEqual(
            report.unmet_lbs_by_item_week,
            {('AU0001', wk): 100.0 for wk in range(4)},
        )

    def test_plan_all_demand_pre_satisfied(self):
        # on_hand alone covers all weekly demand AND the safety target,
        # so eligible_orders returns [] and the loop terminates without
        # committing anything.
        rls = RlsItem(
            item=_ITEM_A, start_date=_START, on_hand_lbs=900.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 100.0, 100.0, 100.0],
        )
        machine = _make_machine('M1')
        state = _make_state(
            machines={'M1': machine}, rls_items={'AU0001': rls},
        )
        report = plan(state, Costing(_weights(lateness=10, drainage=1)))
        self.assertEqual(report.schedules['M1'], ())
        self.assertEqual(report.jobs_by_item['AU0001'], ())
        self.assertEqual(report.unmet_lbs_by_item_week, {})

    def test_plan_idempotent_on_completed_state(self):
        # Running plan twice on the same (state, costing) commits nothing
        # the second time around.
        m = _big_beam_machine('M1', init_item=_T1)
        rls = RlsItem(
            item=_T1, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 100.0, 100.0, 100.0],
        )
        state = _make_state(
            machines={'M1': m}, rls_items={_T1.id: rls},
        )
        costing = Costing(_weights(
            lateness=10, drainage=1, carrying=1,
        ))
        report1 = plan(state, costing)
        acts1 = state.machines['M1'].activities
        jobs1 = state.rls_items[_T1.id].jobs

        report2 = plan(state, costing)
        acts2 = state.machines['M1'].activities
        jobs2 = state.rls_items[_T1.id].jobs

        # No new mutations.
        self.assertEqual(acts1, acts2)
        self.assertEqual(jobs1, jobs2)
        # Per-field report equality on everything the spec requires.
        self.assertEqual(report1.schedules, report2.schedules)
        self.assertEqual(report1.jobs_by_item, report2.jobs_by_item)
        self.assertAlmostEqual(report1.total_score, report2.total_score)
        self.assertEqual(
            report1.cost_components_by_item,
            report2.cost_components_by_item,
        )
        self.assertEqual(
            report1.unmet_lbs_by_item_week,
            report2.unmet_lbs_by_item_week,
        )

    # ===================================================================
    # 1.4.2 Demand fully placed (capacity available)
    # ===================================================================

    def test_plan_single_item_single_machine_fully_placed(self):
        # One machine with abundant beam capacity; 4 weeks of small
        # demand. Loop places every week.
        m = _big_beam_machine('M1', init_item=_T1)
        rls = RlsItem(
            item=_T1, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 100.0, 100.0, 100.0],
        )
        state = _make_state(
            machines={'M1': m}, rls_items={_T1.id: rls},
        )
        report = plan(state, Costing(_weights(lateness=10, drainage=1)))
        # Every safety-view order fully satisfied.
        for order in rls.safety_view.orders:
            self.assertEqual(order.remaining_lbs, 0.0)
        self.assertEqual(report.unmet_lbs_by_item_week, {})
        # Total scheduled lbs >= total demand (safety=0 for _T1).
        total_scheduled = sum(j.lbs for j in rls.jobs)
        self.assertGreaterEqual(total_scheduled, 400.0)

    def test_plan_single_item_multiple_machines(self):
        # Two identical eligible machines; the window mechanism spreads
        # work across both as each machine's next_job_end falls out of
        # window between commits.
        m1 = _big_beam_machine('M1', init_item=_T1)
        m2 = _big_beam_machine('M2', init_item=_T1)
        rls = RlsItem(
            item=_T1, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 100.0, 100.0, 100.0],
        )
        state = _make_state(
            machines={'M1': m1, 'M2': m2}, rls_items={_T1.id: rls},
        )
        report = plan(state, Costing(_weights(lateness=10, drainage=1)))
        # Demand fully placed.
        self.assertEqual(report.unmet_lbs_by_item_week, {})
        # Both machines saw at least one commit (the planner spreads
        # work across machines via the decision-window mechanism).
        self.assertGreater(len(report.schedules['M1']), 0)
        self.assertGreater(len(report.schedules['M2']), 0)

    def test_plan_multiple_items_multiple_machines(self):
        # Three items partitioned by family across three machines.
        # Every item is fully placed; per-machine eligibility honored.
        m1 = _big_beam_machine('M1', init_item=_T1)
        m2 = _big_beam_machine('M2', init_item=_T2)
        m3 = _big_beam_machine('M3', init_item=_TC)
        rls_t1 = RlsItem(
            item=_T1, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 100.0, 100.0, 100.0],
        )
        rls_t2 = RlsItem(
            item=_T2, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 100.0, 100.0, 100.0],
        )
        rls_tc = RlsItem(
            item=_TC, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 100.0, 100.0, 100.0],
        )
        state = _make_state(
            machines={'M1': m1, 'M2': m2, 'M3': m3},
            rls_items={_T1.id: rls_t1, _T2.id: rls_t2, _TC.id: rls_tc},
        )
        report = plan(state, Costing(_weights(lateness=10, drainage=1)))
        self.assertEqual(report.unmet_lbs_by_item_week, {})
        # Per-machine eligibility honored: every committed Job's item
        # can run on the machine it landed on.
        for m_id, schedule in report.schedules.items():
            for a in schedule:
                if isinstance(a, Job):
                    self.assertTrue(
                        a.item.can_run_on_mchn(m_id),
                        f'{a.item.id} committed on {m_id} '
                        'but cannot run there',
                    )

    # ===================================================================
    # 1.4.3 Capacity-bound (some demand unmet)
    # ===================================================================

    def test_plan_single_bottleneck(self):
        # Demand far exceeds what a single default-beam machine can
        # produce within the horizon (default beams force in-stream
        # reloads that cap weekly throughput well below 168×rate).
        machine = _make_machine('M1', init_item=_T1)
        rls = RlsItem(
            item=_T1, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[200_000.0, 0.0, 0.0, 0.0],
        )
        state = _make_state(
            machines={'M1': machine}, rls_items={_T1.id: rls},
        )
        report = plan(state, Costing(_weights(lateness=10, drainage=1)))
        # Loop committed *something*.
        scheduled = sum(j.lbs for j in state.rls_items[_T1.id].jobs)
        self.assertGreater(scheduled, 0.0)
        # …but a shortfall remains on week 0.
        self.assertIn((_T1.id, 0), report.unmet_lbs_by_item_week)
        self.assertGreater(
            report.unmet_lbs_by_item_week[(_T1.id, 0)], 0.0,
        )

    def test_plan_item_with_no_eligible_machines(self):
        # _T1 runs on M1/M2; _TC runs only on M3. With only M1/M2 in
        # state, _TC is unplaceable — every _TC week surfaces in
        # unmet_lbs_by_item_week, while _T1 is fully placed.
        m1 = _big_beam_machine('M1', init_item=_T1)
        m2 = _big_beam_machine('M2', init_item=_T2)
        rls_t1 = RlsItem(
            item=_T1, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 100.0, 100.0, 100.0],
        )
        rls_tc = RlsItem(
            item=_TC, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 100.0, 100.0, 100.0],
        )
        state = _make_state(
            machines={'M1': m1, 'M2': m2},
            rls_items={_T1.id: rls_t1, _TC.id: rls_tc},
        )
        report = plan(state, Costing(_weights(lateness=10, drainage=1)))
        # _TC: every week unmet at full lbs.
        for wk in range(4):
            self.assertEqual(
                report.unmet_lbs_by_item_week.get((_TC.id, wk)), 100.0,
            )
        # _T1: nothing unmet.
        for wk in range(4):
            self.assertNotIn((_T1.id, wk), report.unmet_lbs_by_item_week)

    def test_plan_tight_horizon(self):
        # planning_horizon_buffer = -14 days → horizon = latest_due - 14d
        # = (_START + 21d) - 14d = _START + 7d. The loop can only place
        # demand whose effective_start falls before _START + 7d, so the
        # later weeks must surface as unmet.
        m = _big_beam_machine('M1', init_item=_T1)
        rls = RlsItem(
            item=_T1, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 100.0, 100.0, 100.0],
        )
        state = _make_state(
            machines={'M1': m}, rls_items={_T1.id: rls},
            planning_horizon_buffer=-timedelta(days=14),
        )
        report = plan(state, Costing(_weights(lateness=10, drainage=1)))
        # Something is unmet (tight horizon cut off later weeks).
        self.assertGreater(len(report.unmet_lbs_by_item_week), 0)
        # Loop terminated without driving window_end far past the
        # horizon — at most one advance step past.
        horizon = (_START + timedelta(days=21)
                   + state.planning_horizon_buffer)
        self.assertLessEqual(
            state.window_end, horizon + state.window_advance_amount,
        )

    # ===================================================================
    # 1.4.4 Window advancement
    # ===================================================================

    def test_plan_narrow_initial_window_advances(self):
        # Start with window_end == start_date. After the first commit
        # M1.next_job_end pushes past window_end, forcing
        # advance_window() to keep the loop progressing. By the end
        # window has advanced past its initial value.
        m = _big_beam_machine('M1', init_item=_T1)
        rls = RlsItem(
            item=_T1, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 100.0, 100.0, 100.0],
        )
        state = _make_state(
            machines={'M1': m}, rls_items={_T1.id: rls},
            window_end=_START,
        )
        plan(state, Costing(_weights(lateness=10, drainage=1)))
        self.assertGreater(state.window_end, _START)

    def test_plan_threshold_driven_advancement(self):
        # With candidate_threshold > 1, the loop advances the window
        # aggressively to keep the pool topped up. The final
        # window_end with a high threshold is at-or-past the final
        # window_end achieved with threshold=1.
        def run(threshold: int) -> datetime:
            m = _big_beam_machine('M1', init_item=_T1)
            rls = RlsItem(
                item=_T1, start_date=_START, on_hand_lbs=0.0,
                lead_time=timedelta(0),
                weekly_lbs_needed=[100.0, 100.0, 100.0, 100.0],
            )
            state = _make_state(
                machines={'M1': m}, rls_items={_T1.id: rls},
                candidate_threshold=threshold,
            )
            plan(state, Costing(_weights(lateness=10, drainage=1)))
            return state.window_end

        self.assertGreaterEqual(run(10), run(1))

    def test_plan_stops_at_horizon(self):
        # After plan() returns, window_end should not exceed
        # horizon + one advance step. The advance check is
        # `window_end < horizon` before advancing, so a single-step
        # overshoot is the worst case.
        m = _big_beam_machine('M1', init_item=_T1)
        rls = RlsItem(
            item=_T1, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 100.0, 100.0, 100.0],
        )
        state = _make_state(
            machines={'M1': m}, rls_items={_T1.id: rls},
        )
        plan(state, Costing(_weights(lateness=10, drainage=1)))
        # Latest due for the 4-week demand is _START + 21 days.
        horizon = (_START + timedelta(days=21)
                   + state.planning_horizon_buffer)
        self.assertLessEqual(
            state.window_end, horizon + state.window_advance_amount,
        )

    # ===================================================================
    # 1.4.5 PlanReport snapshot fidelity
    # ===================================================================

    def test_plan_report_matches_state(self):
        # Run a non-trivial scenario; verify every PlanReport field
        # mirrors the post-loop state.
        m1 = _big_beam_machine('M1', init_item=_T1)
        m2 = _big_beam_machine('M2', init_item=_T2)
        rls_t1 = RlsItem(
            item=_T1, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 100.0, 100.0, 100.0],
        )
        rls_t2 = RlsItem(
            item=_T2, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 100.0, 100.0, 100.0],
        )
        state = _make_state(
            machines={'M1': m1, 'M2': m2},
            rls_items={_T1.id: rls_t1, _T2.id: rls_t2},
        )
        costing = Costing(_weights(
            lateness=10, drainage=1, carrying=1, excess=1,
            tape_out_single=1, tape_out_both=1,
            family_change=1, idle_time=0.1,
        ))
        report = plan(state, costing)

        # 1. schedules mirror state.machines[*].activities.
        for m_id, machine in state.machines.items():
            self.assertEqual(report.schedules[m_id], machine.activities)
        self.assertEqual(set(report.schedules), set(state.machines))

        # 2. jobs_by_item mirrors state.rls_items[*].jobs.
        for item_id, rls in state.rls_items.items():
            self.assertEqual(report.jobs_by_item[item_id], rls.jobs)
        self.assertEqual(
            set(report.jobs_by_item), set(state.rls_items),
        )

        # 3. total_score equals the score recomputed on the state.
        self.assertAlmostEqual(report.total_score, costing.score(state))

        # 4. cost_components_by_item matches the view trackers.
        for item_id, rls in state.rls_items.items():
            cc = report.cost_components_by_item[item_id]
            self.assertEqual(cc.lateness, rls.raw_view.lateness)
            self.assertEqual(cc.drainage, rls.safety_view.drainage)
            self.assertEqual(cc.carrying, rls.safety_view.carrying)
            self.assertEqual(cc.excess, rls.safety_view.excess)

        # 5. unmet_lbs_by_item_week contains exactly the (item, week)
        # pairs with positive remaining_lbs in the safety view; lbs
        # values match.
        actual_unmet = {}
        for item_id, rls in state.rls_items.items():
            for order in rls.safety_view.orders:
                if order.remaining_lbs > 0:
                    actual_unmet[(item_id, order.week.week_idx)] = (
                        order.remaining_lbs
                    )
        self.assertEqual(report.unmet_lbs_by_item_week, actual_unmet)


if __name__ == '__main__':
    unittest.main()
