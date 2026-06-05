#!/usr/bin/env python

import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from swmtplanner.demand.rlsitem import CostComponents, RlsItem
from swmtplanner.products import Greige
from swmtplanner.schedule import Job, Roll


# Greige fixtures shared with the view tests. RlsItem owns its own Order/View
# instances internally, so we don't need namedtuple stand-ins here.
_GREIGE_FIXTURE = Path(__file__).parent / 'data-files' / 'greige-styles.json'


def _load_greiges() -> dict[str, Greige]:
    with _GREIGE_FIXTURE.open() as f:
        data = json.load(f)
    return {
        g['id']: Greige(
            id=g['id'],
            family=g['family'],
            tgt_wt=g['tgt_wt'],
            top_beam=g['top_beam'],
            top_pct=g['top_pct'],
            btm_beam=g['btm_beam'],
            btm_pct=g['btm_pct'],
            safety=g['safety'],
            machines={m['id']: m['rate'] for m in g['machines']},
        )
        for g in data
    }


_GREIGES = _load_greiges()


_DEFAULT_LEAD_TIME = timedelta(days=7)


# RlsItem treats start_date as week 0's due_date, so to share the same week
# offsets as the view tests we anchor start_date one week past _START. With
# that anchor, RlsItem's week-i due_date matches _due(i).
_START = datetime(2026, 1, 1)


def _due(week_idx: int) -> datetime:
    return _START + timedelta(days=7 * (week_idx + 1))


def _make_rls_item(
    qtys: list[float],
    *,
    on_hand_lbs: float = 0.0,
    greige_id: str = 'AU2958G',
    lead_time: timedelta = _DEFAULT_LEAD_TIME,
) -> RlsItem:
    return RlsItem(
        item=_GREIGES[greige_id],
        start_date=_due(0),  # makes RlsItem week-i due == _due(i)
        on_hand_lbs=on_hand_lbs,
        lead_time=lead_time,
        weekly_lbs_needed=qtys,
    )


def _real_job(item: Greige, end_dt: datetime, lbs: float) -> Job:
    # A Job record delivering `lbs` as a single roll completing at
    # `end_dt`. The demand views read per-roll completion times, and
    # RlsItem sorts jobs by their final roll's completion_time — so a
    # single roll at `end_dt` preserves the FIFO ordering these tests
    # assume.
    return Job(item=item, rolls=(Roll(lbs=lbs, completion_time=end_dt),))


