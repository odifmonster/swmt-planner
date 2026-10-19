#!/usr/bin/env python

"""Tests for `planners/retime` — see tests/spec-files/RETIME_TEST_SPEC.md."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from swmtplanner.schedule import Hanging, Knit, TapeOut
from swmtplanner.planners.infinite.schedule_json import PLANT_TZ
from swmtplanner.planners.retime import (
    Ticket, PriorJob, Position, HangRecord, RetimeResult,
    read_tickets, prior_jobs, locate, retime,
)
from swmtplanner.planners.retime.retime import retime_text, write_outputs


# --- Fixtures -----------------------------------------------------------

_T0 = datetime(2026, 5, 17, 0, 0)          # the prior plan's start (a Sunday)
_START = datetime(2026, 5, 18, 0, 0)       # the new status (the next day)


def _h(hours: float, base: datetime = _T0) -> datetime:
    return base + timedelta(hours=hours)


def _utc(local: datetime) -> str:
    """A plant-local time as the schedule JSON writes it (UTC with offset)."""
    return local.replace(tzinfo=PLANT_TZ).astimezone(timezone.utc).isoformat()


def _offset(local: datetime) -> str:
    """A plant-local time as the doffed-rolls file writes it (with offset)."""
    return local.replace(tzinfo=PLANT_TZ).isoformat()


def _tk(ticket: str, time: datetime, item: str | None, machine: str = 'M1',
        style: str | None = None) -> Ticket:
    return Ticket(ticket, machine, time, style or (item or '?'), item)


def _pj(i: int, item: str, order: str | None, rolls: int,
        start: datetime = _T0, top=(), btm=()) -> PriorJob:
    return PriorJob(f'J{i}', item, order, rolls, start, tuple(top), tuple(btm))


def _plan_job(job_id: str, item: str, order: str | None, rolls: int,
              start: datetime, top=(), btm=()) -> dict:
    """A schedule-JSON job dict: `rolls` rolls, one Hanging per named set
    (a `None` name becomes a NEW set)."""
    acts = []
    t = start
    for bar, names in (('top', top), ('btm', btm)):
        for n in names:
            acts.append({'kind': 'Hanging', 'id': f'H{len(acts)}', 'start': _utc(t),
                         'end': _utc(t + timedelta(hours=1)), 'bars': bar,
                         'top_beam': {'set_no': n or 'NEW000001'} if bar == 'top' else None,
                         'btm_beam': {'set_no': n or 'NEW000002'} if bar == 'btm' else None})
            t += timedelta(hours=1)
    return {'kind': 'job', 'id': job_id, 'item': item, 'tgt_order': order,
            'start': _utc(start), 'end': _utc(start + timedelta(hours=rolls)),
            'rolls': [{'id': f'{job_id}-R{k + 1}'} for k in range(rolls)],
            'activities': acts}


_WEIGHTS = {k: 0.0 for k in (
    'lateness', 'priority', 'drainage', 'carrying', 'excess', 'tape_out_single',
    'tape_out_both', 'style_change', 'runner_change', 'pattern_change',
    'idle_time', 'waste_lbs', 'level_loading', 'old_machine', 'recovery')}


def _style(sid: str, top: str, machines=('M1', 'M2', 'M3')) -> dict:
    return {'id': sid, 'pattern': 'A', 'tgt_wt': 100.0, 'safety': 0.0,
            'beam_cfg': {'top': {'beamset': top, 'pct': 50},
                         'btm': {'beamset': '75D WHT TX 1172X4', 'pct': 50}},
            'machine_rates': [{'id': m, 'rate': 100.0} for m in machines]}


_STYLES = [
    _style('A', '40D BLK 1172X4 S/L'),
    _style('B', '40D WHT 1172X4 S/L'),
    _style('C', '40D GRY 1172X4 S/L'),
    _style('D', '40D BLK 1172X4 S/L', machines=('M9',)),
]


def _set(set_no: str, received: str = '2026-05-01 00:00:00', lbs: float = 2000.0) -> dict:
    """A stock set for B's top bar (`40D WHT 1172X4`)."""
    return {'set_no': set_no, 'merge': 'MW', 'vendor': 'V', 'lbs': lbs,
            'beams': 4, 'ends': 1172, 'denier': 40, 'luster': 'SD',
            'desc': 'POLY', 'received': received}


def _machine(mid: str, item: str) -> dict:
    return {'id': mid, 'is_new': True, 'init_item': item,
            'init_top_lbs': 2800.0, 'init_btm_lbs': 1800.0, 'init_roll_lbs': 0.0}


class _Bundle:
    """A temporary run-config directory with a prior plan and a tickets
    file: `retime()` is run on it."""

    def __init__(self, machines, prior, tickets=None, beam_sets=(),
                 start=_START, change=None, assigned_sets=None):
        self.dir = tempfile.TemporaryDirectory()
        d = Path(self.dir.name)
        (d / 'variant-map.json').write_text(json.dumps({'merges': {}, 'masters': {}}))
        cfg = {
            'start_date': start.strftime('%Y-%m-%d %H:%M:%S'),
            'change_date': (change or start).strftime('%Y-%m-%d %H:%M:%S'),
            'mode': 'exact', 'products': _STYLES,
            'workcal': {'work_days': [0, 1, 2, 3, 4, 5, 6], 'day_start': 0,
                        'day_end': 24, 'holidays': []},
            'machines': machines,
            'demand': [{'item_id': s['id'], 'on_hand': 0.0, 'lead_time_days': 7,
                        'weekly_dmnd': [0.0, 0.0, 0.0, 0.0]} for s in _STYLES],
            'weights': _WEIGHTS,
            'variant_masters': {'A-V': 'A', 'B-V': 'B'},
            'variant_map': 'variant-map.json',
            'beam_sets': list(beam_sets),
        }
        if assigned_sets is not None:
            cfg['assigned_sets'] = list(assigned_sets)
        (d / 'master.json').write_text(json.dumps(cfg))
        (d / 'prior.json').write_text(json.dumps(prior))
        (d / 'tickets.json').write_text(json.dumps(tickets or {}))
        self.config = d / 'master.json'
        self.prior = d / 'prior.json'
        self.tickets = d / 'tickets.json'

    def run(self) -> RetimeResult:
        return retime(self.config, self.prior, self.tickets)

    def close(self):
        self.dir.cleanup()


