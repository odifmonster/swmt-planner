#!/usr/bin/env python

import unittest
from datetime import datetime, timedelta

from swmtplanner.products import Greige, BeamSet, BeamSetDesc
from swmtplanner.schedule import (
    Machine, Knit, Job, Roll, ProductionPlan,
    Waste, Doff, TapeOut, Hanging, Threading,
    StyleChange, RunnerChange, PatternChange, Idle,
)
from swmtplanner.demand.rlsitem import RlsItem
from swmtplanner.support import WorkCal
from swmtplanner.planners.infinite import (
    State, Move, CostWeights, Costing,
    DecisionPoint, OrderKey, RegularOrder, SafetyOrder, ScoringContext,
    assign_priorities, eligible_decision_points, eligible_orders,
    enumerate_candidates,
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

_FIXTURE_DATE = datetime(2026, 1, 1)
_TOP_BEAM = BeamSet.new(BeamSetDesc('40D BLACK 1000X4'), 2800.0, _FIXTURE_DATE)
_BTM_BEAM = BeamSet.new(BeamSetDesc('60D WHITE 1000X4'), 1800.0, _FIXTURE_DATE)


def _with_lbs(beam: BeamSet, lbs: float) -> BeamSet:
    """The fixture set carrying `lbs` — what a `Hanging` loads onto a bar."""
    return beam.returned(lbs, beam.avail_date)

_START = datetime(2026, 5, 18, 0, 0)


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
# preamble must include TapeOut('both') + a 'both' re-thread (Hanging +
# Threading) + a PatternChange (legacy cross-family).
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
        _24_7, is_new=is_new,
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


def _plan(activities=(), jobs=()) -> ProductionPlan:
    """Wrap activity-stream and Job-record lists into a ProductionPlan."""
    return ProductionPlan(activities=tuple(activities), jobs=tuple(jobs))


def _job_rec(item: Greige, lbs: float, completion_time: datetime) -> Job:
    """A Job record delivering `lbs` as a single roll completing at
    `completion_time` (the demand views read per-roll completion times)."""
    return Job(
        item=item, rolls=(Roll(lbs=lbs, completion_time=completion_time),),
    )


def _move_with_plan(
    activities=(),
    jobs=(),
    machine_id: str = 'M1',
    item: Greige = _ITEM_A,
) -> Move:
    """Convenience for the 1.1 tests, where only the plan matters: build a
    Move whose `ProductionPlan` carries the given activity stream and Job
    records, with placeholder values for the bookkeeping fields the State
    doesn't touch."""
    return Move(
        machine_id=machine_id, item=item, lbs=0.0,
        start_at='schedule_tail', idle_for=timedelta(0),
        plan=_plan(activities, jobs),
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
        _24_7, is_new=is_new,
    )


def _weights(**overrides) -> CostWeights:
    """Build CostWeights with all fields defaulting to 0.0 and the
    specified ones overridden. Lets each 1.2 test set only the weights
    its scenario exercises, so the score formula reduces to those
    weights times the corresponding quantities."""
    defaults = dict(
        lateness=0.0, drainage=0.0, carrying=0.0, excess=0.0,
        tape_out_single=0.0, tape_out_both=0.0,
        style_change=0.0, runner_change=0.0, pattern_change=0.0,
        idle_time=0.0, waste_lbs=0.0,
        priority=0.0, level_loading=0.0, old_machine=0.0,
        recovery=0.0,
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

    def test_commit_move_with_knit_activity_does_not_touch_rls_item(self):
        # The productive *activity* is a Knit; it goes to the activity
        # schedule only. Production records (Jobs) are routed separately.
        state = _make_state()
        rls = state.rls_items['AU0001']
        knit = Knit(
            start=_START, end=_START + timedelta(hours=1),
            item=_ITEM_A, lbs=100.0,
        )
        state.commit_move(_move_with_plan([knit]))
        self.assertEqual(state.machines['M1'].activities, (knit,))
        self.assertEqual(state.machines['M1'].jobs, ())
        self.assertEqual(rls.jobs, ())

    def test_commit_move_with_job_record_routes_to_machine_jobs_and_rls(self):
        # A Job record in plan.jobs lands on machine.jobs and on the
        # matching rls_item.jobs (via register_jobs); it is not an activity.
        state = _make_state()
        rls = state.rls_items['AU0001']
        job = _job_rec(
            _ITEM_A, lbs=100.0, completion_time=_START + timedelta(hours=1),
        )
        state.commit_move(_move_with_plan(jobs=[job]))
        self.assertEqual(state.machines['M1'].jobs, (job,))
        self.assertEqual(rls.jobs, (job,))
        self.assertEqual(state.machines['M1'].activities, ())

    def test_commit_move_with_waste_does_not_touch_rls_item(self):
        state = _make_state()
        rls = state.rls_items['AU0001']
        waste = Waste(
            start=_START, end=_START,
            beam=_TOP_BEAM, bar='top', lbs=50.0,
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

    def test_commit_move_with_doff(self):
        state = _make_state()
        rls = state.rls_items['AU0001']
        doff = Doff(start=_START, end=_START + timedelta(minutes=20))
        state.commit_move(_move_with_plan([doff]))
        self.assertEqual(state.machines['M1'].activities, (doff,))
        self.assertEqual(rls.jobs, ())

    def test_commit_move_with_hanging_top(self):
        # Start with empty top so the Hanging is consistent with state.
        machine = _make_machine('M1', init_top_lbs=0.0, init_btm_lbs=1800.0)
        state = _make_state(machines={'M1': machine})
        rls = state.rls_items['AU0001']
        h = Hanging(
            start=_START, end=_START + timedelta(hours=1),
            bars='top', top_beam=_with_lbs(_TOP_BEAM, 2800.0),
        )
        state.commit_move(_move_with_plan([h]))
        self.assertEqual(state.machines['M1'].activities, (h,))
        self.assertEqual(rls.jobs, ())

    def test_commit_move_with_hanging_threading_btm(self):
        machine = _make_machine('M1', init_top_lbs=2800.0, init_btm_lbs=0.0)
        state = _make_state(machines={'M1': machine})
        rls = state.rls_items['AU0001']
        h = Hanging(
            start=_START, end=_START + timedelta(hours=1),
            bars='btm', btm_beam=_with_lbs(_BTM_BEAM, 1800.0),
        )
        t = Threading(
            start=h.end, end=h.end + timedelta(hours=2), bars='btm',
        )
        state.commit_move(_move_with_plan([h, t]))
        self.assertEqual(state.machines['M1'].activities, (h, t))
        self.assertEqual(rls.jobs, ())

    def test_commit_move_with_style_change(self):
        state = _make_state()
        rls = state.rls_items['AU0001']
        sc = StyleChange(
            start=_START, end=_START + timedelta(minutes=5),
            from_item=_ITEM_A, to_item=_ITEM_B,
        )
        state.commit_move(_move_with_plan([sc]))
        self.assertEqual(state.machines['M1'].activities, (sc,))
        self.assertEqual(rls.jobs, ())

    def test_commit_move_with_runner_change(self):
        state = _make_state()
        rls = state.rls_items['AU0001']
        rc = RunnerChange(
            start=_START, end=_START + timedelta(minutes=45),
            from_item=_ITEM_A, to_item=_ITEM_B,
        )
        state.commit_move(_move_with_plan([rc]))
        self.assertEqual(state.machines['M1'].activities, (rc,))
        self.assertEqual(rls.jobs, ())

    def test_commit_move_with_pattern_change(self):
        state = _make_state()
        rls = state.rls_items['AU0001']
        pc = PatternChange(
            start=_START, end=_START + timedelta(hours=1, minutes=30),
            from_item=_ITEM_A, to_item=_ITEM_B,
        )
        state.commit_move(_move_with_plan([pc]))
        self.assertEqual(state.machines['M1'].activities, (pc,))
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
        k1 = Knit(start=t0, end=t1, item=_ITEM_A, lbs=100.0)
        k2 = Knit(start=t1, end=t2, item=_ITEM_A, lbs=100.0)
        state.commit_move(_move_with_plan([k1]))
        state.commit_move(_move_with_plan([k2]))
        self.assertEqual(state.machines['M1'].activities, (k1, k2))
        self.assertEqual(state.machines['M1'].schedule_tail, t2)

    def test_commits_on_different_machines_are_independent(self):
        state = _make_state(machines={
            'M1': _make_machine('M1'), 'M2': _make_machine('M2'),
        })
        t0 = _START
        t1 = t0 + timedelta(hours=1)
        knit = Knit(start=t0, end=t1, item=_ITEM_A, lbs=100.0)
        state.commit_move(_move_with_plan([knit], machine_id='M1'))
        self.assertEqual(state.machines['M1'].activities, (knit,))
        self.assertEqual(state.machines['M2'].activities, ())

    def test_jobs_for_same_item_accumulate_in_rls_item(self):
        state = _make_state(machines={
            'M1': _make_machine('M1'), 'M2': _make_machine('M2'),
        })
        rls = state.rls_items['AU0001']
        t0 = _START
        t1 = t0 + timedelta(hours=1)
        j_m1 = _job_rec(_ITEM_A, lbs=100.0, completion_time=t1)
        j_m2 = _job_rec(_ITEM_A, lbs=200.0, completion_time=t1)
        state.commit_move(_move_with_plan(jobs=[j_m1], machine_id='M1'))
        state.commit_move(_move_with_plan(jobs=[j_m2], machine_id='M2'))
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
        j_a = _job_rec(_ITEM_A, lbs=100.0, completion_time=t1)
        j_b = _job_rec(_ITEM_B, lbs=100.0, completion_time=t2)
        state.commit_move(_move_with_plan(jobs=[j_a], item=_ITEM_A))
        state.commit_move(_move_with_plan(jobs=[j_b], item=_ITEM_B))
        self.assertEqual(rls_a.jobs, (j_a,))
        self.assertEqual(rls_b.jobs, (j_b,))

    # ----- 1.1.4 Canonical run-up + transition + new-item plan -----

    def test_canonical_run_up_transition_plan(self):
        # Partial beams (top=180, btm=2000) with top_pct=btm_pct=0.5.
        # Run-up usable top = (180-5)/0.5 = 350 fabric lbs -> 3 whole
        # rolls (Job A, 300 lbs); the run-up emits whole rolls only (no
        # partial-roll Waste). Then the same-yarn changeover A->B (a
        # RunnerChange on this legacy machine) and Job B for the requested
        # 100 lbs; the near-empty top is re-threaded inside B's loop.
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
        a_jobs = [j for j in plan.jobs if j.item == _ITEM_A]
        b_jobs = [j for j in plan.jobs if j.item == _ITEM_B]
        # Sanity: plan really does carry a run-up Job of A and a new
        # production Job of B.
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

        # 1. Machine has the full activity stream in order; current_status
        # reflects the post-plan state (current_item swapped to B).
        self.assertEqual(machine.activities, plan.activities)
        self.assertEqual(machine.current_status.current_item, _ITEM_B)
        # 2. machine.jobs holds both Job records.
        self.assertEqual(machine.jobs, plan.jobs)

        # 3. rls_a contains the run-up Job(s) of A.
        self.assertEqual(set(rls_a.jobs), set(a_jobs))
        # 4. rls_b contains the new Job(s) of B.
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
        # Plan: TapeOut('top') 4h, re-thread top (Hanging + Threading,
        # both unweighted), Idle 2h, Knit 1h. The Job ends past week-0 due
        # (= START) → lateness > 0. rls's on_hand = 0 < safety target 500
        # → drainage > 0.
        t0 = _START
        t1 = t0 + timedelta(hours=4)      # TapeOut('top')
        t2 = t1 + timedelta(hours=1)      # Hanging(top)
        t3 = t2 + timedelta(hours=2)      # Threading(top)
        t4 = t3 + timedelta(hours=2)      # Idle (2 work-hours)
        t5 = t4 + timedelta(hours=1)      # Knit
        # Activity stream drives the schedule penalties (TapeOut, Idle);
        # the Job record (its roll completing at t5, past due) drives the
        # demand-side lateness/drainage. The re-thread is unweighted.
        plan = _plan(
            activities=[
                TapeOut(start=t0, end=t1, bars='top'),
                Hanging(start=t1, end=t2, bars='top',
                        top_beam=_with_lbs(_TOP_BEAM, 2800.0)),
                Threading(start=t2, end=t3, bars='top'),
                Idle(start=t3, end=t4),
                Knit(start=t4, end=t5, item=_ITEM_A, lbs=100.0),
            ],
            jobs=[_job_rec(_ITEM_A, lbs=100.0, completion_time=t5)],
        )
        state.commit_move(Move(
            machine_id='M1', item=_ITEM_A, lbs=100.0,
            start_at='schedule_tail', idle_for=timedelta(0), plan=plan,
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

    # ----- 1.2.2 changeover types + double tape-out -----

    def _commit_changeover_plan(self, activities):
        """Commit a beam-work-only plan (no Jobs) onto an empty-demand
        state and return it, so the score reduces to the schedule
        penalties of `activities`."""
        machine = _make_machine('M1')
        state = _make_state(machines={'M1': machine}, rls_items={})
        state.commit_move(Move(
            machine_id='M1', item=_ITEM_B, lbs=0.0,
            start_at='schedule_tail', idle_for=timedelta(0),
            plan=_plan(activities=activities),
        ))
        return state

    def test_legacy_cross_family_full_changeover(self):
        # TapeOut('both') + a 'both' re-thread (Hanging + Threading,
        # unweighted) + PatternChange. Covers tape_out_both, pattern_change.
        t0 = _START
        t1 = t0 + timedelta(hours=3)      # TapeOut('both')
        t2 = t1 + timedelta(hours=1, minutes=30)   # Hanging('both')
        t3 = t2 + timedelta(hours=3, minutes=30)   # Threading('both')
        t4 = t3 + timedelta(hours=1, minutes=30)   # PatternChange
        state = self._commit_changeover_plan([
            TapeOut(start=t0, end=t1, bars='both'),
            Hanging(start=t1, end=t2, bars='both',
                    top_beam=_with_lbs(_TOP_BEAM, 2800.0),
                    btm_beam=_with_lbs(_BTM_BEAM, 1800.0)),
            Threading(start=t2, end=t3, bars='both'),
            PatternChange(start=t3, end=t4,
                          from_item=_ITEM_A, to_item=_ITEM_B),
        ])
        weights = _weights(tape_out_both=15.0, pattern_change=5.0)
        expected = weights.tape_out_both * 1 + weights.pattern_change * 1
        self.assertAlmostEqual(Costing(weights).score(state), expected)

    def test_legacy_same_family_runner_change(self):
        # A RunnerChange (legacy, same family) is the only weighted
        # schedule activity; tape_out weights are 0. Covers runner_change.
        state = self._commit_changeover_plan([
            RunnerChange(start=_START, end=_START + timedelta(minutes=45),
                         from_item=_ITEM_A, to_item=_ITEM_B),
        ])
        weights = _weights(runner_change=7.0)
        self.assertAlmostEqual(Costing(weights).score(state),
                               weights.runner_change * 1)

    def test_new_machine_style_change(self):
        # A StyleChange (the only class a new machine emits). Covers
        # style_change.
        state = self._commit_changeover_plan([
            StyleChange(start=_START, end=_START + timedelta(minutes=5),
                        from_item=_ITEM_A, to_item=_ITEM_B),
        ])
        weights = _weights(style_change=3.0)
        self.assertAlmostEqual(Costing(weights).score(state),
                               weights.style_change * 1)

    # ----- 1.2.3 waste (discarded yarn) -----

    def test_waste_discarded_yarn(self):
        # A plan with two zero-duration Waste activities (45 + 55 lbs).
        # waste_lbs is the only non-zero weight, so the score reduces to
        # w_waste_lbs * sum(Waste.lbs). Empty rls_items -> no demand-side
        # contributions; Waste is zero-duration -> no idle/time term.
        machine = _make_machine('M1')
        plan = _plan(activities=[
            Waste(start=_START, end=_START, beam=_TOP_BEAM, bar='top', lbs=45.0),
            Waste(start=_START, end=_START, beam=_BTM_BEAM, bar='btm', lbs=55.0),
        ])
        state = _make_state(machines={'M1': machine}, rls_items={})
        state.commit_move(Move(
            machine_id='M1', item=_ITEM_A, lbs=0.0,
            start_at='schedule_tail', idle_for=timedelta(0), plan=plan,
        ))

        weights = _weights(waste_lbs=2.0)
        costing = Costing(weights)
        expected = weights.waste_lbs * (45.0 + 55.0)
        self.assertAlmostEqual(costing.score(state), expected)

    # ----- 1.2.4 excess -----

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
        job = _job_rec(_ITEM_A, lbs=1500.0, completion_time=_START)
        state.commit_move(Move(
            machine_id='M1', item=_ITEM_A, lbs=1500.0,
            start_at='schedule_tail', idle_for=timedelta(0),
            plan=_plan(jobs=[job]),
        ))

        self.assertGreater(rls.safety_view.excess, 0)

        weights = _weights(excess=5.0)
        costing = Costing(weights)
        expected = weights.excess * rls.safety_view.excess
        self.assertAlmostEqual(costing.score(state), expected)

    # ----- 1.2.5 carrying -----

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
        job = _job_rec(_ITEM_A, lbs=900.0, completion_time=_START)
        state.commit_move(Move(
            machine_id='M1', item=_ITEM_A, lbs=900.0,
            start_at='schedule_tail', idle_for=timedelta(0),
            plan=_plan(jobs=[job]),
        ))

        self.assertGreater(rls.safety_view.carrying, 0)

        weights = _weights(carrying=2.0)
        costing = Costing(weights)
        expected = weights.carrying * rls.safety_view.carrying
        self.assertAlmostEqual(costing.score(state), expected)

    # ----- 1.2.6 score_after_move (equivalence + purity) -----

    def test_score_after_move_equivalence_and_purity(self):
        rls = _make_rls_item(item=_ITEM_A, on_hand=0.0)
        machine = _make_machine('M1')
        state = _make_state(
            machines={'M1': machine}, rls_items={'AU0001': rls},
        )
        # All Phase 1 weights non-zero; Phase 2 weights zero so the
        # cross-cutting term is 0 regardless of ctx contents — this test
        # is about the equivalence of per-item + per-machine costing
        # before vs after commit.
        weights = _weights(
            lateness=10.0, drainage=1.0, carrying=2.0, excess=5.0,
            tape_out_single=100.0, tape_out_both=150.0,
            style_change=50.0, runner_change=60.0, pattern_change=70.0,
            idle_time=10.0,
        )
        costing = Costing(weights)

        plan = machine.plan_production(
            _ITEM_A, lbs=100.0, start_at='schedule_tail',
        )
        move = Move(
            machine_id='M1', item=_ITEM_A, lbs=100.0,
            start_at='schedule_tail', idle_for=timedelta(0), plan=plan,
        )
        # Minimal ctx — Phase 2 weights are 0, so its contents don't
        # affect the score, but score_after_move requires a ctx.
        ctx = ScoringContext(
            priorities={},
            regular_orders_by_key={},
            earliest_dp_excluding={},
            earliest_dp_time=machine.schedule_tail,
            new_machine_avail={},
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

        predicted = costing.score_after_move(state, move, ctx)

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


# --- 1.2.7 Priority cost --------------------------------------------------

class PriorityCostTests(unittest.TestCase):
    """Section 1.2.7 of INF_PLAN_TEST_SPEC.md.

    Verifies the opportunity-cost shape of `Costing._priority_cost`
    against four scenarios that span the three priority buckets
    (urgent regular / safety / future regular). All tests use a shared
    four-item state and assert on `Costing._priority_cost(...)` with
    `w.priority = 1.0` and every other weight = 0."""

    # Greige fixtures for the four items. Same beam/tgt_wt/family across
    # the board — only `safety` and the `machines` dict matter for the
    # priority cost.
    _U_LOW = Greige(
        'U_LOW', family='A', tgt_wt=100.0,
        top_beam='40D BLACK 1000X4', top_pct=0.5,
        btm_beam='60D WHITE 1000X4', btm_pct=0.5,
        safety=0.0, machines={'M1': 100.0, 'M2': 100.0},
    )
    _U_HIGH = Greige(
        'U_HIGH', family='A', tgt_wt=100.0,
        top_beam='40D BLACK 1000X4', top_pct=0.5,
        btm_beam='60D WHITE 1000X4', btm_pct=0.5,
        safety=100.0, machines={'M1': 100.0, 'M2': 100.0},
    )
    _SAFETY_ITEM = Greige(
        'SAFETY', family='A', tgt_wt=100.0,
        top_beam='40D BLACK 1000X4', top_pct=0.5,
        btm_beam='60D WHITE 1000X4', btm_pct=0.5,
        safety=100.0, machines={'M1': 100.0, 'M2': 100.0},
    )
    _FUTURE = Greige(
        'FUTURE', family='A', tgt_wt=100.0,
        top_beam='40D BLACK 1000X4', top_pct=0.5,
        btm_beam='60D WHITE 1000X4', btm_pct=0.5,
        safety=0.0, machines={'M1': 100.0, 'M2': 100.0},
    )

    def setUp(self):
        """Build the shared 1.2.7 state, derive priorities, pack a
        `ScoringContext`, and build a `Costing` instance with
        `w.priority = 1.0` (all other weights 0). Stored on `self` for
        each test to read."""
        # U_LOW: weekly=[300, 100, 0, 0], on_hand=300 → bucket 1 fills
        # week 0 (300), no safety (target=0), week 1 unmet 100 lbs.
        rls_u_low = RlsItem(
            item=self._U_LOW, start_date=_START, on_hand_lbs=300.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[300, 100, 0, 0],
        )
        # U_HIGH: weekly=[300, 200, 0, 0], on_hand=400 → bucket 1
        # fills week 0 (300), bucket 2 fills safety (100=target),
        # week 1 unmet 200 lbs.
        rls_u_high = RlsItem(
            item=self._U_HIGH, start_date=_START, on_hand_lbs=400.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[300, 200, 0, 0],
        )
        # SAFETY: weekly=[0]*4, on_hand=50 → no demand, safety pool=50
        # (target=100 → SafetyOrder gap=50). No regular orders.
        rls_safety = RlsItem(
            item=self._SAFETY_ITEM, start_date=_START, on_hand_lbs=50.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[0, 0, 0, 0],
        )
        # FUTURE: weekly=[0, 0, 0, 100], on_hand=0 → week 3 unmet 100.
        rls_future = RlsItem(
            item=self._FUTURE, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[0, 0, 0, 100],
        )
        m1 = _make_machine('M1')
        m2 = _make_machine('M2')
        self.state = _make_state(
            machines={'M1': m1, 'M2': m2},
            rls_items={
                'U_LOW': rls_u_low, 'U_HIGH': rls_u_high,
                'SAFETY': rls_safety, 'FUTURE': rls_future,
            },
        )

        priorities = assign_priorities(self.state)
        regular_orders_by_key: dict[OrderKey, RegularOrder] = {}
        self.u_low_reg = None
        self.u_high_reg = None
        self.future_reg = None
        self.safety_order = None
        for o in eligible_orders(self.state):
            if isinstance(o, RegularOrder):
                regular_orders_by_key[OrderKey(o.item.id, o.week_idx)] = o
                if o.item.id == 'U_LOW':
                    self.u_low_reg = o
                elif o.item.id == 'U_HIGH':
                    self.u_high_reg = o
                elif o.item.id == 'FUTURE':
                    self.future_reg = o
            elif isinstance(o, SafetyOrder) and o.item.id == 'SAFETY':
                self.safety_order = o

        # earliest_dp_excluding: the predicted fill of a deferred order is
        # this plus one week, so six days before the week-1 due date puts
        # both urgent regulars exactly one day late (lateness_factor(1) =
        # 1). Week 3 (FUTURE) is never higher-priority than a tested move.
        other_dp = self.u_low_reg.due_date - timedelta(days=6)
        self.ctx = ScoringContext(
            priorities=priorities,
            regular_orders_by_key=regular_orders_by_key,
            earliest_dp_excluding={'M1': other_dp, 'M2': other_dp},
            earliest_dp_time=other_dp,
            new_machine_avail={},
        )
        self.costing = Costing(_weights(priority=1.0))

    def _move(self, item, week_idx):
        """Tiny `Move` helper — only `machine_id`, `item`, and
        `week_idx` matter to the priority cost; `plan=[]` keeps the
        per-item demand contribution at its current-view value (which
        is multiplied by 0 weights anyway)."""
        return Move(
            machine_id='M1', item=item, lbs=0.0,
            start_at='schedule_tail', idle_for=timedelta(0),
            plan=_plan(), week_idx=week_idx,
        )

    def test_setup_priority_ordering(self):
        # Pre-flight: confirm the four-item state sorts into the rank
        # order the rest of section 1.2.7 relies on.
        self.assertEqual(self.ctx.priorities[OrderKey('U_LOW', 1)], 1)
        self.assertEqual(self.ctx.priorities[OrderKey('U_HIGH', 1)], 2)
        self.assertEqual(self.ctx.priorities[OrderKey('SAFETY', None)], 3)
        self.assertEqual(self.ctx.priorities[OrderKey('FUTURE', 3)], 4)

    def test_highest_ranked_move_pays_no_priority_cost(self):
        # 1.2.7.1: move targets U_LOW.reg (rank 1). No higher-priority
        # order exists → priority cost is 0.
        move = self._move(self.u_low_reg.item, self.u_low_reg.week_idx)
        self.assertEqual(self.costing._priority_cost(move, self.ctx), 0.0)

    def test_same_urgency_less_depleted_pays_for_more_depleted(self):
        # 1.2.7.2: move targets U_HIGH.reg (rank 2). Only U_LOW.reg is
        # higher-priority; it is predicted one day late → factor 1, and its
        # whole week is unmet (100 of 100) → share 1.0.
        # Expected: w × (100 / 100) × lateness_factor(1) = 1.0.
        move = self._move(self.u_high_reg.item, self.u_high_reg.week_idx)
        self.assertAlmostEqual(
            self.costing._priority_cost(move, self.ctx),
            self.u_low_reg.lbs / self.u_low_reg.gross_lbs * 1.0,
        )

    def test_safety_move_pays_for_both_urgent_regulars(self):
        # 1.2.7.3: move targets SAFETY.safety (rank 3). U_LOW.reg and
        # U_HIGH.reg are higher-priority, each one day late with its whole
        # week unmet. Expected: w × (1.0 + 1.0) × lateness_factor(1) = 2.0.
        # week_idx=None marks a safety move.
        move = self._move(self.safety_order.item, week_idx=None)
        expected = (self.u_low_reg.lbs / self.u_low_reg.gross_lbs
                    + self.u_high_reg.lbs / self.u_high_reg.gross_lbs)
        self.assertAlmostEqual(
            self.costing._priority_cost(move, self.ctx), expected,
        )

    def test_future_move_pays_same_as_safety_move(self):
        # 1.2.7.4: move targets FUTURE.reg (rank 4). Higher-priority
        # entries are U_LOW.reg, U_HIGH.reg, and SAFETY.safety; the
        # safety order is filtered out by the regulars-only scope, so
        # priority cost matches scenario 3.
        move = self._move(self.future_reg.item, self.future_reg.week_idx)
        expected = (self.u_low_reg.lbs / self.u_low_reg.gross_lbs
                    + self.u_high_reg.lbs / self.u_high_reg.gross_lbs)
        self.assertAlmostEqual(
            self.costing._priority_cost(move, self.ctx), expected,
        )


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
        Compares types, items (by identity), week metadata and gross lbs
        for RegularOrders, `order_id`, and `lbs` within float tolerance."""
        self.assertEqual(len(actual), len(expected))
        for a, e in zip(actual, expected):
            self.assertIs(type(a), type(e))
            self.assertIs(a.item, e.item)
            self.assertAlmostEqual(a.lbs, e.lbs, places=places)
            self.assertEqual(a.order_id, e.order_id)
            if isinstance(a, RegularOrder):
                self.assertEqual(a.week_idx, e.week_idx)
                self.assertEqual(a.due_date, e.due_date)
                self.assertAlmostEqual(a.gross_lbs, e.gross_lbs, places=places)

    # ===================================================================
    # 1.3.1 eligible_decision_points
    # ===================================================================

    def test_eligible_dps_empty_state(self):
        state = _make_state(machines={}, rls_items={})
        self.assertEqual(eligible_decision_points(state), [])

    def test_eligible_dps_all_out_of_window(self):
        # schedule_tail == start_date == _START on a fresh machine; setting
        # window_end before _START leaves every DP out of window.
        machine = _make_machine('M1')
        state = _make_state(
            machines={'M1': machine}, rls_items={},
            window_end=_START - timedelta(hours=1),
        )
        self.assertEqual(eligible_decision_points(state), [])

    def test_eligible_dps_both_in_window_distinct(self):
        # Default beams (top=2800, btm=1800, top_pct=btm_pct=0.5,
        # rate=100): btm limits at 35 whole rolls, each 4/3h (knit +
        # doff), so next_runout ≈ _START + 46h40m. With window_end at
        # next_runout both DPs are in window and distinct.
        machine = _make_machine('M1')
        runout = machine.next_runout
        state = _make_state(
            machines={'M1': machine}, rls_items={},
            window_end=runout,
        )
        self.assertEqual(set(eligible_decision_points(state)), {
            DecisionPoint('M1', 'schedule_tail', _START),
            DecisionPoint('M1', 'next_runout', runout),
        })

    def test_eligible_dps_both_in_window_coinciding(self):
        # Empty beams → next_runout coincides with schedule_tail.
        machine = _make_machine(
            'M1', init_top_lbs=0.0, init_btm_lbs=0.0,
        )
        state = _make_state(
            machines={'M1': machine}, rls_items={},
            window_end=_START + timedelta(hours=24),
        )
        # Only the schedule_tail entry is emitted; the coincident
        # next_runout is deduplicated.
        self.assertEqual(eligible_decision_points(state), [
            DecisionPoint('M1', 'schedule_tail', _START),
        ])

    def test_eligible_dps_only_schedule_tail_in_window(self):
        # Default beams; window covers schedule_tail (= _START) but ends
        # well before next_runout (≈ _START + 46h40m).
        machine = _make_machine('M1')
        state = _make_state(
            machines={'M1': machine}, rls_items={},
            window_end=_START + timedelta(hours=10),
        )
        self.assertEqual(eligible_decision_points(state), [
            DecisionPoint('M1', 'schedule_tail', _START),
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
            DecisionPoint('M1', 'schedule_tail', _START),
            DecisionPoint('M1', 'next_runout', runout),
            DecisionPoint('M2', 'schedule_tail', _START),
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
            DecisionPoint('M1', 'schedule_tail', _START),
            DecisionPoint('M2', 'schedule_tail', _START),
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
            DecisionPoint('M1', 'schedule_tail', _START),
            DecisionPoint('M1', 'next_runout', m1.next_runout),
        })

    def test_eligible_dps_multi_subset_only_job_ends(self):
        # All machines in window for schedule_tail only. M3 runs the
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
            DecisionPoint('M1', 'schedule_tail', _START),
            DecisionPoint('M2', 'schedule_tail', _START),
            DecisionPoint('M3', 'schedule_tail',
                          _START + timedelta(hours=24)),
        })

    def test_eligible_dps_multi_mix_of_dps(self):
        # M1: both DPs in window. Default beams (btm limits): usable
        # (1800-5)/0.5=3590 -> floor(3590/100)=35 whole rolls, each 4/3h
        # (knit + doff), so next_runout ≈ _START + 46h40m. window_end is
        # set there so M1's next_runout just lands in window.
        # M2: only schedule_tail in window — huge beams push next_runout
        # far past window_end.
        # M3: out of window entirely (starts at +48h, past window_end).
        m1 = _make_machine('M1')
        m2 = _make_machine('M2', init_top_lbs=1e6, init_btm_lbs=1e6)
        m3 = _make_machine(
            'M3', init_item=_TC,
            start=_START + timedelta(hours=48),
        )
        runout = m1.next_runout
        state = _make_state(
            machines={'M1': m1, 'M2': m2, 'M3': m3}, rls_items={},
            window_end=runout,
        )
        self.assertEqual(set(eligible_decision_points(state)), {
            DecisionPoint('M1', 'schedule_tail', _START),
            DecisionPoint('M1', 'next_runout', runout),
            DecisionPoint('M2', 'schedule_tail', _START),
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
            _job_rec(_ITEM_A, lbs=900.0, completion_time=_START),
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
        def expected(gross):
            return [RegularOrder(item=item, week_idx=0, due_date=_START,
                                 lbs=100.0, gross_lbs=gross,
                                 order_id=f'P0@{item.id}')]

        # (a) week 0 has the unmet 100 lbs directly via the constructor.
        rls_a = RlsItem(
            item=item, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 0.0, 0.0, 0.0],
        )
        state_a = _make_state(machines={}, rls_items={item.id: rls_a})
        self._assert_orders_match(eligible_orders(state_a), expected(100.0))

        # (b) week 0 demand=300; a 200-lb job at week-0 due leaves 100
        # unmet (gross stays the full 300).
        rls_b = RlsItem(
            item=item, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[300.0, 0.0, 0.0, 0.0],
        )
        rls_b.register_jobs([
            _job_rec(item, lbs=200.0, completion_time=_START),
        ])
        state_b = _make_state(machines={}, rls_items={item.id: rls_b})
        self._assert_orders_match(eligible_orders(state_b), expected(300.0))

    def test_eligible_orders_safety_below_target_only(self):
        expected = [SafetyOrder(item=_ITEM_A, lbs=500.0,
                                order_id=f'S@{_ITEM_A.id}')]

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
            _job_rec(_ITEM_A, lbs=400.0, completion_time=late_t),
        ])
        state_b = _make_state(machines={}, rls_items={'AU0001': rls_b})
        self._assert_orders_match(eligible_orders(state_b), expected)

    def test_eligible_orders_urgent_regular_suppresses_safety(self):
        # At most one order per item: an item with BOTH an urgent unmet order
        # (week_idx <= reference_week) AND a safety shortfall yields only the
        # urgent RegularOrder — the urgent regular takes precedence over safety.
        expected = [
            RegularOrder(item=_ITEM_A, week_idx=0,
                         due_date=_START, lbs=100.0, gross_lbs=100.0,
                         order_id=f'P0@{_ITEM_A.id}'),
        ]

        # (a) weekly=[100, 0, 0, 0], no on_hand → week 0 fully unmet and
        # safety at 0 (target 500); the safety order is suppressed.
        rls_a = RlsItem(
            item=_ITEM_A, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 0.0, 0.0, 0.0],
        )
        state_a = _make_state(machines={}, rls_items={'AU0001': rls_a})
        self._assert_orders_match(eligible_orders(state_a), expected)

        # (b) weekly=[100]*4, no jobs → every week unmet; only the earliest
        # (week 0, urgent under the default reference_week) surfaces, and the
        # safety order stays suppressed.
        rls_b = RlsItem(
            item=_ITEM_A, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[100.0, 100.0, 100.0, 100.0],
        )
        state_b = _make_state(machines={}, rls_items={'AU0001': rls_b})
        self._assert_orders_match(eligible_orders(state_b), expected)

    def test_eligible_orders_future_regular_when_safety_met(self):
        # Unmet demand only PAST the reference week (default 1), safety at
        # target (_T1 has safety=0): the item still gets a RegularOrder for the
        # earliest unmet week — the "future regular" bucket.
        rls = RlsItem(
            item=_T1, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[0.0, 0.0, 100.0, 0.0],
        )
        state = _make_state(machines={}, rls_items={_T1.id: rls})
        self._assert_orders_match(eligible_orders(state), [
            RegularOrder(item=_T1, week_idx=2,
                         due_date=_START + timedelta(weeks=2), lbs=100.0,
                         gross_lbs=100.0, order_id=f'P2@{_T1.id}'),
        ])

    def test_eligible_orders_safety_precedes_future_regular(self):
        # No urgent order (unmet only past the reference week) AND safety below
        # target → the SafetyOrder wins; the future regular is suppressed.
        rls = RlsItem(
            item=_ITEM_A, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[0.0, 0.0, 100.0, 0.0],
        )
        state = _make_state(machines={}, rls_items={'AU0001': rls})
        self._assert_orders_match(eligible_orders(state), [
            SafetyOrder(item=_ITEM_A, lbs=500.0, order_id=f'S@{_ITEM_A.id}'),
        ])

    def test_eligible_orders_reference_week_promotes_regular_over_safety(self):
        # Same item/state as the safety-precedence case, but raising the
        # reference week to include week 2 makes that regular *urgent*, so it
        # now suppresses the safety order.
        rls = RlsItem(
            item=_ITEM_A, start_date=_START, on_hand_lbs=0.0,
            lead_time=timedelta(0),
            weekly_lbs_needed=[0.0, 0.0, 100.0, 0.0],
        )
        state = _make_state(
            machines={}, rls_items={'AU0001': rls}, reference_week_idx=2,
        )
        self._assert_orders_match(eligible_orders(state), [
            RegularOrder(item=_ITEM_A, week_idx=2,
                         due_date=_START + timedelta(weeks=2), lbs=100.0,
                         gross_lbs=100.0, order_id=f'P2@{_ITEM_A.id}'),
        ])

    def test_eligible_orders_earliest_unmet_selection(self):
        item = Greige(
            'AU_S0', family='A', tgt_wt=100.0,
            top_beam='40D BLACK 1000X4', top_pct=0.5,
            btm_beam='60D WHITE 1000X4', btm_pct=0.5,
            safety=0.0, machines={'M1': 100.0},
        )
        # gross_lbs is the week's demand as loaded (200); on-hand or a job
        # nets it to the 100 unmet lbs.
        expected = [
            RegularOrder(item=item, week_idx=0,
                         due_date=_START, lbs=100.0, gross_lbs=200.0,
                         order_id=f'P0@{item.id}'),
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
            _job_rec(item, lbs=100.0, completion_time=_START),
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
                         due_date=_START, lbs=100.0, gross_lbs=100.0,
                         order_id=f'P0@{safety0.id}'),
            SafetyOrder(item=_ITEM_B, lbs=300.0,
                        order_id=f'S@{_ITEM_B.id}'),
        ])

    # ===================================================================
    # 1.3.3.1 enumerate_candidates filtering and idling correctness
    # ===================================================================

    def test_enumerate_candidates_trivial(self):
        # Two items in the same family; one machine programmed for each
        # at the start state. Orders are small and target week 0, so no
        # carrying-avoidance idle. Items run on both machines, so each
        # item gets a candidate per machine; we assert the
        # programmed-machine candidate has one Knit activity + one Job record.
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
            window_end=_START,  # only schedule_tail DPs in window
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
            # One whole roll: a Knit + its Doff, and one Job record for
            # the item (no run-up, no preamble).
            self.assertEqual(
                [type(a).__name__ for a in mv.plan.activities],
                ['Knit', 'Doff'],
            )
            self.assertEqual(mv.plan.activities[0].item, item)
            self.assertEqual(len(mv.plan.jobs), 1)
            self.assertEqual(mv.plan.jobs[0].item, item)
            self.assertEqual(mv.idle_for, timedelta(0))

        # No move anywhere idles.
        for mv in moves:
            self.assertEqual(mv.idle_for, timedelta(0))
            self.assertFalse(any(isinstance(a, Idle) for a in mv.plan.activities))

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
        self.assertIsInstance(mv.plan.activities[0], Idle)
        self.assertEqual(
            mv.plan.activities[0].end - mv.plan.activities[0].start, mv.idle_for,
        )

    # ===================================================================
    # 1.3.3.2 enumerate_candidates lbs cap (move.lbs reflects
    # producible_lbs_in_week)
    # ===================================================================

    def test_enumerate_candidates_cap_mid_week_tail(self):
        # Machine running _T1 starts mid-Monday of ISO week 21 (Mon
        # 12:00). Beams of 1e6 each preclude any in-stream reloads, so
        # the producible cap is the 156-hour window divided by the
        # per-roll cost (knit + doff = 100/100 + 1/3 = 4/3h):
        # floor(156 / (4/3)) = 117 rolls × 100 = 11700 lbs.
        start = _START + timedelta(hours=12)
        machine = Machine(
            'M1', _T1, start,
            _TOP_BEAM, 1e6, _BTM_BEAM, 1e6,
            _24_7,
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
        self.assertEqual(moves[0].lbs, 11700.0)

    def test_enumerate_candidates_cap_full_changeover(self):
        # Machine starts at week_start running _TD (family B, 30D/90D)
        # with 1e6-each beams. Order is for _T1 (family A, 40D/60D) —
        # both yarns differ and families differ, so the preamble is the
        # canonical full changeover (legacy cross-family):
        #   TapeOut('both')=3h + 'both' re-thread (Hanging 1.5h +
        #   Threading 3.5h) + PatternChange=1.5h = 9.5h.
        # After the preamble, beams are reset to plant-standard fresh
        # lbs (2800 top low-denier, 1800 btm high-denier), so the
        # production loop will hit in-stream reloads. We assert
        # move.lbs equals the actual producible cap, and bound that cap
        # against the spec's ideal-formula upper bound (which assumes
        # no in-stream reloads).
        machine = Machine(
            'M1', _TD, _START,
            BeamSet.new(BeamSetDesc('30D RED 1000X4'), 1e6, _FIXTURE_DATE), 1e6,
            BeamSet.new(BeamSetDesc('90D GREEN 1000X4'), 1e6, _FIXTURE_DATE), 1e6,
            _24_7,
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
        # Ideal-formula upper bound: (week - preamble) × rate, ignoring
        # both the per-roll doff and in-stream reloads (so the real cap
        # sits below it). preamble = 9.5h → (168 - 9.5) × 100 = 15850.
        ideal_upper = (168 - 9.5) * 100
        self.assertGreater(mv.lbs, 0)
        self.assertLessEqual(mv.lbs, ideal_upper)
        # Preamble shape sanity: TapeOut('both'), a 'both' re-thread, and
        # a PatternChange — all present, in order, before the first Knit.
        kinds = [type(a).__name__ for a in mv.plan.activities]
        first_job = kinds.index('Knit')
        preamble = mv.plan.activities[:first_job]
        self.assertEqual(
            [type(a).__name__ for a in preamble],
            ['TapeOut', 'Hanging', 'Threading', 'PatternChange'],
        )
        self.assertEqual(preamble[0].bars, 'both')
        self.assertIsInstance(preamble[-1], PatternChange)

    def test_enumerate_candidates_cap_carrying_avoidance_idle(self):
        # Order for week 2 (due _START + 14d) forces carrying-avoidance
        # idle to (_START + 14d - 24h margin) = _START + 13d. The
        # effective start lands in ISO week 22 (May 25 - Jun 1) with
        # only 24 work-hours remaining before week_end — under the
        # three-day rule, so the cap window runs through the end of ISO
        # week 23 as well: 24 + 168 = 192 work hours. Item matches the
        # machine's current item and beams are huge → no preamble and no
        # in-stream reloads, so the cap is that window over the per-roll
        # cost: floor(192 / (4/3)) = 144 rolls × 100 = 14400 lbs.
        machine = Machine(
            'M1', _T1, _START,
            _TOP_BEAM, 1e6, _BTM_BEAM, 1e6,
            _24_7,
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
        self.assertEqual(mv.lbs, 14400.0)
        self.assertEqual(mv.idle_for, timedelta(hours=312))
        # Plan: a single Idle of 312h, then directly into production (no
        # preamble since current item matches) — Knit/Doff pairs whose
        # lbs total the cap, recorded on one Job of _T1.
        self.assertIsInstance(mv.plan.activities[0], Idle)
        self.assertEqual(mv.plan.activities[0].end - mv.plan.activities[0].start, mv.idle_for)
        knits = [a for a in mv.plan.activities if isinstance(a, Knit)]
        self.assertTrue(all(k.item is _T1 for k in knits))
        self.assertEqual(sum(k.lbs for k in knits), 14400.0)
        self.assertEqual(len(mv.plan.jobs), 1)
        self.assertEqual(mv.plan.jobs[0].item, _T1)
        self.assertEqual(mv.plan.jobs[0].total_lbs, 14400.0)

    def test_enumerate_candidates_cap_next_runout_dp(self):
        # Partial beams (top=600, btm=1000 with top_pct=btm_pct=0.5,
        # rate=100): top limits at floor((600-5)/0.5/100)=11 whole rolls,
        # so next_runout falls ~14.7h (11 × 4/3h) into ISO week 21. Order
        # is for _T2 (same yarn, same family as _T1), so the
        # cap-simulation preamble is a single RunnerChange (legacy
        # same-family).
        #
        # The cap simulation idles from as_of to next_runout (so the
        # beam state is unchanged from initial — top=600 partial,
        # btm=1000 partial), which forces in-stream reloads in the
        # post-changeover production loop. We bound the cap against a
        # loose ideal upper bound (no doff, no in-stream reloads) and
        # verify the move's plan structure.
        machine = Machine(
            'M1', _T1, _START,
            _TOP_BEAM, 600.0, _BTM_BEAM, 1000.0,
            _24_7,
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
        # Two DPs (schedule_tail + next_runout); we focus on the
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
        # Loose ideal upper bound: (week_hours - to_next_runout_hours -
        # changeover_hours) × rate, ignoring doff and reloads, so the
        # real cap sits below it. ~(168 - 14.7 - 0.75) × 100 < 15500.
        ideal_upper = 15500.0
        self.assertGreater(mv.lbs, 0)
        self.assertLessEqual(mv.lbs, ideal_upper)
        self.assertEqual(mv.lbs % _T2.tgt_wt, 0)

        # Plan structure: 'next_runout' mode emits a run-up Job of the
        # current item (_T1), then the preamble for _T2 (which here
        # includes a re-thread for the bar emptied during run-up since
        # the actual commit-side plan doesn't idle), a RunnerChange
        # (same family, legacy machine), and finally _T2 production Jobs.
        first_job = next(
            i for i, a in enumerate(mv.plan.activities) if isinstance(a, Knit)
        )
        self.assertEqual(mv.plan.activities[first_job].item, _T1)
        changeovers = [
            a for a in mv.plan.activities if isinstance(a, RunnerChange)
        ]
        self.assertEqual(len(changeovers), 1)
        # Same-family legacy transition uses RunnerChange, not Style/Pattern.
        self.assertFalse(any(isinstance(a, (StyleChange, PatternChange))
                             for a in mv.plan.activities))
        # No tape-outs anywhere in the plan.
        self.assertFalse(any(isinstance(a, TapeOut) for a in mv.plan.activities))

    def test_enumerate_candidates_cap_bumpup_to_next_week(self):
        # When fewer than three work days of the ISO week remain at
        # `effective_start`, the cap window runs through the end of the
        # *next* ISO week. The extreme case: a tail 30 minutes before the
        # week ends, where the week's remnant could not fit even one roll
        # (and without the extension `n_rolls = 0` would filter the
        # candidate out).
        #
        # Setup: machine starts Sunday 23:30 of ISO week 21. Beams are
        # huge so the extended window (Sun 23:30 of week 21 →
        # Mon 00:00 of week 23) is cap-bounded by hours alone: 7 days +
        # 30 min = 168.5h over the per-roll cost (4/3h) =
        # floor(168.5 / (4/3)) = 126 whole rolls × 100 = 12600 lbs.
        start = _START + timedelta(days=6, hours=23, minutes=30)
        machine = Machine(
            'M1', _T1, start,
            _TOP_BEAM, 1e6, _BTM_BEAM, 1e6,
            _24_7,
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
        self.assertEqual(moves[0].lbs, 12600.0)

    def test_enumerate_candidates_cap_three_day_rule(self):
        # The boundary of the three-day rule on the 24/7 calendar (72 work
        # hours). A tail at Friday 00:00 leaves exactly 72h: not fewer than
        # three days, so the cap stays in the current week —
        # floor(72 / (4/3)) = 54 rolls = 5400 lbs. One hour later leaves
        # 71h, under the rule, and the window runs through next week:
        # floor((71 + 168) / (4/3)) = 179 rolls = 17900 lbs.
        for offset, expected in ((timedelta(days=4), 5400.0),
                                 (timedelta(days=4, hours=1), 17900.0)):
            start = _START + offset
            machine = Machine('M1', _T1, start, _TOP_BEAM, 1e6, _BTM_BEAM, 1e6, _24_7)
            rls = RlsItem(item=_T1, start_date=_START, on_hand_lbs=0.0,
                          lead_time=timedelta(0),
                          weekly_lbs_needed=[1_000_000.0, 0.0, 0.0, 0.0])
            state = _make_state(machines={'M1': machine}, rls_items={_T1.id: rls},
                                window_end=start)
            moves = enumerate_candidates(state)
            self.assertEqual(len(moves), 1)
            self.assertEqual(moves[0].lbs, expected, f'tail at {start}')

    # --- 1.3.3.3 next_runout skipped for the machine's current item -------

    def test_enumerate_candidates_skips_same_item_next_runout(self):
        # Separate setup from the filtering/cap tests: M1 is mid-run on _T1
        # with partial beams (top=600, btm=1000, top_pct=btm_pct=0.5) so its
        # next_runout is in-window and distinct from schedule_tail. _T1 (the
        # current item) has unmet demand, and so does _T2 (a different item M1
        # can run). The (next_runout, _T1) pairing must be skipped --
        # plan_production rejects a same-item next_runout -- while
        # (schedule_tail, _T1) and (next_runout, _T2) remain.
        machine = Machine(
            'M1', _T1, _START,
            _TOP_BEAM, 600.0, _BTM_BEAM, 1000.0,
            _24_7,
        )
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
            machines={'M1': machine},
            rls_items={_T1.id: rls_t1, _T2.id: rls_t2},
            window_end=machine.next_runout,   # both DPs in window
        )
        moves = enumerate_candidates(state)   # must not raise

        # 1. No same-item next_runout candidate.
        self.assertFalse(any(
            mv.start_at == 'next_runout' and mv.item.id == _T1.id
            for mv in moves
        ))
        # 2. The schedule_tail candidate for the current item is present.
        self.assertTrue(any(
            mv.start_at == 'schedule_tail' and mv.item.id == _T1.id
            for mv in moves
        ))
        # 3. A next_runout candidate for the *other* item is present — the skip
        #    is specific to the current item, not a blanket next_runout drop.
        self.assertTrue(any(
            mv.start_at == 'next_runout' and mv.item.id == _T2.id
            for mv in moves
        ))


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
        total_scheduled = sum(j.total_lbs for j in rls.jobs)
        self.assertGreaterEqual(total_scheduled, 400.0)

    def test_plan_single_item_multiple_machines(self):
        # Two identical eligible machines; the window mechanism spreads
        # work across both as each machine's schedule_tail falls out of
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
            eoq_threshold_rolls=0,          # a lone item is a unique setup: no batching here
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
                if isinstance(a, Knit):
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
        scheduled = sum(j.total_lbs for j in state.rls_items[_T1.id].jobs)
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
            eoq_threshold_rolls=0,          # a lone item is a unique setup: no batching here
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
        # M1.schedule_tail pushes past window_end, forcing
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
            item=_T1, start_date=_START, on_hand_lbs=150.0,
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
            runner_change=1, pattern_change=1, idle_time=0.1,
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

        # 6. rls_items are the same objects state holds, and each carries
        # its on_hand_coverage (the initial jobs=[] allocation, captured at
        # construction). Re-derive the expected coverage from a fresh
        # RlsItem built with the same inputs — its views prime with
        # jobs=[] + on_hand at __init__, so this exercises the real code
        # path rather than re-implementing the bucket walk.
        self.assertEqual(set(report.rls_items), set(state.rls_items))
        for item_id, rls in state.rls_items.items():
            self.assertIs(report.rls_items[item_id], rls)
            fresh = RlsItem(
                item=rls.item, start_date=rls.start_date,
                on_hand_lbs=rls.on_hand_lbs, lead_time=rls.lead_time,
                weekly_lbs_needed=[w.qty_lbs for w in rls.weekly_demand],
            )
            expected = {
                o.id: o.allocated_lbs for o in fresh.safety_view.orders
            }
            expected[fresh.safety_view.safety.id] = (
                fresh.safety_view.safety_pool
            )
            self.assertEqual(
                report.rls_items[item_id].on_hand_coverage, expected,
            )
        # The positive-on_hand item (_T1) has non-trivial coverage.
        self.assertGreater(
            sum(report.rls_items[_T1.id].on_hand_coverage.values()), 0.0,
        )


# --- 1.1.6 State.capacity and booking -------------------------------------

from datetime import date as _date
from swmtplanner.schedule import ChangeoverCapacity, DEFAULT_RESOURCES

# The per-kind rations alone; the plant-wide change cap is covered by the
# tests that name it.
_PER_KIND = {k: DEFAULT_RESOURCES[k] for k in ('tape_out', 'pattern_change')}
from swmtplanner.planners.infinite.report import (
    changeovers_dataframe, _activity_desc,
)
from swmtplanner.planners.infinite import schedule_json as _sj


class StateCapacityTests(unittest.TestCase):

    def test_default_is_unrationed(self):
        state = _make_state()
        self.assertIsInstance(state.capacity, ChangeoverCapacity)
        self.assertIsNone(state.capacity.limits('tape_out'))
        self.assertIsNone(state.capacity.limits('pattern_change'))
        self.assertEqual(state.capacity.bookings(), {})

    def test_commit_books_the_plan_slots(self):
        cap = ChangeoverCapacity(_24_7, DEFAULT_RESOURCES)
        state = _make_state(capacity=cap)
        day = _START.date()
        plan = ProductionPlan(
            activities=(), jobs=(),
            capacity_taken=(('tape_out', day, 2, _START + timedelta(hours=8)),
                            ('pattern_change', day, 1, _START + timedelta(hours=9))),
        )
        state.commit_move(Move(machine_id='M1', item=_ITEM_A, lbs=0.0,
                               start_at='schedule_tail', idle_for=timedelta(0),
                               plan=plan))
        self.assertEqual(cap.booked('tape_out', day), 2)
        self.assertEqual(cap.booked('pattern_change', day), 1)
        state.commit_move(_move_with_plan())          # no slots: nothing more
        self.assertEqual(cap.bookings(), {('tape_out', day): 2,
                                          ('pattern_change', day): 1})

    def test_candidates_see_the_bookings(self):
        # M1 runs _TD (family B, its own yarn on both bars). A _T1 candidate
        # needs a both-bar tape-out; a _TD continuation needs no changeover.
        # With the day's tape-out units booked, only the changeover waits.
        cap = ChangeoverCapacity(_24_7, _PER_KIND)
        cap.book('tape_out', _START.date(), 2)
        # M1's bars must actually carry _TD's yarn (the module fixture sets
        # are _T1's), or the preamble keeps them and only pattern-changes.
        m1 = Machine(
            'M1', _TD, _START,
            BeamSet.new(BeamSetDesc('30D RED 1000X4'), 2800.0, _FIXTURE_DATE), 2800.0,
            BeamSet.new(BeamSetDesc('90D GREEN 1000X4'), 1800.0, _FIXTURE_DATE), 1800.0,
            _24_7,
        )
        rls_t1 = RlsItem(item=_T1, start_date=_START, on_hand_lbs=0.0,
                         lead_time=timedelta(0),
                         weekly_lbs_needed=[100.0, 0.0, 0.0, 0.0])
        rls_td = RlsItem(item=_TD, start_date=_START, on_hand_lbs=0.0,
                         lead_time=timedelta(0),
                         weekly_lbs_needed=[100.0, 0.0, 0.0, 0.0])
        state = _make_state(machines={'M1': m1},
                            rls_items={_T1.id: rls_t1, _TD.id: rls_td},
                            window_end=_START, capacity=cap)
        moves = enumerate_candidates(state)
        change = next(mv for mv in moves if mv.item.id == _T1.id)
        cont = next(mv for mv in moves if mv.item.id == _TD.id)
        waits = [a for a in change.plan.activities if isinstance(a, Idle) and a.reason]
        self.assertEqual(len(waits), 1)
        self.assertEqual(waits[0].reason, 'tape_out slot')
        tape = next(a for a in change.plan.activities if isinstance(a, TapeOut))
        self.assertEqual(tape.start, waits[0].end)
        self.assertEqual(tape.start, _START + timedelta(days=1, hours=8))
        self.assertEqual(change.plan.capacity_taken[0][:3],
                         ('tape_out', (_START + timedelta(days=1)).date(), 2))
        self.assertFalse(any(isinstance(a, Idle) for a in cont.plan.activities))
        self.assertEqual(cont.plan.capacity_taken, ())
        self.assertEqual(cap.bookings(), {('tape_out', _START.date()): 2})


# --- 1.5 Changeover report -------------------------------------------------

def _report(schedules, capacity):
    return PlanReport(
        schedules=schedules, jobs_by_item={}, jobs_by_machine={},
        total_score=0.0, cost_components_by_item={},
        unmet_lbs_by_item_week={}, late_orders=(), rls_items={},
        capacity=capacity,
    )


class ChangeoverReportTests(unittest.TestCase):

    def setUp(self):
        self.cap = ChangeoverCapacity(_24_7, _PER_KIND)
        self.t0 = _START + timedelta(hours=9)             # Mon 09:00
        self.tape_both = TapeOut(start=self.t0, end=self.t0 + timedelta(hours=3), bars='both')
        self.tape_top = TapeOut(start=self.t0 + timedelta(days=1), end=self.t0 + timedelta(days=1, hours=2), bars='top')
        self.pattern = PatternChange(start=self.t0 + timedelta(hours=4),
                                     end=self.t0 + timedelta(hours=5.5),
                                     from_item=_ITEM_A, to_item=_ITEM_B)
        self.wait = Idle(start=_START, end=_START + timedelta(hours=8), reason='tape_out slot')
        self.plain = Idle(start=_START, end=_START + timedelta(hours=1))

    def test_no_ration_is_empty(self):
        df = changeovers_dataframe(_report({'M1': (self.tape_both,)}, None))
        self.assertTrue(df.empty)
        self.assertIn('used', df.columns)
        df = changeovers_dataframe(_report({'M1': (self.tape_both,)},
                                           ChangeoverCapacity(None, {})))
        self.assertTrue(df.empty)

    def test_period_rows(self):
        df = changeovers_dataframe(_report(
            {'M1': (self.tape_both, self.pattern), 'M2': (self.tape_top,)}, self.cap))
        periods = df[df.row == 'period'].reset_index(drop=True)
        self.assertEqual(list(periods.resource), ['pattern_change', 'tape_out', 'tape_out'])
        self.assertEqual(list(periods.day), [_START.date(), _START.date(),
                                             (_START + timedelta(days=1)).date()])
        self.assertEqual(list(periods.capacity), [3, 2, 2])
        self.assertEqual(list(periods.used), [1, 2, 1])
        self.assertEqual(periods.activities[1], f'M1:{self.tape_both.id}@09:00')
        self.assertEqual(periods.period_start[1], _START + timedelta(hours=8))
        self.assertEqual(periods.period_end[1], _START + timedelta(hours=24))

    def test_wait_rows(self):
        df = changeovers_dataframe(_report(
            {'M1': (self.plain, self.wait, self.tape_both)}, self.cap))
        waits = df[df.row == 'wait'].reset_index(drop=True)
        self.assertEqual(len(waits), 1)
        self.assertEqual((waits.resource[0], waits.machine[0], waits.start[0], waits.end[0]),
                         ('tape_out', 'M1', _START, _START + timedelta(hours=8)))

    def test_schedule_json_reason(self):
        out = _sj._activity(self.wait, _sj.PLANT_TZ)
        self.assertEqual(out['reason'], 'tape_out slot')
        self.assertNotIn('reason', _sj._activity(self.plain, _sj.PLANT_TZ))

    def test_schedule_sheet_desc(self):
        self.assertEqual(_activity_desc(self.wait), 'waiting for tape_out slot')
        self.assertEqual(_activity_desc(self.plain), '')


# --- 1.2.8 Recovery cost ---------------------------------------------------

import importlib as _importlib
from swmtplanner.demand.view import lateness_factor
from swmtplanner.schedule import (
    effective_rate, TAPE_OUT_BOTH_DURATION, PATTERN_CHANGE_DURATION,
)
from swmtplanner.planners.infinite.coordination import (
    build_cheap_sets, build_urgent_by_item, cheap_set_after,
)

# Yarn Y (40D BLACK / 60D WHITE) carries two pattern families; yarn U
# (30D RED / 90D GREEN) is unique to one item. Every item runs on every
# machine of this section at a nominal 100 lbs/h, except where a test says.
_RM = {m: 100.0 for m in ('MA', 'MB', 'MC', 'MD', 'ME')}
_RY1 = Greige('RY1', family='A', tgt_wt=100.0,
              top_beam='40D BLACK 1000X4', top_pct=0.5,
              btm_beam='60D WHITE 1000X4', btm_pct=0.5, safety=0.0, machines=dict(_RM))
_RY2 = Greige('RY2', family='A', tgt_wt=100.0,
              top_beam='40D BLACK 1000X4', top_pct=0.5,
              btm_beam='60D WHITE 1000X4', btm_pct=0.5, safety=0.0,
              machines={m: 100.0 for m in ('MA', 'MC', 'MD', 'ME')})   # not MB
_RYC = Greige('RYC', family='C', tgt_wt=100.0,
              top_beam='40D BLACK 1000X4', top_pct=0.5,
              btm_beam='60D WHITE 1000X4', btm_pct=0.5, safety=0.0, machines=dict(_RM))
_RU = Greige('RU', family='A', tgt_wt=100.0,
             top_beam='30D RED 1000X4', top_pct=0.5,
             btm_beam='90D GREEN 1000X4', btm_pct=0.5, safety=0.0, machines=dict(_RM))

_Y_TOP = BeamSet.new(BeamSetDesc('40D BLACK 1000X4'), 1e6, _FIXTURE_DATE)
_Y_BTM = BeamSet.new(BeamSetDesc('60D WHITE 1000X4'), 1e6, _FIXTURE_DATE)
_U_TOP = BeamSet.new(BeamSetDesc('30D RED 1000X4'), 1e6, _FIXTURE_DATE)
_U_BTM = BeamSet.new(BeamSetDesc('90D GREEN 1000X4'), 1e6, _FIXTURE_DATE)


def _rmachine(mid, item, start=_START, is_new=False):
    """A machine mounted with `item`'s yarn (huge sets), running `item`."""
    if item is _RU:
        top, btm = _U_TOP, _U_BTM
    else:
        top, btm = _Y_TOP, _Y_BTM
    return Machine(mid, item, start, top, 1e6, btm, 1e6, _24_7, is_new=is_new)


def _rrls(item, weekly, on_hand=0.0):
    return RlsItem(item=item, start_date=_START, on_hand_lbs=on_hand,
                   lead_time=timedelta(0), weekly_lbs_needed=weekly)


def _rmove(mid, item):
    return Move(machine_id=mid, item=item, lbs=0.0, start_at='schedule_tail',
                idle_for=timedelta(0), plan=_plan())


def _ctx_for(state):
    return ScoringContext(
        priorities={}, regular_orders_by_key={}, earliest_dp_excluding={},
        earliest_dp_time=_START, new_machine_avail={},
        cheap_sets=build_cheap_sets(state), urgent_by_item=build_urgent_by_item(state),
    )


def _rate(item, mid, is_new=False):
    return effective_rate(item.get_rate_on_mchn(mid), 'new' if is_new else 'old')


class RecoveryCostTests(unittest.TestCase):
    """Section 1.2.8 of INF_PLAN_TEST_SPEC.md."""

    def setUp(self):
        self.costing = Costing(_weights(recovery=1.0))
        self.cap = ChangeoverCapacity(_24_7, DEFAULT_RESOURCES)
        self.due0 = _START                      # week 0 due (a Monday)
        self.due1 = _START + timedelta(days=7)  # week 1 due

    # 1. cheap sets
    def test_cheap_sets(self):
        state = _make_state(
            machines={'MA': _rmachine('MA', _RY1, is_new=True),
                      'MB': _rmachine('MB', _RY1),
                      'MC': _rmachine('MC', _RYC),
                      'MD': _rmachine('MD', _RU)},
            rls_items={i.id: _rrls(i, [100.0, 0.0, 0.0, 0.0])
                       for i in (_RY1, _RY2, _RYC, _RU)},
            capacity=self.cap)
        cs = build_cheap_sets(state)
        self.assertEqual(cs['MA'], frozenset({'RY1', 'RY2', 'RYC'}))   # new: whole yarn
        self.assertEqual(cs['MB'], frozenset({'RY1'}))                 # old, family A; RY2 can't run on MB
        self.assertEqual(cs['MC'], frozenset({'RYC'}))                 # old, family C
        self.assertEqual(cs['MD'], frozenset({'RU'}))
        self.assertEqual(cheap_set_after(state, 'MB', _RU), frozenset({'RU'}))
        self.assertEqual(cheap_set_after(state, 'MA', _RU), frozenset({'RU'}))
        self.assertEqual(cheap_set_after(state, 'MD', _RYC), frozenset({'RYC'}))   # old → family C only
        self.assertEqual(cheap_set_after(state, 'MA', _RYC), frozenset({'RY1', 'RY2', 'RYC'}))
        # 10. a machine set up for an item it cannot run holds nothing cheaply
        state = _make_state(machines={'MB': _rmachine('MB', _RY2)},
                            rls_items={'RY2': _rrls(_RY2, [100.0, 0.0, 0.0, 0.0])},
                            capacity=self.cap)
        self.assertFalse(state.machines['MB'].can_run_current_item)
        self.assertEqual(build_cheap_sets(state)['MB'], frozenset())

    # 10. an item the machine cannot run
    def test_cannot_run_current_item(self):
        # MB is set up for RY2, which cannot run on it: leaving strands nothing.
        state = _make_state(
            machines={'MB': _rmachine('MB', _RY2), 'MC': _rmachine('MC', _RY1)},
            rls_items={'RY1': _rrls(_RY1, [0.0, 1000.0, 0.0, 0.0]),
                       'RU': _rrls(_RU, [1000.0, 0.0, 0.0, 0.0])},
            capacity=self.cap)
        self.assertEqual(self.costing.recovery_detail(state, _rmove('MB', _RU), _ctx_for(state)),
                         (0.0, []))
        self.assertEqual(self.costing.recovery_detail(state, _rmove('MB', _RYC), _ctx_for(state)),
                         (0.0, []))
        # ... and it does not cover for MA leaving yarn Y, where MB on RY1 would.
        def leaving(mb_item):
            st = _make_state(
                machines={'MA': _rmachine('MA', _RY1, is_new=True), 'MB': _rmachine('MB', mb_item)},
                rls_items={'RY1': _rrls(_RY1, [0.0, 1000.0, 0.0, 0.0]),
                           'RU': _rrls(_RU, [1000.0, 0.0, 0.0, 0.0])},
                capacity=self.cap)
            return self.costing.recovery_detail(st, _rmove('MA', _RU), _ctx_for(st))[0]
        self.assertEqual(leaving(_RY1), 0.0)
        self.assertGreater(leaving(_RY2), 0.0)

    # 2. urgent orders
    def test_urgent_by_item(self):
        state = _make_state(
            machines={'MA': _rmachine('MA', _RY1)},
            rls_items={'RY1': _rrls(_RY1, [300.0, 200.0, 100.0, 0.0], on_hand=100.0),
                       'RU': _rrls(_RU, [100.0, 0.0, 0.0, 0.0], on_hand=100.0)},
            capacity=self.cap)                    # reference_week_idx defaults to 1
        urgent = build_urgent_by_item(state)
        self.assertNotIn('RU', urgent)             # fully covered by on-hand
        orders = urgent['RY1']
        self.assertEqual([(o.week_idx, o.lbs, o.gross_lbs) for o in orders],
                         [(0, 200.0, 300.0), (1, 200.0, 200.0)])
        self.assertEqual(orders[0].due_date, self.due0)

    # 3. nothing lost
    def test_nothing_lost(self):
        state = _make_state(
            machines={'MA': _rmachine('MA', _RY1, is_new=True), 'MB': _rmachine('MB', _RY1)},
            rls_items={i.id: _rrls(i, [1000.0, 1000.0, 0.0, 0.0]) for i in (_RY1, _RY2, _RYC)},
            capacity=self.cap)
        ctx = _ctx_for(state)
        self.assertEqual(self.costing.recovery_detail(state, _rmove('MB', _RY1), ctx), (0.0, []))  # same item
        self.assertEqual(self.costing.recovery_detail(state, _rmove('MA', _RYC), ctx), (0.0, []))  # style change
        # MB (old, family A) can only cheaply make RY1 (RY2 can't run on it);
        # moving it to RYC loses RY1 — covered by MA below — so a runner
        # change case needs a machine that can run both: MC.
        state2 = _make_state(
            machines={'MC': _rmachine('MC', _RY1), 'MA': _rmachine('MA', _RY1, is_new=True)},
            rls_items={i.id: _rrls(i, [1000.0, 1000.0, 0.0, 0.0]) for i in (_RY1, _RY2)},
            capacity=self.cap)
        ctx2 = _ctx_for(state2)
        self.assertEqual(self.costing.recovery_detail(state2, _rmove('MC', _RY2), ctx2), (0.0, []))  # runner change

    # 4. covered elsewhere
    def test_covered_elsewhere(self):
        # MB leaves yarn Y for RU; MC (old, family A, idle from _START) can
        # make RY1's 1,000 lbs long before the week-1 due date.
        state = _make_state(
            machines={'MB': _rmachine('MB', _RY1), 'MC': _rmachine('MC', _RY1)},
            rls_items={'RY1': _rrls(_RY1, [0.0, 1000.0, 0.0, 0.0]),
                       'RU': _rrls(_RU, [1000.0, 0.0, 0.0, 0.0])},
            capacity=self.cap)
        ctx = _ctx_for(state)
        self.assertEqual(self.costing.recovery_detail(state, _rmove('MB', _RU), ctx), (0.0, []))

    # 5. last machine, tape-out route only
    def test_last_machine_tape_out_route(self):
        # MD is the only machine on yarn U. Leaving it for RY1 strands RU's
        # week-0 order (100 of 100 lbs, due _START). The other machines are
        # on yarn Y: MA new (tail _START), MB old family A (tail later) — all
        # tape routes. The earliest tail is MA's, a new machine, so the fill
        # is the next both-bar tape-out slot after _START (08:00, the window
        # opening) plus a week.
        state = _make_state(
            machines={'MD': _rmachine('MD', _RU),
                      'MA': _rmachine('MA', _RY1, is_new=True),
                      'MB': _rmachine('MB', _RY1, start=_START + timedelta(hours=5))},
            rls_items={'RU': _rrls(_RU, [100.0, 0.0, 0.0, 0.0]),
                       'RY1': _rrls(_RY1, [100.0, 0.0, 0.0, 0.0])},
            capacity=self.cap)
        ctx = _ctx_for(state)
        q, strands = self.costing.recovery_detail(state, _rmove('MD', _RY1), ctx)
        slot = self.cap.next_slot('tape_out', 2, _START, TAPE_OUT_BOTH_DURATION)
        self.assertEqual(slot, _START + timedelta(hours=8))
        fill = slot + timedelta(days=7)
        expected = 1.0 * lateness_factor((fill - self.due0) / timedelta(days=1))
        self.assertAlmostEqual(q, expected)
        self.assertEqual(strands, [('RU', q)])
        # The earliest-tail tape-route machine old and in another family:
        # a pattern slot follows the tape-out slot. Book the day's pattern
        # units and the fill moves to the next day.
        state2 = _make_state(
            machines={'MD': _rmachine('MD', _RU),
                      'MC': _rmachine('MC', _RYC)},
            rls_items={'RU': _rrls(_RU, [100.0, 0.0, 0.0, 0.0]),
                       'RYC': _rrls(_RYC, [100.0, 0.0, 0.0, 0.0])},
            capacity=self.cap)
        ctx2 = _ctx_for(state2)
        q_free, _ = self.costing.recovery_detail(state2, _rmove('MD', _RYC), ctx2)
        self.cap.book('pattern_change', _START.date(), 3)
        ctx3 = _ctx_for(state2)
        q_full, _ = self.costing.recovery_detail(state2, _rmove('MD', _RYC), ctx3)
        t = self.cap.next_slot('tape_out', 2, _START, TAPE_OUT_BOTH_DURATION)
        t = self.cap.next_slot('pattern_change', 1, t, PATTERN_CHANGE_DURATION)
        self.assertEqual(t, _START + timedelta(days=1, hours=8))
        self.assertAlmostEqual(
            q_full, lateness_factor((t + timedelta(days=7) - self.due0) / timedelta(days=1)))
        self.assertGreater(q_full, q_free)

    # 6. route weighting
    def test_route_weighting(self):
        # MB (old, family A) leaves yarn Y for RU, stranding RY1's week-1
        # order (100 lbs). MA is a new machine on Y but its tail is three
        # weeks out, so it covers nothing before the due date; MC and ME are
        # old machines on Y in family C. Routes: style 1 (fill = MA's tail,
        # past the horizon), pattern 2 (next pattern slot after the earliest
        # of MC/ME's tails).
        far = _START + timedelta(days=21)
        state = _make_state(
            machines={'MB': _rmachine('MB', _RY1),
                      'MA': _rmachine('MA', _RY1, start=far, is_new=True),
                      'MC': _rmachine('MC', _RYC, start=_START + timedelta(hours=10)),
                      'ME': _rmachine('ME', _RYC, start=_START + timedelta(hours=12))},
            rls_items={'RY1': _rrls(_RY1, [0.0, 100.0, 0.0, 0.0]),
                       'RU': _rrls(_RU, [100.0, 0.0, 0.0, 0.0]),
                       'RYC': _rrls(_RYC, [0.0, 0.0, 0.0, 0.0])},
            capacity=self.cap)
        ctx = _ctx_for(state)
        q, strands = self.costing.recovery_detail(state, _rmove('MB', _RU), ctx)
        week = timedelta(days=7)
        fill_style = max(far, self.due1) + week
        t_pat = self.cap.next_slot('pattern_change', 1, _START + timedelta(hours=10),
                                   PATTERN_CHANGE_DURATION)
        fill_pat = t_pat + week
        late = lambda fill: lateness_factor((fill - self.due1) / timedelta(days=1))
        expected = (1 / 3) * late(fill_style) + (2 / 3) * late(fill_pat)
        self.assertAlmostEqual(q, expected)
        self.assertEqual(strands, [('RY1', q)])
        # Booking the day's pattern slots pushes the pattern route's fill.
        self.cap.book('pattern_change', _START.date(), 3)
        q2, _ = self.costing.recovery_detail(state, _rmove('MB', _RU), _ctx_for(state))
        self.assertGreater(q2, q)

    # 7. partial coverage
    def test_partial_coverage(self):
        # MC (old, family A, 10 lbs/h nominal on RY1) is the only other cheap
        # machine. Its tail is 100 working hours before the week-0 due date,
        # enough for order 0 (1,000 lbs) exactly; by the week-1 due date it
        # has 168 h more → 1,680 lbs of order 1's 2,000: 320 uncovered.
        slow = Greige('RY1', family='A', tgt_wt=100.0,
                      top_beam='40D BLACK 1000X4', top_pct=0.5,
                      btm_beam='60D WHITE 1000X4', btm_pct=0.5, safety=0.0,
                      machines={'MB': 100.0, 'MC': 10.0 / effective_rate(1.0, 'old'), 'MA': 100.0})
        start_c = self.due0 - timedelta(hours=100)
        state = _make_state(
            machines={'MB': _rmachine('MB', slow),
                      'MC': _rmachine('MC', slow, start=start_c),
                      'MA': _rmachine('MA', _RU, is_new=True)},   # the recovery route
            rls_items={'RY1': _rrls(slow, [1000.0, 2000.0, 0.0, 0.0]),
                       'RU': _rrls(_RU, [100.0, 0.0, 0.0, 0.0])},
            start_date=start_c, capacity=self.cap)
        ctx = _ctx_for(state)
        q, strands = self.costing.recovery_detail(state, _rmove('MB', _RU), ctx)
        # Two recovery routes, one machine each: MC itself (a runner change,
        # already booked to the horizon, so its fill is the week-1 due date
        # plus a week) and MA (new, on yarn U — a tape route, filling a week
        # after the next both-bar slot). Only the 320 uncovered lbs of
        # order 1 are charged.
        share = 320.0 / 2000.0
        late = lambda fill: lateness_factor((fill - self.due1) / timedelta(days=1))
        week = timedelta(days=7)
        t = self.cap.next_slot('tape_out', 2, _START, TAPE_OUT_BOTH_DURATION)
        expected = 0.5 * share * late(self.due1 + week) + 0.5 * share * late(t + week)
        self.assertAlmostEqual(q, expected, places=6)
        self.assertEqual([i for i, _c in strands], ['RY1'])

    # 8. the walk is sequential
    def test_capacity_walk_is_sequential(self):
        # Same setup as 7. Counted independently, MC's 268 h × 10 lbs/h =
        # 2,680 lbs would cover order 1's 2,000 and the quantity would be 0;
        # sequentially order 0 consumes the first 1,000 and 320 are left.
        slow = Greige('RY1', family='A', tgt_wt=100.0,
                      top_beam='40D BLACK 1000X4', top_pct=0.5,
                      btm_beam='60D WHITE 1000X4', btm_pct=0.5, safety=0.0,
                      machines={'MB': 100.0, 'MC': 10.0 / effective_rate(1.0, 'old'), 'MA': 100.0})
        start_c = self.due0 - timedelta(hours=100)
        state = _make_state(
            machines={'MB': _rmachine('MB', slow),
                      'MC': _rmachine('MC', slow, start=start_c),
                      'MA': _rmachine('MA', _RU, is_new=True)},
            rls_items={'RY1': _rrls(slow, [1000.0, 2000.0, 0.0, 0.0]),
                       'RU': _rrls(_RU, [100.0, 0.0, 0.0, 0.0])},
            start_date=start_c, capacity=self.cap)
        q, _ = self.costing.recovery_detail(state, _rmove('MB', _RU), _ctx_for(state))
        self.assertGreater(q, 0.0)
        # and nothing at all when order 1 fits in what is left (1,680 lbs)
        state.rls_items['RY1'] = _rrls(slow, [1000.0, 1600.0, 0.0, 0.0])
        q2, _ = self.costing.recovery_detail(state, _rmove('MB', _RU), _ctx_for(state))
        self.assertEqual(q2, 0.0)

    # 9. memoised and reported
    def test_memoised_scored_and_logged(self):
        state = _make_state(
            machines={'MD': _rmachine('MD', _RU), 'MA': _rmachine('MA', _RY1, is_new=True)},
            rls_items={'RU': _rrls(_RU, [100.0, 0.0, 0.0, 0.0]),
                       'RY1': _rrls(_RY1, [100.0, 0.0, 0.0, 0.0])},
            capacity=self.cap)
        ctx = _ctx_for(state)
        a = self.costing.recovery_detail(state, _rmove('MD', _RY1), ctx)
        b = self.costing.recovery_detail(state, _rmove('MD', _RY1), ctx)
        self.assertIs(a, b)
        self.assertIn(('MD', 'RY1'), ctx.recovery_cache)
        self.assertGreater(a[0], 0.0)
        # a context without cheap sets scores 0
        bare = ScoringContext(priorities={}, regular_orders_by_key={},
                              earliest_dp_excluding={}, earliest_dp_time=_START,
                              new_machine_avail={})
        self.assertEqual(self.costing.recovery_detail(state, _rmove('MD', _RY1), bare), (0.0, []))
        # score_after_move with only `recovery` weighted equals w × quantity
        costing = Costing(_weights(recovery=2.5))
        move = _rmove('MD', _RY1)
        self.assertAlmostEqual(costing.score_after_move(state, move, ctx), 2.5 * a[0])
        # the debug cost_summary carries a `recovery` row of kind `other`
        run_mod = _importlib.import_module('swmtplanner.planners.infinite.run')
        dl = run_mod._build_debug_log()
        dl.add_row('iteration_log', iteration_idx=0, order_id=None,
                   order_remaining_lbs=0.0, machine='MD', decision_point='schedule_tail')
        costing.score_after_move(state, move, ctx, debuglog=dl)
        cs = dl.get_df('cost_summary').reset_index()
        row = cs[cs.label == 'recovery'].iloc[0]
        self.assertEqual(row.kind, 'other')
        self.assertAlmostEqual(row.raw, a[0])
        self.assertAlmostEqual(row.cost, 2.5 * a[0])


# --- 1.6 Idle machines left out of the outputs ----------------------------

from swmtplanner.planners.infinite.report import (
    schedule_dataframe, collapsed_schedule_dataframe,
)


class IdleMachinesOmittedTests(unittest.TestCase):

    def setUp(self):
        self.idle = (Idle(start=_START, end=_START + timedelta(hours=8)),
                     Idle(start=_START + timedelta(hours=8), end=_START + timedelta(hours=9),
                          reason='tape_out slot'))
        self.work = (Knit(start=_START, end=_START + timedelta(hours=1), item=_ITEM_A, lbs=100.0),
                     Doff(start=_START + timedelta(hours=1), end=_START + timedelta(hours=1, minutes=20)))

    def test_has_work(self):
        self.assertFalse(_sj.has_work(()))
        self.assertFalse(_sj.has_work(self.idle))
        self.assertTrue(_sj.has_work(self.idle + self.work[:1]))

    def test_schedule_json_omits_idle_machines(self):
        report = _report({'M_IDLE': self.idle, 'M1': self.work, 'M_EMPTY': ()}, None)
        out = _sj.schedule_json(report)
        self.assertEqual([m['id'] for m in out], ['M1'])
        machines = {'M_IDLE': _make_machine('M_IDLE'), 'M1': _make_machine('M1')}
        machines['M_IDLE'].add_activities(list(self.idle))
        machines['M1'].add_activities(list(self.work))
        self.assertEqual([m['id'] for m in _sj.machines_schedule_json(machines)], ['M1'])

    def test_sheets_omit_idle_machines(self):
        report = _report({'M_IDLE': self.idle, 'M1': self.work}, None)
        sched = schedule_dataframe(report)
        self.assertEqual(set(sched.index.get_level_values('machine')), {'M1'})
        collapsed = collapsed_schedule_dataframe(report)
        self.assertEqual(set(collapsed.index.get_level_values('machine')), {'M1'})


if __name__ == '__main__':
    unittest.main()


# --- 1.7 Assigned sets passed over in the outputs / 1.8 Sticking to the prior plan ---
# (tests/spec-files/INF_PLAN_TEST_SPEC.md)

import json as _json
import tempfile as _tempfile
from pathlib import Path as _Path

import pandas as _pd

from swmtplanner.schedule import Hanging as _Hanging, Knit as _Knit
from swmtplanner.schedule.activity import BEAM_FLOOR_LBS as _FLOOR
from swmtplanner.planners.infinite.loop import build_report, recommit_prior
from swmtplanner.planners.infinite.state import PriorCommit
from swmtplanner.planners.infinite.run import passed_over_lines, prior_commits
from swmtplanner.planners.infinite.schedule_json import schedule_json, order_due_dates
from swmtplanner.planners.infinite.report import (
    _activity_desc, prior_jobs_dataframe, write_plan_report_xlsx,
)
from swmtplanner.planners.retime import PriorJob, prior_jobs as _read_prior_jobs

_QB = BeamSet('QB', 'MX', 900.0, BeamSetDesc('30D RED 1000X4'), _FIXTURE_DATE, vendor='V',
              known_merge=True, assigned=True)


def _passed_over_state():
    """A state whose `M1` plan passed a queued set over (its top at the
    floor with a non-fitting set queued), committed; `M2` passed nothing."""
    m1 = Machine('M1', _ITEM_A, _START, _TOP_BEAM, _FLOOR, _BTM_BEAM, 1800.0, _24_7,
                 init_top_queue=(_QB,))
    m2 = _make_machine('M2')
    state = _make_state(machines={'M1': m1, 'M2': m2})
    for m in (m1, m2):
        m.commit_plan(m.plan_production(_ITEM_A, 100.0, 'schedule_tail'))
    return state


class PassedOverOutputTests(unittest.TestCase):
    """1.7"""

    def test_report_maps_machines_with_pass_overs(self):
        state = _passed_over_state()
        report = build_report(state, Costing(_weights()))
        self.assertEqual(list(report.queue_passed_over), ['M1'])
        self.assertEqual([p.beam_set.set_no for p in report.queue_passed_over['M1']], ['QB'])
        empty = build_report(_make_state(), Costing(_weights()))
        self.assertEqual(empty.queue_passed_over, {})

    def test_run_lines(self):
        self.assertEqual(passed_over_lines(build_report(_make_state(), Costing(_weights()))), [])
        lines = passed_over_lines(build_report(_passed_over_state(), Costing(_weights())))
        self.assertEqual(len(lines), 2)
        self.assertIn('passed over', lines[0])
        self.assertIn(': 1', lines[0])
        self.assertIn('M1', lines[1]); self.assertIn('top', lines[1]); self.assertIn('set QB', lines[1])
        self.assertIn('30D RED 1000X4', lines[1]); self.assertIn('merge MX', lines[1])
        self.assertIn('bar needed 40D BLACK 1000X4', lines[1])

    def test_schedule_json_hanging_passed_over(self):
        report = build_report(_passed_over_state(), Costing(_weights()))
        data = {m['id']: m for m in schedule_json(report)}
        def hangs(mid):
            return [a for e in data[mid]['schedule'] if e.get('kind') == 'job'
                    for a in e['activities'] if a['kind'] == 'Hanging']
        h1 = hangs('M1')[0]
        self.assertEqual([(p['bar'], p['set_no'], p['merge'], p['desc']) for p in h1['passed_over']],
                         [('top', 'QB', 'MX', '30D RED 1000X4')])
        m2_hangs = hangs('M2')
        self.assertTrue(all('passed_over' not in h for h in m2_hangs))

    def test_knit_sets_in_json_and_desc(self):
        report = build_report(_make_state_with_plan(), Costing(_weights()))
        data = schedule_json(report)
        knit = next(a for e in data[0]['schedule'] if e.get('kind') == 'job'
                    for a in e['activities'] if a['kind'] == 'Knit')
        self.assertEqual((knit['top_beam']['set_no'], knit['btm_beam']['set_no']),
                         (_TOP_BEAM.set_no, _BTM_BEAM.set_no))
        k = next(a for a in report.schedules['M1'] if isinstance(a, _Knit))
        desc = _activity_desc(k)
        self.assertIn(f'top #{_TOP_BEAM.set_no}', desc)
        self.assertIn(f'btm #{_BTM_BEAM.set_no}', desc)
        self.assertTrue(desc.startswith(_ITEM_A.id))
        bare = _Knit(start=_START, end=_START, item=_ITEM_A, lbs=1.0)
        self.assertEqual(_activity_desc(bare), _ITEM_A.id)


def _make_state_with_plan():
    state = _make_state()
    m = state.machines['M1']
    m.commit_plan(m.plan_production(_ITEM_A, 100.0, 'schedule_tail'))
    return state


_WEEK = timedelta(days=7)
_NOSAFE = Greige('AU0001', family='A', tgt_wt=100.0, top_beam='40D BLACK 1000X4', top_pct=0.5,
                 btm_beam='60D WHITE 1000X4', btm_pct=0.5, safety=0.0, machines={'M1': 100.0, 'M2': 100.0})


def _pc(machine='M1', prior='J1', item=_ITEM_A.id, rolls=1, order='P1@AU0001',
        due=_START + _WEEK, start=_START) -> PriorCommit:
    return PriorCommit(machine=machine, prior_job=prior, item=item, rolls=rolls,
                       order=order, due_date=due, start=start)


def _prior_state(*commits, machines=None, rls_items=None, **kw):
    state = _make_state(machines=machines, rls_items=rls_items, **kw)
    for pc in commits:
        state.prior.setdefault(pc.machine, []).append(pc)
    return state


def _remaining(state, item_id, week):
    return next(o.remaining_lbs for o in state.rls_items[item_id].safety_view.orders
                if o.week.week_idx == week)


class PriorPlanTests(unittest.TestCase):
    """1.8"""

    def test_prior_commits(self):
        jobs = {'M1': [PriorJob('J2', 'AU0001', 'P1@AU0001', 2, _START + timedelta(hours=5)),
                       PriorJob('J0', 'AU0001', None, 1, _START),
                       PriorJob('J1', 'AU0001', 'P0@AU0001', 1, _START + timedelta(hours=1)),
                       PriorJob('J3', 'AU0001', 'P2@AU0001', 0, _START + timedelta(hours=9))],
                'M2': [PriorJob('J9', 'AU0001', None, 3, _START)]}
        out = prior_commits(jobs)
        self.assertEqual(list(out), ['M1'])
        self.assertEqual([(pc.prior_job, pc.rolls, pc.order, pc.status) for pc in out['M1']],
                         [('J1', 1, 'P0@AU0001', 'open'), ('J2', 2, 'P1@AU0001', 'open')])
        self.assertEqual(prior_commits({}), {})

    def test_recommitting(self):
        # Week 1 is the earliest open order, so the job's production lands on it.
        state = _prior_state(_pc(rolls=1), rls_items={'AU0001': _make_rls_item(weekly=[0.0, 100.0, 0.0, 0.0])})
        before = _remaining(state, 'AU0001', 1)
        self.assertEqual(recommit_prior(state), 1)
        m = state.machines['M1']
        job = m.jobs[-1]
        self.assertEqual((job.tgt_order, job.prior_job, job.total_lbs), ('P1@AU0001', 'J1', 100.0))
        pc = state.prior['M1'][0]
        self.assertEqual((pc.status, pc.job_id, pc.note), ('consumed', job.id, ''))
        self.assertAlmostEqual(_remaining(state, 'AU0001', 1), max(0.0, before - 100.0))
        self.assertEqual(recommit_prior(state), 0)

    def test_order_of_the_walk(self):
        rls = {'AU0001': _make_rls_item(weekly=[0.0, 1000.0, 0.0, 0.0])}
        state = _prior_state(_pc('M1', 'JA', start=_START + timedelta(hours=2)),
                             _pc('M2', 'JB', start=_START),
                             machines={'M1': _make_machine('M1'), 'M2': _make_machine('M2')},
                             rls_items=rls)
        self.assertEqual(recommit_prior(state), 2)
        ja = state.prior['M1'][0].job_id; jb = state.prior['M2'][0].job_id
        self.assertLess(jb, ja)

    def test_not_urgent(self):
        rls = {'AU0001': _make_rls_item(weekly=[0.0, 0.0, 100.0, 0.0])}
        pc = _pc(order='P2@AU0001', due=_START + 2 * _WEEK)
        state = _prior_state(pc, rls_items=rls)
        self.assertEqual(recommit_prior(state), 0)
        self.assertEqual((pc.status, pc.note), ('open', 'not urgent'))
        self.assertEqual(state.machines['M1'].jobs, ())
        pc2 = _pc(order='P2@AU0001', due=_START + 2 * _WEEK)
        state2 = _prior_state(pc2, rls_items={'AU0001': _make_rls_item(weekly=[0.0, 0.0, 100.0, 0.0])},
                              reference_week_idx=2)
        self.assertEqual(recommit_prior(state2), 1)
        self.assertEqual(pc2.status, 'consumed')

    def test_filled(self):
        rls = {'AU0001': _make_rls_item(weekly=[0.0, 0.0, 0.0, 0.0])}
        pc = _pc()
        state = _prior_state(pc, rls_items=rls)
        self.assertEqual(recommit_prior(state), 0)
        self.assertEqual((pc.status, pc.note), ('dropped', 'order filled'))
        first, second = _pc(prior='J1', rolls=1, start=_START), _pc(prior='J2', rolls=1,
                                                                   start=_START + timedelta(hours=1))
        state = _prior_state(first, second, rls_items={'AU0001': _make_rls_item(weekly=[0.0, 100.0, 0.0, 0.0])})
        self.assertEqual(recommit_prior(state), 1)
        self.assertEqual((first.status, second.status, second.note), ('consumed', 'dropped', 'order filled'))

    def test_no_such_order(self):
        cases = [_pc(order='S@AU0001', due=None),
                 _pc(due=_START + timedelta(days=3)),
                 _pc(item='ZZ', order='P1@ZZ')]
        state = _prior_state(*cases, rls_items={'AU0001': _make_rls_item(weekly=[0.0, 100.0, 0.0, 0.0])})
        self.assertEqual(recommit_prior(state), 0)
        self.assertTrue(all((c.status, c.note) == ('dropped', 'no such order') for c in cases))

    def test_refused(self):
        elsewhere = Greige('AU0007', family='A', tgt_wt=100.0,
                           top_beam='40D BLACK 1000X4', top_pct=0.4,
                           btm_beam='60D WHITE 1000X4', btm_pct=0.6,
                           safety=0.0, machines={'M9': 100.0})
        rls = {'AU0007': RlsItem(item=elsewhere, start_date=_START, on_hand_lbs=0.0,
                                 lead_time=timedelta(days=7), weekly_lbs_needed=[0.0, 100.0, 0.0, 0.0]),
               'AU0001': _make_rls_item(weekly=[0.0, 100.0, 0.0, 0.0])}
        bad = _pc(prior='JX', item='AU0007', order='P1@AU0007', start=_START)
        good = _pc(prior='JY', start=_START + timedelta(hours=1))
        state = _prior_state(bad, good, rls_items=rls)
        self.assertEqual(recommit_prior(state), 1)
        self.assertEqual(bad.status, 'dropped')
        self.assertIn('cannot run', bad.note)
        self.assertEqual(good.status, 'consumed')

    def test_the_loop_and_the_sheet(self):
        state = _prior_state(_pc(rolls=1))
        report = plan(state, Costing(_weights()))
        self.assertEqual(len(report.prior), 1)
        self.assertEqual(report.prior[0].status, 'consumed')
        first_job = state.machines['M1'].jobs[0]
        self.assertEqual(first_job.prior_job, 'J1')
        df = prior_jobs_dataframe(report)
        self.assertEqual(list(df.columns), ['machine', 'prior_job', 'item', 'rolls', 'order',
                                            'due_date', 'start', 'status', 'job_id', 'note'])
        self.assertEqual(len(df), 1)
        with _tempfile.TemporaryDirectory() as d:
            path = _Path(d) / 'plan.xlsx'
            write_plan_report_xlsx(report, path)
            self.assertIn('prior_jobs', _pd.ExcelFile(path).sheet_names)
            plain = plan(_make_state(), Costing(_weights()))
            write_plan_report_xlsx(plain, path)
            self.assertNotIn('prior_jobs', _pd.ExcelFile(path).sheet_names)

    def test_schedule_json_due_date_and_prior_job(self):
        state = _prior_state(_pc(rolls=1), rls_items={'AU0001': _make_rls_item(weekly=[0.0, 100.0, 0.0, 0.0])})
        recommit_prior(state)
        report = build_report(state, Costing(_weights()))
        due = order_due_dates(report)
        self.assertEqual(due['P1@AU0001'], _START + _WEEK)
        data = schedule_json(report)
        job = next(e for e in data[0]['schedule'] if e.get('kind') == 'job' and e['tgt_order'])
        self.assertEqual(job['prior_job'], 'J1')
        self.assertIsNotNone(job['due_date'])
        back = _read_prior_jobs(data, ['M1'])['M1']
        with_order = next(j for j in back if j.order == 'P1@AU0001')
        self.assertEqual(with_order.due_date, _START + _WEEK)
        run_up = [j for j in back if j.order is None]
        self.assertTrue(all(j.due_date is None for j in run_up))
        stripped = _json.loads(_json.dumps(data))
        for e in stripped[0]['schedule']:
            e.pop('due_date', None)
        self.assertTrue(all(j.due_date is None for j in _read_prior_jobs(stripped, ['M1'])['M1']))


# --- 1.3.4 Economic order quantity / 1.8.10 the frozen window ------------------

from swmtplanner.planners.infinite.coordination import unique_setups as _unique_setups

_SLOW_UNIQUE = Greige(
    'AU0101', family='A', tgt_wt=100.0,
    top_beam='30D RED 1000X4', top_pct=0.5,
    btm_beam='90D GREEN 1000X4', btm_pct=0.5,
    safety=0.0, machines={'M1': 1.0},          # 1 lb/h: a week's cap is well under a batch
)
_FAST_UNIQUE = Greige(
    'AU0102', family='A', tgt_wt=100.0,
    top_beam='30D RED 1000X4', top_pct=0.5,
    btm_beam='90D GREEN 1000X4', btm_pct=0.5,
    safety=0.0, machines={'M1': 100.0},
)
_U_TOP = BeamSet.new(BeamSetDesc('30D RED 1000X4'), 2800.0, _FIXTURE_DATE)
_U_BTM = BeamSet.new(BeamSetDesc('90D GREEN 1000X4'), 1800.0, _FIXTURE_DATE)


def _unique_machine(item=_FAST_UNIQUE) -> Machine:
    return Machine('M1', item, _START, _U_TOP, 2800.0, _U_BTM, 1800.0, _24_7)


def _rls(item, weekly, safety=0.0):
    return RlsItem(item=item, start_date=_START, on_hand_lbs=0.0,
                   lead_time=timedelta(days=7), weekly_lbs_needed=weekly)


def _only_move(state):
    cands = enumerate_candidates(state)
    self_check = [m for m in cands if m.start_at == 'schedule_tail']
    assert len(self_check) == 1, [(m.item.id, m.start_at, m.lbs) for m in cands]
    return self_check[0]


class EconomicOrderQuantityTests(unittest.TestCase):
    """1.3.4"""

    def test_unique_setups(self):
        state = _make_state(rls_items={'AU0001': _make_rls_item(_ITEM_A), 'AU0002': _make_rls_item(_ITEM_B),
                                       'AU0102': _rls(_FAST_UNIQUE, [100.0] * 4)})
        self.assertEqual(_unique_setups(state), {'AU0102'})
        self.assertEqual(_unique_setups(_make_state()), {'AU0001'})
        split = Greige('AU0103', family='A', tgt_wt=100.0, top_beam='30D RED 1000X4 S/L', top_pct=0.5,
                       btm_beam='90D GREEN 1000X4', btm_pct=0.5, safety=0.0, machines={'M1': 100.0})
        state = _make_state(rls_items={'AU0102': _rls(_FAST_UNIQUE, [100.0] * 4), 'AU0103': _rls(split, [100.0] * 4)})
        self.assertEqual(_unique_setups(state), set())        # split lease aside, the same setup

    def test_small_unique_move_is_batched(self):
        state = _make_state(machines={'M1': _unique_machine()},
                            rls_items={'AU0102': _rls(_FAST_UNIQUE, [100.0] * 6)})
        move = _only_move(state)
        self.assertEqual(move.lbs, 400.0)                      # weeks 0-3, not the 200 open
        self.assertEqual((move.week_idx, move.order_remaining_lbs), (0, 100.0))
        self.assertEqual(move.plan.jobs[-1].tgt_order, 'P0@AU0102')

    def test_batch_is_not_capped_at_the_week(self):
        state = _make_state(machines={'M1': _unique_machine(_SLOW_UNIQUE)},
                            rls_items={'AU0101': _rls(_SLOW_UNIQUE, [100.0] * 6)})
        move = _only_move(state)
        self.assertEqual(move.lbs, 400.0)
        state2 = _make_state(machines={'M1': _unique_machine(_SLOW_UNIQUE)},
                             rls_items={'AU0101': _rls(_SLOW_UNIQUE, [100.0] * 6)}, eoq_threshold_rolls=0)
        self.assertLess(_only_move(state2).lbs, 400.0)         # the week's cap, batching off

    def test_all_demand_pulled_in_and_rounded(self):
        state = _make_state(machines={'M1': _unique_machine()},
                            rls_items={'AU0102': _rls(_FAST_UNIQUE, [60.0, 60.0, 60.0, 60.0])})
        self.assertEqual(_only_move(state).lbs, 200.0)         # 240 lbs of demand -> 2 whole rolls

    def test_above_threshold_not_batched(self):
        state = _make_state(machines={'M1': _unique_machine()},
                            rls_items={'AU0102': _rls(_FAST_UNIQUE, [200.0, 200.0, 200.0, 200.0])})
        self.assertEqual(_only_move(state).lbs, 400.0)         # 4 open rolls: sized as before
        state2 = _make_state(machines={'M1': _unique_machine()},
                             rls_items={'AU0102': _rls(_FAST_UNIQUE, [200.0, 200.0, 200.0, 200.0])},
                             eoq_threshold_rolls=4, eoq_batch_rolls=6)
        self.assertEqual(_only_move(state2).lbs, 600.0)        # the thresholds are tunable

    def test_shared_setup_and_safety_not_batched(self):
        rls = {'AU0001': _make_rls_item(_ITEM_A, weekly=[100.0] * 6)}
        state = _make_state(rls_items={**rls, 'AU0002': _make_rls_item(_ITEM_B, weekly=[100.0] * 6)})
        a = next(m for m in enumerate_candidates(state) if m.item is _ITEM_A and m.start_at == 'schedule_tail')
        self.assertEqual(a.lbs, 200.0)                          # A and B share a setup: open demand only
        safety = Greige('AU0104', family='A', tgt_wt=100.0, top_beam='30D RED 1000X4', top_pct=0.5,
                        btm_beam='90D GREEN 1000X4', btm_pct=0.5, safety=150.0, machines={'M1': 100.0})
        state = _make_state(machines={'M1': _unique_machine(safety)},
                            rls_items={'AU0104': _rls(safety, [0.0, 0.0, 0.0, 0.0])})
        move = _only_move(state)
        self.assertIsNone(move.week_idx)
        self.assertEqual(move.lbs, 100.0)                       # the 150-lb gap, whole rolls


class FrozenWindowTests(unittest.TestCase):
    """1.8.10"""

    def test_window_bounds_the_pre_pass(self):
        rls = {'AU0001': _make_rls_item(weekly=[0.0, 100.0, 0.0, 0.0])}
        late = _pc(start=_START + timedelta(days=2))
        state = _prior_state(late, rls_items=rls, frozen_window=timedelta(days=1))
        self.assertEqual(recommit_prior(state), 0)
        self.assertEqual((late.status, late.note), ('open', 'outside the frozen window'))
        for window in (timedelta(days=3), None):
            pc = _pc(start=_START + timedelta(days=2))
            state = _prior_state(pc, rls_items={'AU0001': _make_rls_item(weekly=[0.0, 100.0, 0.0, 0.0])},
                                 frozen_window=window)
            self.assertEqual(recommit_prior(state), 1, window)
            self.assertEqual(pc.status, 'consumed')


# --- 1.3.5 Filling a slot wait / 1.5 change rows / 1.8.11 / 1.9 ----------------

from swmtplanner.schedule import Fill as _Fill, RunnerChange as _RunnerChange
from swmtplanner.planners.infinite.loop.candidates import fill_for as _fill_for
from swmtplanner.planners.infinite.report import production_dataframe as _production_df

_SAFE250 = Greige('AU0001', family='A', tgt_wt=100.0, top_beam='40D BLACK 1000X4', top_pct=0.5,
                  btm_beam='60D WHITE 1000X4', btm_pct=0.5, safety=250.0,
                  machines={'M1': 100.0, 'M2': 100.0})
_NONE = Greige('NONE', family='A', tgt_wt=100.0, top_beam='40D BLACK 1000X4', top_pct=0.5,
               btm_beam='60D WHITE 1000X4', btm_pct=0.5, safety=0.0, machines={'M1': 100.0})
# _ITEM_A's yarn and family, runnable on M2 only — M1 may still be set up for it.
_ITEM_X = Greige('AU000X', family='A', tgt_wt=100.0, top_beam='40D BLACK 1000X4', top_pct=0.5,
                 btm_beam='60D WHITE 1000X4', btm_pct=0.5, safety=0.0, machines={'M2': 100.0})


def _change_booked(day=None):
    """The full ration with every change unit of `day` (the start day) taken."""
    cap = ChangeoverCapacity(_24_7, DEFAULT_RESOURCES)
    cap.book('change', day or _START.date(), DEFAULT_RESOURCES['change'].units_per_period)
    return cap


def _two_item_state(capacity=None, **kw):
    """M1 on A; A has 100 lbs open in week 1, B 100 lbs in week 1."""
    return _make_state(
        machines={'M1': _make_machine('M1')}, capacity=capacity,
        rls_items={'AU0001': _make_rls_item(item=_NOSAFE, weekly=[0.0, 100.0, 0.0, 0.0]),
                   'AU0002': _make_rls_item(item=_ITEM_B, weekly=[0.0, 100.0, 0.0, 0.0])},
        **kw)


class FillForTests(unittest.TestCase):
    """1.3.5"""

    def test_sizing(self):
        m = _make_machine('M1')
        state = _make_state(machines={'M1': m}, rls_items={
            'AU0001': _make_rls_item(item=_NOSAFE, weekly=[0.0, 150.0, 0.0, 100.0])})
        self.assertEqual(_fill_for(state, m, _ITEM_B), _Fill(3, 'P1@AU0001'))
        state = _make_state(machines={'M1': m}, rls_items={
            'AU0001': _make_rls_item(item=_SAFE250, weekly=[0.0, 0.0, 0.0, 0.0])})
        self.assertEqual(_fill_for(state, m, _ITEM_B), _Fill(3, 'S@AU0001'))
        state = _make_state(machines={'M1': m}, rls_items={
            'AU0001': _make_rls_item(item=_SAFE250, weekly=[0.0, 150.0, 0.0, 100.0])})
        self.assertEqual(_fill_for(state, m, _ITEM_B), _Fill(5, 'P1@AU0001'))

    def test_none(self):
        m = _make_machine('M1')
        self.assertIsNone(_fill_for(_make_state(machines={'M1': m}), m, _ITEM_A))
        self.assertIsNone(_fill_for(_make_state(
            machines={'M1': m}, rls_items={'AU0002': _make_rls_item(item=_ITEM_B)}), m, _ITEM_B))
        empty = _make_state(machines={'M1': m}, rls_items={
            'AU0001': _make_rls_item(item=_NOSAFE, weekly=[0.0, 0.0, 0.0, 0.0])})
        self.assertIsNone(_fill_for(empty, m, _ITEM_B))
        none = _make_machine('M1', init_item=_NONE)
        self.assertIsNone(_fill_for(_make_state(machines={'M1': none}), none, _ITEM_B))
        bad = _make_machine('M1', init_item=_ITEM_X)        # cannot run its item
        self.assertIsNone(_fill_for(_make_state(machines={'M1': bad}, rls_items={
            'AU000X': _make_rls_item(item=_ITEM_X, weekly=[0.0, 150.0, 0.0, 0.0])}), bad, _ITEM_B))

    def test_candidates_carry_the_fill(self):
        cap = _change_booked()
        state = _two_item_state(capacity=cap)
        m = state.machines['M1']
        moves = enumerate_candidates(state)
        change = next(mv for mv in moves if mv.item.id == 'AU0002' and mv.start_at == 'schedule_tail')
        cont = next(mv for mv in moves if mv.item.id == 'AU0001')
        self.assertEqual([(j.item.id, j.fill) for j in change.plan.jobs],
                         [('AU0001', True), ('AU0002', False)])
        wait = sum((a.end - a.start for a in change.plan.activities
                    if isinstance(a, Idle) and a.reason), timedelta(0))
        plain = m.plan_production(_ITEM_B, change.lbs, start_at='schedule_tail', capacity=cap)
        plain_wait = sum((a.end - a.start for a in plain.activities if isinstance(a, Idle)),
                         timedelta(0))
        self.assertLess(wait, plain_wait)
        self.assertFalse(any(j.fill for j in cont.plan.jobs))
        self.assertEqual(cap.bookings(), {('change', _START.date()): 5})


class CannotRunItemCandidateTests(unittest.TestCase):
    """1.3.6 — M1 set up for `_ITEM_X`, which may run on M2 only."""

    def _state(self):
        m = _make_machine('M1', init_item=_ITEM_X)
        return _make_state(
            machines={'M1': m},
            rls_items={'AU0001': _make_rls_item(item=_ITEM_A, weekly=[100.0, 100.0, 0.0, 0.0]),
                       'AU000X': _make_rls_item(item=_ITEM_X, weekly=[100.0, 100.0, 0.0, 0.0])},
            window_end=_START + timedelta(days=1))

    def test_one_decision_point(self):
        state = self._state()
        self.assertEqual(eligible_decision_points(state),
                         [DecisionPoint('M1', 'schedule_tail', _START)])

    def test_open_to_what_it_can_run(self):
        state = self._state()
        moves = enumerate_candidates(state)
        self.assertTrue(moves)
        self.assertEqual({(mv.item.id, mv.start_at) for mv in moves}, {('AU0001', 'schedule_tail')})
        for mv in moves:
            self.assertEqual([j.item.id for j in mv.plan.jobs], ['AU0001'])
            self.assertFalse(any(j.fill for j in mv.plan.jobs))


class ChangeRowsTests(unittest.TestCase):
    """1.5 — change rows"""

    def test_change_rows_and_waits(self):
        cap = ChangeoverCapacity(_24_7, DEFAULT_RESOURCES)
        t0 = _START + timedelta(hours=9)
        tape_both = TapeOut(start=t0, end=t0 + timedelta(hours=3), bars='both')
        pattern = PatternChange(start=t0 + timedelta(hours=4), end=t0 + timedelta(hours=5.5),
                                from_item=_ITEM_A, to_item=_ITEM_B)
        tape_top = TapeOut(start=t0 + timedelta(days=1), end=t0 + timedelta(days=1, hours=2),
                           bars='top')
        knit = _Knit(start=tape_top.end, end=tape_top.end + timedelta(hours=1),
                     item=_ITEM_A, lbs=100.0)
        runner = _RunnerChange(start=t0 + timedelta(days=2), end=t0 + timedelta(days=2, hours=1),
                               from_item=_ITEM_A, to_item=_ITEM_B)
        wait = Idle(start=_START, end=t0, reason='change slot')
        df = changeovers_dataframe(_report(
            {'M1': (tape_both, pattern), 'M2': (tape_top, knit), 'M3': (wait, runner)}, cap))
        changes = df[(df.row == 'period') & (df.resource == 'change')].reset_index(drop=True)
        self.assertEqual(list(changes.day), [_START.date(), (_START + timedelta(days=1)).date(),
                                             (_START + timedelta(days=2)).date()])
        self.assertEqual(list(changes.used), [1, 1, 1])
        self.assertEqual(list(changes.capacity), [5, 5, 5])
        self.assertEqual(changes.activities[0], f'M1:{tape_both.id}@09:00')
        self.assertEqual(changes.activities[1], f'M2:{tape_top.id}@09:00')
        self.assertEqual(changes.activities[2], f'M3:{runner.id}@09:00')
        waits = df[df.row == 'wait'].reset_index(drop=True)
        self.assertEqual(list(waits.resource), ['change'])
        # the per-kind rows are unchanged beside them
        self.assertEqual(list(df[(df.row == 'period') & (df.resource == 'tape_out')].used), [2, 1])


class PrePassFillTests(unittest.TestCase):
    """1.8.11"""

    def test_fill_in_the_pre_pass(self):
        pc = _pc(item='AU0002', order='P1@AU0002')
        state = _two_item_state(capacity=_change_booked())
        state.prior['M1'] = [pc]
        self.assertEqual(recommit_prior(state), 1)
        jobs = state.machines['M1'].jobs
        self.assertEqual([(j.item.id, j.fill, j.prior_job) for j in jobs],
                         [('AU0001', True, None), ('AU0002', False, 'J1')])
        self.assertEqual(jobs[0].tgt_order, 'P1@AU0001')


class FillOutputsTests(unittest.TestCase):
    """1.9"""

    def _report(self):
        state = _two_item_state(capacity=_change_booked())
        state.prior['M1'] = [_pc(item='AU0002', order='P1@AU0002')]
        recommit_prior(state)
        return build_report(state, Costing(_weights()))

    def test_production_sheet(self):
        df = _production_df(self._report())
        self.assertIn('fill', df.columns)
        self.assertEqual(sorted(df['fill'].tolist()), [False, True])

    def test_schedule_json(self):
        data = schedule_json(self._report())
        jobs = [e for e in data[0]['schedule'] if e.get('kind') == 'job']
        self.assertEqual([j['fill'] for j in jobs], [True, False])


# --- 1.7.5 Blacklisted sets in the outputs ---------------------------------------

_QK = BeamSet('QK', 'MK', 900.0, BeamSetDesc('40D BLACK 1000X4'), _FIXTURE_DATE, vendor='V',
              known_merge=True, assigned=True, blacklisted=True)
_BLACK_TOP = BeamSet('SB', 'MK', 200.0, BeamSetDesc('40D BLACK 1000X4'), _FIXTURE_DATE,
                     vendor='V', known_merge=True, blacklisted=True)


class BlacklistOutputTests(unittest.TestCase):
    """1.7 items 2, 3 and 5 for blacklisted sets"""

    def _state(self):
        # M1's top is at the floor with a blacklisted set queued (passed
        # over); M2 has a blacklisted set mounted (taped out first).
        m1 = Machine('M1', _ITEM_A, _START, _TOP_BEAM, _FLOOR, _BTM_BEAM, 1800.0, _24_7,
                     init_top_queue=(_QK,))
        m2 = Machine('M2', _ITEM_A, _START, _BLACK_TOP, 200.0, _BTM_BEAM, 1800.0, _24_7)
        state = _make_state(machines={'M1': m1, 'M2': m2})
        for m in (m1, m2):
            m.commit_plan(m.plan_production(_ITEM_A, 100.0, 'schedule_tail'))
        return state

    def test_run_lines_carry_the_reason(self):
        report = build_report(self._state(), Costing(_weights()))
        lines = passed_over_lines(report)
        self.assertEqual(len(lines), 2)
        self.assertIn('set QK', lines[1])
        self.assertTrue(lines[1].endswith('blacklisted'))
        plain = passed_over_lines(build_report(_passed_over_state(), Costing(_weights())))
        self.assertTrue(plain[1].endswith('does not fit'))

    def test_schedule_json(self):
        data = {m['id']: m for m in schedule_json(build_report(self._state(), Costing(_weights())))}
        acts = [a for e in data['M1']['schedule'] if e.get('kind') == 'job' for a in e['activities']]
        hang = next(a for a in acts if a['kind'] == 'Hanging')
        self.assertEqual([(p['set_no'], p['reason'], p.get('blacklisted')) for p in hang['passed_over']],
                         [('QK', 'blacklisted', True)])
        self.assertNotIn('blacklisted', hang['top_beam'])
        tape = next(e for e in data['M2']['schedule'] if e['kind'] == 'TapeOut')
        self.assertEqual((tape['top_beam']['set_no'], tape['top_beam']['blacklisted']), ('SB', True))
        plain = {m['id']: m for m in schedule_json(build_report(_passed_over_state(), Costing(_weights())))}
        acts = [a for e in plain['M1']['schedule'] if e.get('kind') == 'job' for a in e['activities']]
        hang = next(a for a in acts if a['kind'] == 'Hanging')
        self.assertEqual([(p['set_no'], p['reason']) for p in hang['passed_over']], [('QB', 'does not fit')])
        self.assertNotIn('blacklisted', hang['passed_over'][0])


# --- 1.7.6 Hung and queued sets in the outputs -----------------------------------

from swmtplanner.schedule import Unhang as _Unhang
from swmtplanner.planners.infinite.report import _activity_desc as _desc

_HUNG_ALT = BeamSet('SH', 'MX', 500.0, BeamSetDesc('30D RED 1000X4'), _FIXTURE_DATE, vendor='V',
                    known_merge=True)
_QS = BeamSet('QS', 'M1', 900.0, BeamSetDesc('40D BLACK 1000X4'), _FIXTURE_DATE, vendor='V',
              known_merge=True, assigned=True, location='staged')


class HungSetOutputTests(unittest.TestCase):
    """1.7.6"""

    def test_location_and_unhang(self):
        m = Machine('M1', _ITEM_A, _START, _HUNG_ALT, 500.0, _BTM_BEAM, 1800.0, _24_7,
                    init_top_threaded=False, init_top_queue=(_QS,))
        m.commit_plan(m.plan_production(_ITEM_A, 100.0, 'schedule_tail'))
        report = build_report(_make_state(machines={'M1': m}), Costing(_weights()))
        entries = schedule_json(report)[0]['schedule']
        unhang = next(e for e in entries if e['kind'] == 'Unhang')
        self.assertEqual((unhang['bars'], unhang['top_beam']['set_no'], unhang['top_beam']['lbs'], unhang['btm_beam']),
                         ('top', 'SH', 500.0, None))
        self.assertNotIn('location', unhang['top_beam'])
        hang = next(a for e in entries if e.get('kind') == 'job' for a in e['activities'] if a['kind'] == 'Hanging')
        self.assertEqual((hang['top_beam']['set_no'], hang['top_beam']['location']), ('QS', 'staged'))
        act = next(a for a in m.activities if isinstance(a, _Unhang))
        self.assertTrue(_desc(act).startswith('unhung, never threaded: top'))
        self.assertIn('500 lbs back', _desc(act))