class RlsItemAllocationTests(unittest.TestCase):
    # Mirrors the non-empty-job allocation scenarios from RawView and
    # SafetyAwareView, driven through RlsItem.register_job, and verifies
    # that RlsItem.cost_if leaves the orders/views untouched after returning.

    def _assert_cost_if_is_pure(self, rls: RlsItem, hypothetical: Job) -> None:
        before_raw = [o.allocated_lbs for o in rls.raw_view.orders]
        before_safety = [o.allocated_lbs for o in rls.safety_view.orders]
        before_lateness = rls.raw_view.lateness
        before_safety_pool = rls.safety_view.safety_pool
        before_drainage = rls.safety_view.drainage
        before_carrying = rls.safety_view.carrying
        before_excess = rls.safety_view.excess

        rls.cost_if([hypothetical])

        self.assertEqual(
            [o.allocated_lbs for o in rls.raw_view.orders], before_raw,
        )
        self.assertEqual(
            [o.allocated_lbs for o in rls.safety_view.orders], before_safety,
        )
        self.assertEqual(rls.raw_view.lateness, before_lateness)
        self.assertEqual(rls.safety_view.safety_pool, before_safety_pool)
        self.assertEqual(rls.safety_view.drainage, before_drainage)
        self.assertEqual(rls.safety_view.carrying, before_carrying)
        self.assertEqual(rls.safety_view.excess, before_excess)

    # --- 1.1 In chronological order ---

    def test_raw_view_jobs_only_chronological(self):
        # Mirrors RawView's test_jobs_only_fills_orders_and_consumes_jobs_sequentially.
        rls = _make_rls_item([100, 200, 150, 300], on_hand_lbs=0)
        rls.register_jobs([_real_job(rls.item, _due(0), 300)])
        rls.register_jobs([_real_job(rls.item, _due(1), 200)])
        self.assertEqual(
            [o.allocated_lbs for o in rls.raw_view.orders],
            [100.0, 200.0, 150.0, 50.0],
        )
        self._assert_cost_if_is_pure(rls, _real_job(rls.item, _due(2), 500))

    def test_raw_view_on_hand_drain_chronological(self):
        # Mirrors RawView's test_on_hand_drains_before_jobs.
        rls = _make_rls_item([100, 200, 150, 300], on_hand_lbs=50)
        rls.register_jobs([_real_job(rls.item, _due(0), 300)])
        rls.register_jobs([_real_job(rls.item, _due(1), 200)])
        self.assertEqual(
            [o.allocated_lbs for o in rls.raw_view.orders],
            [100.0, 200.0, 150.0, 100.0],
        )
        self._assert_cost_if_is_pure(rls, _real_job(rls.item, _due(2), 500))

    def test_safety_view_jobs_fill_weeks_0_and_1_chronological(self):
        # Mirrors SafetyAwareView's test_jobs_fill_weeks_0_and_1_before_safety.
        # Single job, so only the chronological case applies.
        rls = _make_rls_item([100, 200, 150, 300], on_hand_lbs=0)
        rls.register_jobs([_real_job(rls.item, _due(0) + timedelta(days=4), 800)])
        self.assertEqual(
            [o.allocated_lbs for o in rls.safety_view.orders],
            [100.0, 200.0, 0.0, 0.0],
        )
        self.assertEqual(rls.safety_view.safety_pool, 500.0)
        self._assert_cost_if_is_pure(rls, _real_job(rls.item, _due(2), 500))

    def test_safety_view_job_late_to_all_chronological(self):
        # Mirrors SafetyAwareView's
        # test_job_late_to_all_orders_fills_every_order_before_safety.
        rls = _make_rls_item([100, 200, 150, 300], on_hand_lbs=0)
        rls.register_jobs([_real_job(rls.item, _due(3) + timedelta(days=7), 1250)])
        self.assertEqual(
            [o.allocated_lbs for o in rls.safety_view.orders],
            [100.0, 200.0, 150.0, 300.0],
        )
        self.assertEqual(rls.safety_view.safety_pool, 500.0)
        self._assert_cost_if_is_pure(rls, _real_job(rls.item, _due(2), 500))

    # --- 1.2 Out of chronological order ---

    def test_raw_view_jobs_only_reverse_order(self):
        # Same scenario as test_raw_view_jobs_only_chronological, but the
        # later-ending job is registered first. bisect_right inside
        # register_job should place it after the earlier job so the final
        # allocation matches the chronological case.
        rls = _make_rls_item([100, 200, 150, 300], on_hand_lbs=0)
        rls.register_jobs([_real_job(rls.item, _due(1), 200)])  # later first
        rls.register_jobs([_real_job(rls.item, _due(0), 300)])
        self.assertEqual(
            [o.allocated_lbs for o in rls.raw_view.orders],
            [100.0, 200.0, 150.0, 50.0],
        )
        self._assert_cost_if_is_pure(rls, _real_job(rls.item, _due(2), 500))

    def test_raw_view_on_hand_drain_reverse_order(self):
        # Reverse-order counterpart to test_raw_view_on_hand_drain_chronological.
        rls = _make_rls_item([100, 200, 150, 300], on_hand_lbs=50)
        rls.register_jobs([_real_job(rls.item, _due(1), 200)])
        rls.register_jobs([_real_job(rls.item, _due(0), 300)])
        self.assertEqual(
            [o.allocated_lbs for o in rls.raw_view.orders],
            [100.0, 200.0, 150.0, 100.0],
        )
        self._assert_cost_if_is_pure(rls, _real_job(rls.item, _due(2), 500))