def _roll(machine: str, n: int, time: datetime, style: str) -> dict:
    return {'ticket_no': f'{machine}-{n}', 'style': style, 'lbs': 100.0,
            'doff_ts': _offset(time)}


def _hangs(result: RetimeResult, machine: str, bar: str) -> list[str]:
    """Set numbers hung on `bar` of `machine` in the retimed schedule."""
    return [getattr(a, f'{bar}_beam').set_no for a in result.report.schedules[machine]
            if isinstance(a, Hanging) and getattr(a, f'{bar}_beam') is not None]


# --- 1. read_tickets ------------------------------------------------------

class ReadTicketsTests(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.n = 0

    def tearDown(self):
        self.dir.cleanup()

    def _write(self, data) -> Path:
        self.n += 1
        p = Path(self.dir.name) / f'rolls{self.n}.json'
        p.write_text(json.dumps(data))
        return p

    def test_grouping_and_order(self):
        p = self._write({
            'N03': [_roll('N03', 2, _h(5), 'A-V'), _roll('N03', 1, _h(1), 'A-V')],
            '02': [_roll('02', 1, _h(3), 'B')],
        })
        tix, ignored = read_tickets(p, ['N3', 'O2'], {'A-V': 'A'}, ['A', 'B'])
        self.assertEqual(ignored, 0)
        self.assertEqual([t.ticket for t in tix['N3']], ['N03-1', 'N03-2'])
        self.assertEqual([t.time for t in tix['N3']], [_h(1), _h(5)])
        self.assertEqual([t.machine for t in tix['O2']], ['O2'])
        # a flat list groups by the ticket prefix the same way
        p2 = self._write([_roll('N03', 2, _h(5), 'A-V'), _roll('02', 1, _h(3), 'B'),
                          _roll('N03', 1, _h(1), 'A-V')])
        tix2, _ = read_tickets(p2, ['N3', 'O2'], {'A-V': 'A'}, ['A', 'B'])
        self.assertEqual([t.ticket for t in tix2['N3']], ['N03-1', 'N03-2'])
        self.assertEqual(len(tix2['O2']), 1)

    def test_other_machines_dropped_and_counted(self):
        p = self._write({'X9': [_roll('X9', 1, _h(1), 'A'), _roll('X9', 2, _h(2), 'A')],
                         'M1': [_roll('M1', 1, _h(1), 'A')], 'M2': [], 'M3': None})
        tix, ignored = read_tickets(p, ['M1', 'M2', 'M3'], None, ['A'])
        self.assertEqual(ignored, 2)
        self.assertEqual(len(tix['M1']), 1)
        self.assertEqual(tix['M2'], [])
        self.assertEqual(tix['M3'], [])
        p2 = self._write([_roll('X9', 1, _h(1), 'A')])
        _, ignored2 = read_tickets(p2, ['M1'], None, ['A'])
        self.assertEqual(ignored2, 1)

    def test_style_resolution(self):
        p = self._write({'M1': [_roll('M1', 1, _h(1), 'A-V'), _roll('M1', 2, _h(2), 'B'),
                                _roll('M1', 3, _h(3), 'ZZZ')]})
        tix, _ = read_tickets(p, ['M1'], {'A-V': 'A'}, ['A', 'B'])
        self.assertEqual([(t.style, t.item) for t in tix['M1']],
                         [('A-V', 'A'), ('B', 'B'), ('ZZZ', None)])

    def test_loose_keys_and_errors(self):
        p = self._write({'M1': [{'ticket': 'M1-7', 'ts': '2026-05-17 04:00:00',
                                 'item': 'A', 'lbs': 123.4}]})
        tix, _ = read_tickets(p, ['M1'], None, ['A'])
        self.assertEqual((tix['M1'][0].ticket, tix['M1'][0].time, tix['M1'][0].item),
                         ('M1-7', _h(4), 'A'))
        for bad in ({'M1': [{'style': 'A', 'doff_ts': '2026-05-17 04:00:00'}]},
                    {'M1': [{'ticket_no': 'M1-1', 'style': 'A'}]},
                    {'M1': [{'ticket_no': 'M1-1', 'doff_ts': '2026-05-17 04:00:00'}]},
                    'not a list'):
            with self.assertRaises(ValueError):
                read_tickets(self._write(bad), ['M1'], None, ['A'])

    def test_times_are_plant_local(self):
        p = self._write({'M1': [_roll('M1', 1, _h(12), 'A'),
                                {'ticket_no': 'M1-2', 'style': 'A',
                                 'doff_ts': '2026-05-17 13:00:00'}]})
        tix, _ = read_tickets(p, ['M1'], None, ['A'])
        self.assertEqual([t.time for t in tix['M1']], [_h(12), _h(13)])


# --- 2. prior_jobs --------------------------------------------------------

class PriorJobsTests(unittest.TestCase):

    def test_jobs_in_order(self):
        plan = [{'id': 'M1', 'schedule': [
            _plan_job('J2', 'B', 'P1@B', 1, _h(5)),
            {'kind': 'Idle', 'id': 'I1', 'start': _utc(_h(4)), 'end': _utc(_h(5))},
            _plan_job('J1', 'A', 'P1@A', 2, _h(0)),
        ]}]
        jobs = prior_jobs(plan, ['M1'])['M1']
        self.assertEqual([(j.job_id, j.item, j.order, j.rolls, j.start) for j in jobs],
                         [('J1', 'A', 'P1@A', 2, _h(0)), ('J2', 'B', 'P1@B', 1, _h(5))])

    def test_hang_sets_per_bar(self):
        job = _plan_job('J1', 'B', None, 1, _h(0))
        job['activities'] = [
            {'kind': 'Hanging', 'id': 'H1', 'start': _utc(_h(0)), 'end': _utc(_h(1)),
             'bars': 'both', 'top_beam': {'set_no': 's1'}, 'btm_beam': {'set_no': 's2'}},
            {'kind': 'Threading', 'id': 'T1', 'start': _utc(_h(1)), 'end': _utc(_h(2)),
             'bars': 'both'},
            {'kind': 'Hanging', 'id': 'H2', 'start': _utc(_h(3)), 'end': _utc(_h(4)),
             'bars': 'top', 'top_beam': {'set_no': 'NEW000009'}, 'btm_beam': None},
        ]
        j = prior_jobs([{'id': 'M1', 'schedule': [job]}], ['M1'])['M1'][0]
        self.assertEqual(j.top, ('s1', None))
        self.assertEqual(j.btm, ('s2',))

    def test_machines(self):
        plan = [{'id': 'M01', 'schedule': [_plan_job('J1', 'A', None, 1, _h(0))]},
                {'id': 'X9', 'schedule': [_plan_job('J1', 'A', None, 1, _h(0))]}]
        jobs = prior_jobs(plan, ['M1', 'M2'])
        self.assertEqual(sorted(jobs), ['M1', 'M2'])
        self.assertEqual(len(jobs['M1']), 1)
        self.assertEqual(jobs['M2'], [])


# --- 3. locate ------------------------------------------------------------

_JOBS = [_pj(1, 'A', 'P1@A', 2), _pj(2, 'B', 'P1@B', 2), _pj(3, 'A', 'P2@A', 1)]


def _locate(tickets, status_item='A', run_up=0, in_progress=False, jobs=_JOBS):
    return locate('M1', jobs, tickets, _T0, _START, status_item, run_up, in_progress)


def _left(pos: Position) -> list[tuple[str, int]]:
    return [(j.item, j.rolls) for j in pos.remaining]


class LocateTests(unittest.TestCase):

    def test_no_tickets_no_run_up(self):
        p = _locate([])
        self.assertEqual((p.consumed, p.tickets), (0, 0))
        self.assertEqual(_left(p), [('A', 2), ('B', 2), ('A', 1)])
        self.assertTrue(p.replayable)
        self.assertEqual((p.extra, p.early, p.wrong_style, p.finished), ([], [], None, False))

    def test_tickets_consume_in_order(self):
        p = _locate([_tk('M1-1', _h(1), 'A'), _tk('M1-2', _h(2), 'A'), _tk('M1-3', _h(3), 'B')],
                    status_item='B')
        self.assertEqual((p.consumed, p.tickets), (3, 3))
        self.assertEqual(_left(p), [('B', 1), ('A', 1)])
        second = p.remaining[0]
        self.assertEqual((second.job_id, second.order, second.start), ('J2', 'P1@B', _T0))

    def test_tickets_before_the_prior_start(self):
        p = _locate([_tk('M1-0', _T0 - timedelta(hours=1), 'B'), _tk('M1-1', _h(1), 'A')])
        self.assertEqual((p.consumed, p.tickets), (1, 1))

    def test_tickets_after_the_status(self):
        p = _locate([_tk('M1-1', _h(1), 'A'), _tk('M1-2', _START + timedelta(hours=1), 'A')])
        self.assertEqual((p.consumed, p.tickets, p.after_status), (1, 1, 1))

    def test_extra_roll_of_the_style_just_finished(self):
        p = _locate([_tk('M1-1', _h(1), 'A'), _tk('M1-2', _h(2), 'A'),
                     _tk('M1-3', _h(3), 'A'), _tk('M1-4', _h(4), 'B')], status_item='B')
        self.assertEqual(p.extra, ['M1-3'])
        self.assertEqual(p.consumed, 3)
        self.assertEqual(_left(p), [('B', 1), ('A', 1)])
        self.assertIsNone(p.wrong_style)

    def test_wrong_style_stops_the_walk(self):
        p = _locate([_tk('M1-1', _h(1), 'A'), _tk('M1-2', _h(2), 'C', style='C-X'),
                     _tk('M1-3', _h(3), 'A')])
        self.assertIn('M1-2', p.wrong_style)
        self.assertIn('C-X', p.wrong_style)
        self.assertIn('A', p.wrong_style)
        self.assertEqual((p.consumed, p.tickets), (1, 2))
        self.assertEqual(p.remaining, [])
        self.assertFalse(p.replayable)

    def test_unresolved_style_is_wrong(self):
        p = _locate([_tk('M1-1', _h(1), None, style='ZZZ')])
        self.assertIsNotNone(p.wrong_style)
        self.assertIn('ZZZ', p.wrong_style)

    def test_early_change_by_ticket(self):
        p = _locate([_tk('M1-1', _h(1), 'A'), _tk('M1-2', _h(2), 'B')], status_item='B')
        self.assertIsNone(p.wrong_style)
        self.assertEqual(len(p.early), 1)
        for word in ('1 roll', 'A', 'P1@A', 'M1-2'):
            self.assertIn(word, p.early[0])
        self.assertEqual(p.consumed, 3)
        self.assertEqual(_left(p), [('B', 1), ('A', 1)])
        # two jobs ahead is a wrong style, not an early change
        four = [_pj(1, 'A', 'P1@A', 2), _pj(2, 'B', 'P1@B', 1), _pj(3, 'C', 'P1@C', 1),
                _pj(4, 'A', 'P2@A', 1)]
        p2 = _locate([_tk('M1-1', _h(1), 'A'), _tk('M1-2', _h(2), 'C')], jobs=four,
                     status_item='C')
        self.assertIsNotNone(p2.wrong_style)
        self.assertEqual(p2.early, [])

    def test_early_change_per_the_status(self):
        p = _locate([], status_item='B', run_up=1, in_progress=True)
        self.assertIsNone(p.wrong_style)
        self.assertEqual(len(p.early), 1)
        self.assertIn('per the status', p.early[0])
        self.assertIn('2 roll', p.early[0])
        self.assertEqual(p.consumed, 3)         # the two A rolls dropped, one B by the run-up
        self.assertEqual(_left(p), [('B', 1), ('A', 1)])
        self.assertTrue(p.replayable)
        four = [_pj(1, 'A', 'P1@A', 2), _pj(2, 'B', 'P1@B', 1), _pj(3, 'C', 'P1@C', 1)]
        self.assertIsNotNone(_locate([], status_item='C', jobs=four).wrong_style)

    def test_status_must_match(self):
        p = _locate([], status_item='C')
        self.assertIsNotNone(p.wrong_style)
        self.assertIn('status says C', p.wrong_style)
        self.assertFalse(p.replayable)

    def test_run_up_rolls_consume(self):
        p = _locate([], run_up=2, in_progress=True)
        self.assertEqual((p.consumed, p.run_up_rolls), (2, 2))
        self.assertEqual(p.in_progress_order, 'P1@A')
        self.assertEqual(_left(p), [('B', 2), ('A', 1)])
        self.assertIsNone(_locate([], run_up=1, in_progress=False).in_progress_order)

    def test_run_up_overrunning_the_style(self):
        p = _locate([], run_up=3, in_progress=True)
        self.assertEqual(p.consumed, 2)
        self.assertFalse(p.finished)
        self.assertEqual(_left(p), [('B', 2), ('A', 1)])

    def test_extra_roll_in_progress(self):
        two_a = [_tk('M1-1', _h(1), 'A'), _tk('M1-2', _h(2), 'A')]
        p = _locate(two_a, status_item='A', run_up=1, in_progress=True)
        self.assertTrue(p.extra_in_progress)
        self.assertEqual(p.consumed, 2)
        self.assertEqual(_left(p), [('B', 2), ('A', 1)])
        self.assertEqual(p.extra, [])
        p2 = _locate(two_a, status_item='A', run_up=2, in_progress=True)
        self.assertEqual(len(p2.extra), 1)
        self.assertIn('run-up', p2.extra[0])

    def test_finished(self):
        tix = [_tk(f'M1-{n}', _h(n), it) for n, it in enumerate(['A', 'A', 'B', 'B', 'A'], 1)]
        p = _locate(tix, status_item='Q')
        self.assertTrue(p.finished)
        self.assertEqual(p.remaining, [])
        self.assertFalse(p.replayable)
        self.assertIsNone(p.wrong_style)

    def test_remaining_jobs_keep_identity(self):
        jobs = [_pj(1, 'A', 'P1@A', 3, _h(2), top=('s1',), btm=('s2', None))]
        p = _locate([_tk('M1-1', _h(1), 'A')], jobs=jobs)
        j = p.remaining[0]
        self.assertEqual((j.job_id, j.order, j.start, j.top, j.btm, j.rolls),
                         ('J1', 'P1@A', _h(2), ('s1',), ('s2', None), 2))


# --- 4. retime: steps and replay --------------------------------------------

def _prior(m1_jobs, m2_jobs=None) -> list[dict]:
    plan = [{'id': 'M1', 'schedule': m1_jobs}]
    if m2_jobs is not None:
        plan.append({'id': 'M2', 'schedule': m2_jobs})
    return plan


_M1_JOBS = [_plan_job('J1', 'A', 'P1@A', 2, _h(0)), _plan_job('J2', 'B', 'P1@B', 1, _h(3))]
_M2_JOBS = [_plan_job('J3', 'B', 'P1@B2', 2, _h(0))]
_TWO = [_machine('M1', 'A'), _machine('M2', 'B')]


class RetimeTests(unittest.TestCase):

    def tearDown(self):
        if hasattr(self, 'b'):
            self.b.close()

    def _run(self, **kw) -> RetimeResult:
        self.b = _Bundle(**kw)
        return self.b.run()

    def test_same_sequence_new_times(self):
        r = self._run(machines=_TWO, prior=_prior(_M1_JOBS, _M2_JOBS))
        self.assertEqual(r.steps, [('M1', 'A', 2, 'P1@A'), ('M2', 'B', 2, 'P1@B2'),
                                   ('M1', 'B', 1, 'P1@B')])
        self.assertEqual(r.failures, [])
        a_jobs = [j for j in r.report.jobs_by_item['A']]
        self.assertEqual([(j.total_rolls, j.tgt_order) for j in a_jobs], [(2, 'P1@A')])
        b_jobs = sorted(((j.total_rolls, j.tgt_order) for j in r.report.jobs_by_item['B']))
        self.assertEqual(b_jobs, [(1, 'P1@B'), (2, 'P1@B2')])
        for acts in r.report.schedules.values():
            for a in acts:
                self.assertGreaterEqual(a.start, _START)
        # with a later change date the load's run-up consumes A rolls
        self.b.close()
        r2 = self._run(machines=_TWO, prior=_prior(_M1_JOBS, _M2_JOBS),
                       change=_START + timedelta(hours=2))
        self.assertEqual(r2.positions['M1'].run_up_rolls, 2)
        self.assertEqual(r2.positions['M1'].consumed, 2)
        # M2's run-up ran both of its B rolls: it finished its plan
        self.assertTrue(r2.positions['M2'].finished)
        self.assertEqual(r2.steps, [('M1', 'B', 1, 'P1@B')])

    def test_tickets_shorten_the_first_job(self):
        r = self._run(machines=_TWO, prior=_prior(_M1_JOBS, _M2_JOBS),
                      tickets={'M1': [_roll('M1', 1, _h(1), 'A-V')]})
        self.assertEqual(r.steps[0], ('M1', 'A', 1, 'P1@A'))
        self.assertEqual((r.positions['M1'].tickets, r.positions['M1'].consumed), (1, 1))

    def test_wrong_style_machine_left_alone(self):
        r = self._run(machines=_TWO, prior=_prior(_M1_JOBS, _M2_JOBS),
                      tickets={'M2': [_roll('M2', 1, _h(1), 'C')]})
        self.assertIsNotNone(r.positions['M2'].wrong_style)
        self.assertEqual([s for s in r.steps if s[0] == 'M2'], [])
        self.assertEqual(r.report.schedules['M2'], ())
        self.assertEqual([s[0] for s in r.steps], ['M1', 'M1'])

    def test_sets_go_to_the_earliest_hang(self):
        both_a = [_machine('M1', 'A'), _machine('M2', 'A')]
        prior = _prior(
            [_plan_job('J0', 'A', None, 3, _h(0)),
             _plan_job('J1', 'B', 'P1@B', 1, _h(1), top=('S1',))],
            [_plan_job('J9', 'A', None, 1, _h(0)),
             _plan_job('J2', 'B', 'P2@B', 1, _h(2), top=(None,))])
        r = self._run(machines=both_a, prior=prior, beam_sets=[_set('S1')])
        # M1's B step is staged first, but M2's B hang comes first in time
        self.assertEqual(_hangs(r, 'M2', 'top'), ['S1'])
        self.assertTrue(_hangs(r, 'M1', 'top')[0].startswith('NEW'))
        m2 = next(h for h in r.hangs if h.machine == 'M2' and h.bar == 'top')
        m1 = next(h for h in r.hangs if h.machine == 'M1' and h.bar == 'top')
        self.assertEqual((m2.hung, m2.source, m2.prior), ('S1', 'stock', None))
        self.assertEqual((m1.source, m1.prior), ('new', 'S1'))
        self.assertTrue(m1.hung.startswith('NEW'))
        self.assertLess(m2.at, m1.at)
        self.assertEqual(r.hangs, sorted(r.hangs, key=lambda h: (h.at, h.machine, h.bar)))

    def test_retimed_on_the_real_pounds(self):
        # B's top draws 50 lbs a roll (100-lb rolls, top_pct 0.5): an 80-lb
        # set gives one roll above the floor, so the two-roll job hangs again.
        jobs = [_plan_job('J1', 'A', 'P1@A', 1, _h(0)),
                _plan_job('J2', 'B', 'P1@B', 2, _h(2), top=(None,))]
        r = self._run(machines=_TWO[:1], prior=_prior(jobs), beam_sets=[_set('S1', lbs=80.0)])
        hang = next(a for a in r.report.schedules['M1']
                    if isinstance(a, Hanging) and a.top_beam is not None)
        self.assertEqual((hang.top_beam.set_no, hang.top_beam.lbs), ('S1', 80.0))
        tops = [x for x in r.hangs if x.machine == 'M1' and x.bar == 'top']
        self.assertEqual([(h.hung, h.source, h.plan_lbs, h.set_lbs, h.short_by, h.rolls) for h in tops][:1],
                         [('S1', 'stock', 80.0, 80.0, 0.0, 1)])
        self.assertEqual(len(tops), 2)                        # the second roll needs another set
        self.assertEqual((tops[1].source, tops[1].rolls), ('new', 1))
        self.assertGreaterEqual(r.rounds, 2)
        self.b.close()
        r2 = self._run(machines=_TWO[:1], prior=_prior(jobs), beam_sets=[_set('S1')])
        tops2 = [x for x in r2.hangs if x.machine == 'M1' and x.bar == 'top']
        self.assertEqual([(h.hung, h.set_lbs, h.short_by, h.rolls) for h in tops2],
                         [('S1', 2000.0, 0.0, 2)])
        self.assertEqual(r2.withheld, [])

    def test_rounds_stop_when_nothing_more_is_assigned(self):
        jobs = [_plan_job('J1', 'A', 'P1@A', 1, _h(0)),
                _plan_job('J2', 'B', 'P1@B', 2, _h(2), top=(None,))]
        r = self._run(machines=_TWO[:1], prior=_prior(jobs), beam_sets=[_set('S1')])
        self.assertEqual(r.rounds, 2)                          # assigned once, confirmed once
        self.b.close()
        r0 = self._run(machines=_TWO[:1], prior=_prior(jobs), beam_sets=[])
        self.assertEqual(r0.rounds, 1)                         # nothing to assign
        self.assertTrue(all(h.source == 'new' for h in r0.hangs))

    def test_taped_out_set_comes_back_in_time_order(self):
        both_a = [_machine('M1', 'A'), _machine('M2', 'A')]
        prior = _prior(
            [_plan_job('J0', 'A', None, 1, _h(0)),
             _plan_job('J1', 'B', 'P1@B', 1, _h(1), top=(None,)),
             _plan_job('J3', 'A', 'P2@A', 1, _h(2))],
            [_plan_job('J9', 'A', None, 6, _h(0)),
             _plan_job('J2', 'B', 'P2@B', 1, _h(5), top=(None,))])
        r = self._run(machines=both_a, prior=prior, beam_sets=[_set('S1')])
        self.assertEqual(_hangs(r, 'M1', 'top')[0], 'S1')
        self.assertEqual(_hangs(r, 'M2', 'top'), ['S1'])
        tapes = [a.top_beam.set_no for a in r.report.schedules['M1']
                 if isinstance(a, TapeOut) and a.top_beam is not None]
        self.assertIn('S1', tapes)                      # the B set's tape-out carries it
        m2 = next(h for h in r.hangs if h.machine == 'M2' and h.bar == 'top')
        self.assertAlmostEqual(m2.set_lbs, 1950.0)

    def test_knits_carry_their_sets(self):
        jobs = [_plan_job('J1', 'A', 'P1@A', 1, _h(0)),
                _plan_job('J2', 'B', 'P1@B', 1, _h(2), top=(None,))]
        r = self._run(machines=_TWO[:1], prior=_prior(jobs), beam_sets=[_set('S1')])
        knits = [a for a in r.report.schedules['M1'] if isinstance(a, Knit)]
        self.assertTrue(knits)
        self.assertTrue(all(k.top_beam is not None and k.btm_beam is not None for k in knits))
        self.assertEqual([k.top_beam.set_no for k in knits if k.item.id == 'B'], ['S1'])
        with tempfile.TemporaryDirectory() as d:
            _xlsx, js, _txt = write_outputs(r, Path(d), r.start_date)
            data = json.loads(js.read_text())
            m1 = next(m for m in data if m['id'] == 'M1')
            knit_objs = [a for j in m1['schedule'] if j.get('kind') == 'job'
                         for a in j['activities'] if a.get('kind') == 'Knit']
            self.assertTrue(knit_objs)
            self.assertIn('S1', {a['top_beam']['set_no'] for a in knit_objs})

    def test_failed_step_stops_its_machine(self):
        jobs = [_plan_job('J0', 'A', 'P1@A', 1, _h(0)), _plan_job('J1', 'D', 'P1@D', 1, _h(2)),
                _plan_job('J2', 'B', 'P1@B', 1, _h(4))]
        r = self._run(machines=_TWO, prior=_prior(jobs, _M2_JOBS))
        self.assertEqual(len(r.failures), 1)
        self.assertIn('M1', r.failures[0])
        self.assertIn('D', r.failures[0])
        # M1's A step replayed, its D step failed, its B step was skipped
        self.assertEqual(r.steps, [('M1', 'A', 1, 'P1@A'), ('M2', 'B', 2, 'P1@B2')])

    def test_machines_not_in_the_prior_plan(self):
        r = self._run(machines=_TWO + [_machine('M3', 'A')], prior=_prior(_M1_JOBS, _M2_JOBS))
        self.assertEqual(r.not_in_plan, ['M3'])
        self.assertEqual([s for s in r.steps if s[0] == 'M3'], [])

    def test_tickets_of_other_machines(self):
        r = self._run(machines=_TWO, prior=_prior(_M1_JOBS, _M2_JOBS),
                      tickets={'X9': [_roll('X9', 1, _h(1), 'A')]})
        self.assertEqual(r.tickets_ignored, 1)
        self.assertEqual(r.steps, [('M1', 'A', 2, 'P1@A'), ('M2', 'B', 2, 'P1@B2'),
                                   ('M1', 'B', 1, 'P1@B')])

    def test_report_is_the_states(self):
        r = self._run(machines=_TWO, prior=_prior(_M1_JOBS, _M2_JOBS))
        self.assertEqual(r.start_date, _START)
        self.assertTrue(r.report.jobs_by_item['A'])
        self.assertEqual(r.report.late_orders, ())
        self.assertEqual(r.report.unmet_lbs_by_item_week, {})


# --- 5. retime_text and write_outputs ---------------------------------------

def _result(positions, hangs=(), steps=(), failures=(), ignored=0, not_in_plan=()):
    return RetimeResult(report=None, start_date=_START, positions=positions,
                        steps=list(steps), hangs=list(hangs),
                        failures=list(failures), tickets_ignored=ignored,
                        not_in_plan=list(not_in_plan))


class RetimeTextTests(unittest.TestCase):

    def test_sections(self):
        text = retime_text(_result({'M1': Position('M1', 'A', remaining=[_pj(1, 'A', 'P1@A', 2)])},
                                   ignored=3))
        for head in ('POSITIONS', 'DEVIATIONS', 'SET ASSIGNMENTS', 'STILL INVENTED',
                     'ASSIGNED SETS PASSED OVER', 'STEPS REPLAYED', 'FAILURES'):
            self.assertIn(head, text)
        self.assertIn('ignored: 3', text)
        self.assertIn('M1   on A', text)
        self.assertEqual(text.count('\nnone\n'), 4)

    def test_deviations_spelled_out(self):
        positions = {
            'M1': Position('M1', 'C', wrong_style='the status says C; the plan expected A'),
            'M2': Position('M2', 'A', extra=['M2-9'], remaining=[_pj(1, 'B', None, 1)]),
            'M3': Position('M3', 'A', extra_in_progress=True, remaining=[_pj(1, 'B', None, 1)]),
            'M4': Position('M4', 'B', early=['2 roll(s) of A (P1@A) dropped: changed early per the status'],
                           remaining=[_pj(1, 'B', None, 1)]),
            'M5': Position('M5', 'A', finished=True),
            'M6': Position('M6', 'A', in_progress_order='P7@A', remaining=[_pj(1, 'A', None, 1)]),
        }
        text = retime_text(_result(positions))
        self.assertIn('M1: on a style the plan never put there', text)
        self.assertIn('M2: extra roll of the previous style: M2-9', text)
        self.assertIn('M3: an extra roll of A in progress', text)
        self.assertIn('M4: 2 roll(s) of A (P1@A) dropped', text)
        self.assertIn('M5: the floor finished everything', text)
        self.assertIn('M6: the roll in progress was for P7@A', text)
        self.assertIn('WRONG STYLE', text)

    def test_assignments_and_still_invented(self):
        hangs = [HangRecord('M1', 'top', _START, '40D BLK 1172X4', 'NEW000003', 'new',
                            2800.0, None, 0.0, None),
                 HangRecord('M1', 'btm', _START, '75D WHT TX 1172X4', 'S1', 'stock',
                            1800.0, 1500.0, 30.0, 'S9')]
        text = retime_text(_result({'M1': Position('M1', 'A', remaining=[_pj(1, 'A', None, 1)])},
                                   hangs=hangs))
        block = text.split('SET ASSIGNMENTS')[1].split('STILL INVENTED')[0]
        self.assertIn('hung S1', block)
        self.assertIn('1500 / 1800 lbs', block)
        self.assertIn('SHORT BY 30 lbs', block)
        self.assertIn('prior S9', block)
        self.assertNotIn('NEW000003', block)
        self.assertIn('1 hang(s)', text)
        self.assertIn('NEW000003', text.split('STILL INVENTED')[1])

    def test_files(self):
        b = _Bundle(machines=_TWO, prior=_prior(_M1_JOBS, _M2_JOBS))
        try:
            r = b.run()
            with tempfile.TemporaryDirectory() as d:
                out = Path(d)
                xlsx, js, txt = write_outputs(r, out, r.start_date)
                self.assertEqual([p.name for p in (xlsx, js, txt)],
                                 ['knit_plan_20260518.xlsx', 'knit_plan_20260518.json',
                                  'retime_20260518.txt'])
                self.assertTrue(all(p.exists() for p in (xlsx, js, txt)))
                plan = json.loads(js.read_text())
                self.assertIsInstance(plan, list)
                self.assertIn('M1', {m['id'] for m in plan})
                xlsx2, _, txt2 = write_outputs(r, out, r.start_date)
                self.assertEqual((xlsx2.name, txt2.name),
                                 ('knit_plan_20260518_2.xlsx', 'retime_20260518_2.txt'))
        finally:
            b.close()


if __name__ == '__main__':
    unittest.main()


# --- 4.12 / 4.13 keep_sets and placeholders --------------------------------

from types import SimpleNamespace as _NS
from swmtplanner.schedule import PassedOver as _PassedOver
from swmtplanner.products import BeamSet as _BeamSet, BeamSetDesc as _BeamSetDesc


def _note(r, machine, bar='top'):
    return next(h for h in r.hangs if h.machine == machine and h.bar == bar)


class KeepSetsTests(unittest.TestCase):

    def tearDown(self):
        if hasattr(self, 'b'):
            self.b.close()

    def _run(self, keep=True, **kw) -> RetimeResult:
        self.b = _Bundle(**kw)
        return retime(self.b.config, self.b.prior, self.b.tickets, keep_sets=keep)

    _BOTH_A = [_machine('M1', 'A'), _machine('M2', 'A')]

    def _prior(self, m1_top=('S1',), m2_top=(None,)):
        return _prior([_plan_job('J0', 'A', None, 3, _h(0)),
                       _plan_job('J1', 'B', 'P1@B', 1, _h(1), top=m1_top)],
                      [_plan_job('J9', 'A', None, 1, _h(0)),
                       _plan_job('J2', 'B', 'P2@B', 1, _h(2), top=m2_top)])

    def test_keeps_the_prior_set(self):
        r = self._run(machines=self._BOTH_A, prior=self._prior(), beam_sets=[_set('S1'), _set('S2')])
        self.assertEqual(_hangs(r, 'M1', 'top'), ['S1'])
        self.assertEqual(_hangs(r, 'M2', 'top'), ['S2'])
        m1, m2 = _note(r, 'M1'), _note(r, 'M2')
        self.assertEqual((m1.hung, m1.source, m1.note), ('S1', 'assigned', ''))
        self.assertEqual((m2.hung, m2.source), ('S2', 'stock'))
        self.assertLess(m2.at, m1.at)                       # M2 hangs first, M1 still keeps S1

    def test_prior_set_the_export_lacks(self):
        r = self._run(machines=self._BOTH_A, prior=self._prior(m1_top=('S9',)), beam_sets=[_set('S1')])
        m1 = _note(r, 'M1')
        self.assertEqual((m1.prior, m1.note), ('S9', 'not in the new inventory'))
        self.assertIn(m1.source, ('stock', 'new'))
        self.b.close()
        r2 = self._run(machines=self._BOTH_A, prior=self._prior(m1_top=(None,)), beam_sets=[])
        self.assertEqual((_note(r2, 'M1').note, _note(r2, 'M1').source), ('invented', 'new'))

    def test_prior_set_too_large_for_the_machine(self):
        old = [dict(_machine('M1', 'A'), is_new=False), _machine('M2', 'A')]
        big = dict(_set('S1'), size='40 x 42')
        r = self._run(machines=old, prior=self._prior(), beam_sets=[big, _set('S2')])
        m1 = _note(r, 'M1')
        self.assertEqual((m1.prior, m1.note), ('S1', 'too large for the machine'))
        self.assertNotEqual(m1.hung, 'S1')
        self.b.close()
        r2 = self._run(machines=self._BOTH_A, prior=self._prior(), beam_sets=[big, _set('S2')])
        self.assertEqual(_note(r2, 'M1').hung, 'S1')

    def test_named_by_an_earlier_step(self):
        prior = _prior([_plan_job('J0', 'A', None, 1, _h(0)), _plan_job('J1', 'B', 'P1@B', 1, _h(1), top=('S1',))],
                       [_plan_job('J9', 'A', None, 1, _h(0)), _plan_job('J2', 'B', 'P2@B', 1, _h(2), top=('S1',))])
        r = self._run(machines=self._BOTH_A, prior=prior, beam_sets=[_set('S1')])
        self.assertEqual(_hangs(r, 'M1', 'top'), ['S1'])
        self.assertEqual(_note(r, 'M2').note, 'named by an earlier step')

    def test_queued_prior_set_is_kept(self):
        queued = dict(_set('Q1'), machine='M01', bar=2)
        prior = _prior([_plan_job('J0', 'A', None, 1, _h(0)), _plan_job('J1', 'B', 'P1@B', 1, _h(1), top=('Q1',))])
        r = self._run(machines=self._BOTH_A[:1], prior=prior, assigned_sets=[queued])
        m1 = _note(r, 'M1')
        self.assertEqual((m1.hung, m1.source, m1.note), ('Q1', 'queued', ''))

    def test_refused_assignment(self):
        r = self._run(machines=self._BOTH_A[:1], prior=self._prior(),
                      beam_sets=[_set('S1', received='2026-06-30 00:00:00')])
        self.assertEqual(r.failures, [])
        self.assertEqual(len(r.steps), 2)
        self.assertTrue(_note(r, 'M1').note.startswith('assignment refused'))

    def test_without_keep_sets_no_notes(self):
        r = self._run(keep=False, machines=self._BOTH_A, prior=self._prior(), beam_sets=[_set('S1')])
        self.assertTrue(all(h.note == '' for h in r.hangs))
        self.assertEqual(_hangs(r, 'M2', 'top'), ['S1'])     # runout order, not the prior name

    def test_placeholders_are_never_stock(self):
        prior = _prior([_plan_job('J0', 'A', None, 1, _h(0)), _plan_job('J1', 'B', 'P1@B', 1, _h(1), top=(None,)),
                        _plan_job('J3', 'A', 'P2@A', 1, _h(2))],
                       [_plan_job('J9', 'A', None, 6, _h(0)), _plan_job('J2', 'B', 'P2@B', 1, _h(5), top=(None,))])
        for keep in (False, True):
            r = self._run(keep=keep, machines=self._BOTH_A, prior=prior, beam_sets=[])
            self.assertTrue(_hangs(r, 'M1', 'top')[0].startswith('NEW'))
            self.assertTrue(_hangs(r, 'M2', 'top')[0].startswith('NEW'))
            self.b.close()


class PassedOverTextTests(unittest.TestCase):
    """5.5"""

    def test_passed_over_sets_listed(self):
        qb = _BeamSet('QB', 'MX', 900.0, _BeamSetDesc('30D RED 1172X4'), _START, assigned=True)
        po = _PassedOver('top', qb, _BeamSetDesc('40D WHT 1172X4 S/L'), _START)
        result = _result({'M1': Position('M1', 'A', remaining=[_pj(1, 'A', None, 1)])})
        result.report = _NS(queue_passed_over={'M1': (po,)})
        text = retime_text(result)
        block = text.split('ASSIGNED SETS PASSED OVER')[1].split('STEPS REPLAYED')[0]
        self.assertIn('set QB', block); self.assertIn('30D RED 1172X4', block)
        self.assertIn('merge MX', block); self.assertIn('bar needed 40D WHT 1172X4', block)
        result.report = None
        self.assertIn('none', retime_text(result).split('ASSIGNED SETS PASSED OVER')[1].split('STEPS REPLAYED')[0])