class RlsItemCostTrackerTests(unittest.TestCase):
    # Drives scenarios through RlsItem.register_job and asserts on both views'
    # cost trackers simultaneously (raw_view.lateness alongside the safety
    # view's drainage / carrying / excess).

    # --- 2.1 Replays of SafetyAwareView cost-tracker tests ---
    # In each, raw_view.lateness should be 0 because those scenarios were
    # designed so the raw view sees no actual late deliveries.

    def test_all_zero_via_register_job(self):
        # Replays SafetyAwareView 2.2 (test_all_costs_zero_with_in_lead_time_job_fills).
        rls = _make_rls_item([100, 200, 150, 300], on_hand_lbs=1500)
        rls.register_jobs([_real_job(rls.item, _due(0) + timedelta(days=4),  200)])
        rls.register_jobs([_real_job(rls.item, _due(0) + timedelta(days=11), 150)])
        rls.register_jobs([_real_job(rls.item, _due(0) + timedelta(days=18), 300)])
        self.assertEqual(rls.raw_view.lateness, 0.0)
        self.assertEqual(rls.safety_view.drainage, 0.0)
        self.assertEqual(rls.safety_view.carrying, 0.0)
        self.assertEqual(rls.safety_view.excess, 0.0)

    def test_constant_drainage_at_safety_target_via_register_job(self):
        # Replays SafetyAwareView 2.3.1.1 (test_constant_drainage_at_safety_target).
        rls = _make_rls_item([100, 200, 150, 300], on_hand_lbs=100)
        rls.register_jobs([_real_job(rls.item, _due(1), 200)])
        rls.register_jobs([_real_job(rls.item, _due(2), 150)])
        rls.register_jobs([_real_job(rls.item, _due(3), 300)])
        self.assertEqual(rls.raw_view.lateness, 0.0)
        self.assertAlmostEqual(rls.safety_view.drainage, 1400.0 * 21)
        self.assertEqual(rls.safety_view.carrying, 0.0)
        self.assertEqual(rls.safety_view.excess, 0.0)

    def test_stacked_drainage_even_split_via_register_job(self):
        # Replays SafetyAwareView 2.3.2.2 (test_stacked_drainage_between_jobs_even_split).
        rls = _make_rls_item([100, 200, 150, 300], on_hand_lbs=1500)
        rls.register_jobs([_real_job(rls.item, _due(2) + timedelta(days=1), 350)])
        rls.register_jobs([_real_job(rls.item, _due(2) + timedelta(days=5), 300)])
        self.assertEqual(rls.raw_view.lateness, 0.0)
        self.assertAlmostEqual(rls.safety_view.drainage, 1750.0)
        self.assertEqual(rls.safety_view.carrying, 0.0)
        self.assertEqual(rls.safety_view.excess, 0.0)

    def test_stacked_drainage_interleaved_via_register_job(self):
        # Replays SafetyAwareView 2.3.2.3 (test_stacked_drainage_interleaved_with_jobs).
        rls = _make_rls_item([100, 200, 150, 300], on_hand_lbs=1500)
        rls.register_jobs([_real_job(rls.item, _due(1) + timedelta(days=1), 100)])
        rls.register_jobs([_real_job(rls.item, _due(2) + timedelta(days=1), 250)])
        rls.register_jobs([_real_job(rls.item, _due(2) + timedelta(days=5), 300)])
        self.assertEqual(rls.raw_view.lateness, 0.0)
        self.assertAlmostEqual(rls.safety_view.drainage, 1050.0)
        self.assertEqual(rls.safety_view.carrying, 0.0)
        self.assertEqual(rls.safety_view.excess, 0.0)

    def test_no_stacked_with_carrying_via_register_job(self):
        # Replays SafetyAwareView 2.4.1 (test_no_stacked_drainage_with_carrying_and_no_excess).
        rls = _make_rls_item([100, 200, 150, 300], on_hand_lbs=600)
        rls.register_jobs([_real_job(rls.item, _due(0) + timedelta(days=1), 1200)])
        rls.register_jobs([_real_job(rls.item, _due(2) + timedelta(days=1), 350)])
        self.assertEqual(rls.raw_view.lateness, 0.0)
        self.assertAlmostEqual(rls.safety_view.drainage, 950.0)
        self.assertAlmostEqual(rls.safety_view.carrying, 600.0)
        self.assertEqual(rls.safety_view.excess, 0.0)

    def test_stacked_with_carrying_via_register_job(self):
        # Replays SafetyAwareView 2.4.3 (test_stacked_drainage_with_carrying_and_no_excess).
        rls = _make_rls_item([100, 200, 150, 300], on_hand_lbs=100)
        rls.register_jobs([_real_job(rls.item, _due(0), 200)])
        rls.register_jobs([_real_job(rls.item, _due(1) + timedelta(days=1), 1850)])
        self.assertEqual(rls.raw_view.lateness, 0.0)
        self.assertAlmostEqual(rls.safety_view.drainage, 9800.0)
        self.assertAlmostEqual(rls.safety_view.carrying, 1800.0)
        self.assertEqual(rls.safety_view.excess, 0.0)

    # --- 2.2 Scenarios exercising both views' cost trackers at once ---

    def test_combined_lateness_drainage_and_carrying(self):
        # demand=[100, 200, 150, 300], on_hand=0. No early on-hand → orders 0
        # and 1 must wait for jobs that arrive after their due dates,
        # producing raw_view.lateness > 0. The same job stream is also short
        # of safety until the second job arrives, producing safety-view
        # drainage and carrying.
        #
        # Job A: 100 lbs at week_0.due+1d (1 day late for order 0).
        # Job B: 2050 lbs at week_1.due+1d (1 day late for order 1, on-time
        # for orders 2 and 3; refunds order 1 in bucket 1, fills order 2 in
        # bucket 1, tops safety in bucket 2, and lands 300 lbs in bucket 3
        # for order 3 held 13 days → 6 days past lead_time).
        #
        # Raw view FIFO walk:
        #   order 0 takes 100 from Job A (1d late) → 100 * 2^1 = 200.
        #   order 1 takes 200 from Job B (1d late) → 200 * 2^1 = 400.
        #   orders 2 and 3 take from Job B on-time.
        #   lateness = 600.
        #
        # Safety view:
        #   week_0.due → week_0.due+1d (1d × deficit 1400)  = 1400
        #   week_0.due+1d → week_1.due (6d × deficit 1400)  = 8400
        #   week_1.due → week_1.due+1d (1d × deficit 1400)  = 1400
        #   (Job B then restores pool to safety_target.)
        #   drainage = 11200, carrying = 300 × 6 = 1800.
        rls = _make_rls_item([100, 200, 150, 300], on_hand_lbs=0)
        rls.register_jobs([_real_job(rls.item, _due(0) + timedelta(days=1), 100)])
        rls.register_jobs([_real_job(rls.item, _due(1) + timedelta(days=1), 2050)])

        self.assertEqual(
            [o.allocated_lbs for o in rls.safety_view.orders],
            [100.0, 200.0, 150.0, 300.0],
        )
        self.assertAlmostEqual(rls.raw_view.lateness, 600.0)
        self.assertAlmostEqual(rls.safety_view.drainage, 11200.0)
        self.assertAlmostEqual(rls.safety_view.carrying, 1800.0)
        self.assertEqual(rls.safety_view.excess, 0.0)


class RlsItemCostIfTests(unittest.TestCase):
    # Verifies that cost_if returns the same CostComponents that register_job
    # would produce for the same hypothetical job, across five insertion
    # positions in the existing schedule. Each test also confirms that
    # cost_if leaves the RlsItem state untouched.

    # Shared base used by tests 3.2–3.5. on_hand=100 fully covers order 0 but
    # nothing else, so the existing jobs and the hypothetical do real work in
    # the cost computations.
    _BASE_QTYS = [100, 200, 150, 300]
    _BASE_ON_HAND = 100.0

    def _fresh_rls(self) -> RlsItem:
        return _make_rls_item(self._BASE_QTYS, on_hand_lbs=self._BASE_ON_HAND)

    def _expected_components(self, all_jobs: list[Job]) -> CostComponents:
        rls = self._fresh_rls()
        rls.register_jobs(all_jobs)
        return CostComponents(
            lateness=rls.raw_view.lateness,
            drainage=rls.safety_view.drainage,
            carrying=rls.safety_view.carrying,
            excess=rls.safety_view.excess,
        )

    def _assert_cost_if_matches_baseline(
        self, existing: list[Job], hypothetical: Job,
    ) -> None:
        # Baseline: register existing + hypothetical on a fresh RlsItem.
        expected = self._expected_components(existing + [hypothetical])

        # Test: register only existing; call cost_if([hypothetical]).
        rls = self._fresh_rls()
        rls.register_jobs(existing)

        # Snapshot pre-cost_if state so we can verify cost_if is pure.
        before_raw = [o.allocated_lbs for o in rls.raw_view.orders]
        before_safety = [o.allocated_lbs for o in rls.safety_view.orders]
        before_lateness = rls.raw_view.lateness
        before_safety_pool = rls.safety_view.safety_pool
        before_drainage = rls.safety_view.drainage
        before_carrying = rls.safety_view.carrying
        before_excess = rls.safety_view.excess

        actual = rls.cost_if([hypothetical])

        # Returned components match the register-and-snapshot baseline.
        self.assertAlmostEqual(actual.lateness, expected.lateness)
        self.assertAlmostEqual(actual.drainage, expected.drainage)
        self.assertAlmostEqual(actual.carrying, expected.carrying)
        self.assertAlmostEqual(actual.excess, expected.excess)

        # State on the test RlsItem is unchanged after cost_if returns.
        self.assertEqual(
            [o.allocated_lbs for o in rls.raw_view.orders], before_raw,
        )
        self.assertEqual(
            [o.allocated_lbs for o in rls.safety_view.orders], before_safety,
        )
        self.assertEqual(rls.raw_view.lateness, before_lateness)
        self.assertEqual(rls.safety_view.safety_pool, before_safety_pool)
        self.assertEqual(rls.safety_view.drainage, before_drainage)
        self.assertEqual(rls.safety_view.carrying, before_carrying)
        self.assertEqual(rls.safety_view.excess, before_excess)

    def test_cost_if_with_no_existing_jobs(self):
        # 3.1: cost_if on a freshly built RlsItem with no register_job calls.
        item = _GREIGES['AU2958G']
        hypothetical = _real_job(item, _due(2), 500)
        self._assert_cost_if_matches_baseline(existing=[], hypothetical=hypothetical)

    def test_cost_if_before_all_existing_jobs(self):
        # 3.2: hypothetical lands before both existing jobs in the timeline.
        item = _GREIGES['AU2958G']
        existing = [
            _real_job(item, _due(1) + timedelta(days=2), 600),
            _real_job(item, _due(2) + timedelta(days=2), 400),
        ]
        hypothetical = _real_job(item, _due(0) + timedelta(days=1), 200)
        self._assert_cost_if_matches_baseline(existing, hypothetical)

    def test_cost_if_between_existing_jobs(self):
        # 3.3: hypothetical.end falls strictly between the two existing
        # jobs' end times.
        item = _GREIGES['AU2958G']
        existing = [
            _real_job(item, _due(1) + timedelta(days=2), 600),
            _real_job(item, _due(2) + timedelta(days=2), 400),
        ]
        hypothetical = _real_job(item, _due(2), 200)
        self._assert_cost_if_matches_baseline(existing, hypothetical)

    def test_cost_if_after_all_existing_jobs(self):
        # 3.4: hypothetical.end is past every existing job.
        item = _GREIGES['AU2958G']
        existing = [
            _real_job(item, _due(1) + timedelta(days=2), 600),
            _real_job(item, _due(2) + timedelta(days=2), 400),
        ]
        hypothetical = _real_job(item, _due(3) + timedelta(days=1), 200)
        self._assert_cost_if_matches_baseline(existing, hypothetical)

    def test_cost_if_same_end_time_as_existing_job(self):
        # 3.5: hypothetical.end exactly matches existing[0].end. bisect_right
        # places it after existing[0], so the spliced order should be
        # [existing[0], hypothetical, existing[1]].
        item = _GREIGES['AU2958G']
        existing = [
            _real_job(item, _due(1) + timedelta(days=2), 600),
            _real_job(item, _due(2) + timedelta(days=2), 400),
        ]
        hypothetical = _real_job(item, _due(1) + timedelta(days=2), 200)
        self._assert_cost_if_matches_baseline(existing, hypothetical)


class RlsItemBatchTests(unittest.TestCase):
    # Verifies multi-job behavior for register_jobs and cost_if. Mirrors the
    # case where plan_production emits multiple Jobs from one decision —
    # either through mid-stream beam exhaustion (multiple Jobs sharing the
    # same item) or through 'next_runout' mode's run-up.

    _BASE_QTYS = [100, 200, 150, 300]
    _BASE_ON_HAND = 100.0

    def _fresh_rls(self) -> RlsItem:
        return _make_rls_item(self._BASE_QTYS, on_hand_lbs=self._BASE_ON_HAND)

    def _components(self, rls: RlsItem) -> CostComponents:
        return CostComponents(
            lateness=rls.raw_view.lateness,
            drainage=rls.safety_view.drainage,
            carrying=rls.safety_view.carrying,
            excess=rls.safety_view.excess,
        )

    def test_register_jobs_batch_matches_per_call_state(self):
        # Registering [j1, j2] in one call must yield the same state as
        # registering j1 and j2 individually.
        item = _GREIGES['AU2958G']
        j1 = _real_job(item, _due(0) + timedelta(days=1), 100)
        j2 = _real_job(item, _due(1) + timedelta(days=1), 2050)

        rls_batch = self._fresh_rls()
        rls_batch.register_jobs([j1, j2])

        rls_per_call = self._fresh_rls()
        rls_per_call.register_jobs([j1])
        rls_per_call.register_jobs([j2])

        self.assertEqual(self._components(rls_batch),
                         self._components(rls_per_call))
        self.assertEqual(
            [o.allocated_lbs for o in rls_batch.raw_view.orders],
            [o.allocated_lbs for o in rls_per_call.raw_view.orders],
        )
        self.assertEqual(
            [o.allocated_lbs for o in rls_batch.safety_view.orders],
            [o.allocated_lbs for o in rls_per_call.safety_view.orders],
        )

    def test_register_jobs_empty_list_is_a_no_op(self):
        rls = self._fresh_rls()
        before = self._components(rls)
        before_alloc_raw = [o.allocated_lbs for o in rls.raw_view.orders]
        before_alloc_safety = [o.allocated_lbs for o in rls.safety_view.orders]

        rls.register_jobs([])

        self.assertEqual(self._components(rls), before)
        self.assertEqual([o.allocated_lbs for o in rls.raw_view.orders],
                         before_alloc_raw)
        self.assertEqual([o.allocated_lbs for o in rls.safety_view.orders],
                         before_alloc_safety)

    def test_cost_if_batch_matches_register_jobs_batch(self):
        # cost_if([j1, j2]) returns the same components as registering both
        # and reading the view trackers. Pure: state unchanged afterwards.
        item = _GREIGES['AU2958G']
        j1 = _real_job(item, _due(0) + timedelta(days=1), 100)
        j2 = _real_job(item, _due(1) + timedelta(days=1), 2050)

        baseline_rls = self._fresh_rls()
        baseline_rls.register_jobs([j1, j2])
        expected = self._components(baseline_rls)

        rls = self._fresh_rls()
        before = self._components(rls)
        actual = rls.cost_if([j1, j2])

        self.assertEqual(actual, expected)
        # State unchanged after cost_if.
        self.assertEqual(self._components(rls), before)

    def test_cost_if_batch_is_order_independent(self):
        # Batch order should not affect the result — register_jobs sorts by
        # job.end internally.
        item = _GREIGES['AU2958G']
        j1 = _real_job(item, _due(0) + timedelta(days=1), 100)
        j2 = _real_job(item, _due(1) + timedelta(days=1), 2050)

        rls = self._fresh_rls()
        self.assertEqual(rls.cost_if([j1, j2]), rls.cost_if([j2, j1]))

    def test_cost_if_empty_list_returns_current_state_cost(self):
        # cost_if([]) acts as a "what is current cost" query.
        item = _GREIGES['AU2958G']
        rls = self._fresh_rls()
        rls.register_jobs([_real_job(item, _due(2) + timedelta(days=1), 350)])

        before = self._components(rls)
        empty_cost = rls.cost_if([])

        self.assertEqual(empty_cost, before)
        # State remains unchanged.
        self.assertEqual(self._components(rls), before)


if __name__ == '__main__':
    unittest.main()
