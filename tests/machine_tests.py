#!/usr/bin/env python

from datetime import datetime, timedelta

from swmtplanner.products import BeamSet, Greige
from swmtplanner.support import WorkCal
from swmtplanner.schedule.machine.machine import Machine

GREIGE_STYLE_DATA = [
    ['AU1234','A',700,'40D WHT 1172X4 S/L',0.27,'70D WHT 1172X4',0.73,2800,3,'M1','M2','M3',863,863,863],
    ['AU0420','A',700,'40D BLK 1172X4 S/L',0.19,'70D BLK 1172X4',0.81,1400,3,'M1','M2','M3',840,840,840],
    ['AU1985','A',700,'40D WHT 1172X4 S/L',0.25,'70D WHT 1172X4',0.75,1400,3,'M1','M2','M3',850,850,850]
]

MACHINE_DATA = ['M1', 'M2', 'M3']

def make_greige_styles():
    ret = []

    for row in GREIGE_STYLE_DATA:
        name, family, tgt, top, top_pct, btm, btm_pct, safety, n_mchns, *vals = row
        mchn_ids = vals[:n_mchns]
        mchn_rates = vals[n_mchns:]
        mchn_mat = { mchn_ids[i]: mchn_rates[i] for i in range(n_mchns) }
        ret.append(Greige(name, family, tgt, top, top_pct, btm, btm_pct, safety, mchn_mat))

    return ret

# A fixed Mon-Fri 9-5 calendar with no holidays so test arithmetic is clean.
def make_workcal():
    return WorkCal(work_days=(0, 1, 2, 3, 4), day_start=9, day_end=17, holidays=())

START = datetime(2025, 6, 2, 9)  # Monday, 2025-06-02 at 9am (ISO week 23)

def make_machine(mchn_id='M1', init_idx=0, start=START):
    """Build a Machine plus the freshly-constructed greige list it uses."""
    styles = make_greige_styles()
    return Machine(mchn_id, styles[init_idx], start, make_workcal()), styles

# ---- identity properties --------------------------------------------------
def test_id_matches_input():
    styles = make_greige_styles()
    for mchn_id in MACHINE_DATA:
        m = Machine(mchn_id, styles[0], START, make_workcal())
        assert m.id == mchn_id, f'id={m.id!r}, expected {mchn_id!r}'

def test_prefix():
    m, _ = make_machine()
    assert m.prefix == 'Machine', f'prefix={m.prefix!r}, expected {"Machine"!r}'

# ---- initial state --------------------------------------------------------
def test_initial_schedule_is_empty():
    m, _ = make_machine()
    assert m.schedule == (), f'schedule={m.schedule!r}, expected empty tuple'

def test_initial_next_job_end_equals_start_date():
    m, _ = make_machine()
    assert m.next_job_end == START, \
        f'next_job_end={m.next_job_end!r}, expected {START!r}'

def test_workcal_property_returns_input_calendar():
    styles = make_greige_styles()
    wc = make_workcal()
    m = Machine('M1', styles[0], START, wc)
    assert m.workcal is wc, 'workcal property should return the same WorkCal instance'

# ---- get_bar_status -------------------------------------------------------
def test_get_bar_status_initial_returns_init_item_beams():
    for init_idx in range(len(GREIGE_STYLE_DATA)):
        m, styles = make_machine(init_idx=init_idx)
        cfg = styles[init_idx].configuration
        top = m.get_bar_status('top')
        btm = m.get_bar_status('btm')
        assert isinstance(top, BeamSet), \
            f'[init={styles[init_idx].id}] top is {type(top).__name__}, expected BeamSet'
        assert isinstance(btm, BeamSet), \
            f'[init={styles[init_idx].id}] btm is {type(btm).__name__}, expected BeamSet'
        assert top.id == cfg.top_beam, \
            f'[init={styles[init_idx].id}] top.id={top.id!r}, expected {cfg.top_beam!r}'
        assert btm.id == cfg.btm_beam, \
            f'[init={styles[init_idx].id}] btm.id={btm.id!r}, expected {cfg.btm_beam!r}'

def test_get_bar_status_default_on_dt_reflects_end_of_schedule():
    # init AU1234 (WHT beams) -> add AU0420 (BLK beams). Default on_dt should
    # report AU0420's beams since that's the most recent (only) added job.
    m, styles = make_machine(init_idx=0)
    rate = styles[1].get_rate_on_mchn('M1')
    m.add_job(styles[1], rate)  # 1 hour
    cfg = styles[1].configuration
    assert m.get_bar_status('top').id == cfg.top_beam, \
        f'top={m.get_bar_status("top").id!r}, expected {cfg.top_beam!r}'
    assert m.get_bar_status('btm').id == cfg.btm_beam, \
        f'btm={m.get_bar_status("btm").id!r}, expected {cfg.btm_beam!r}'

def test_get_bar_status_with_on_dt_during_running_job():
    # init AU1234 (WHT) -> running AU0420 (BLK): mid-run query reports BLK.
    m, styles = make_machine(init_idx=0)
    rate = styles[1].get_rate_on_mchn('M1')
    m.add_job(styles[1], rate * 4)  # 4 hours: Mon 9am - Mon 1pm
    mid_run = datetime(2025, 6, 2, 11)  # Mon 11am
    cfg = styles[1].configuration
    assert m.get_bar_status('top', mid_run).id == cfg.top_beam, \
        f'top={m.get_bar_status("top", mid_run).id!r}, expected {cfg.top_beam!r}'
    assert m.get_bar_status('btm', mid_run).id == cfg.btm_beam, \
        f'btm={m.get_bar_status("btm", mid_run).id!r}, expected {cfg.btm_beam!r}'

def test_get_bar_status_transitions_across_multiple_jobs():
    """As the schedule sequences items with different beams (WHT -> BLK -> WHT),
    queries at different points report the running item's beams."""
    m, styles = make_machine(init_idx=0)  # AU1234 WHT
    m.add_job(styles[1], styles[1].get_rate_on_mchn('M1'))  # AU0420 BLK, 9-10am
    m.add_job(styles[2], styles[2].get_rate_on_mchn('M1'))  # AU1985 WHT, 10-11am

    blk = styles[1].configuration
    wht_after = styles[2].configuration

    # Mon 9:30 -> during AU0420 (BLK).
    during_blk = datetime(2025, 6, 2, 9, 30)
    assert m.get_bar_status('top', during_blk).id == blk.top_beam, \
        f'during AU0420: top={m.get_bar_status("top", during_blk).id!r}, ' \
        f'expected {blk.top_beam!r}'
    assert m.get_bar_status('btm', during_blk).id == blk.btm_beam, \
        f'during AU0420: btm={m.get_bar_status("btm", during_blk).id!r}, ' \
        f'expected {blk.btm_beam!r}'

    # Mon 10:30 -> during AU1985 (WHT). Confirms the bar reverts to WHT.
    during_wht = datetime(2025, 6, 2, 10, 30)
    assert m.get_bar_status('top', during_wht).id == wht_after.top_beam, \
        f'during AU1985: top={m.get_bar_status("top", during_wht).id!r}, ' \
        f'expected {wht_after.top_beam!r}'
    assert m.get_bar_status('btm', during_wht).id == wht_after.btm_beam, \
        f'during AU1985: btm={m.get_bar_status("btm", during_wht).id!r}, ' \
        f'expected {wht_after.btm_beam!r}'

    # Default on_dt -> end of schedule, AU1985 (WHT).
    assert m.get_bar_status('top').id == wht_after.top_beam, \
        f'end of schedule: top={m.get_bar_status("top").id!r}, ' \
        f'expected {wht_after.top_beam!r}'
    assert m.get_bar_status('btm').id == wht_after.btm_beam, \
        f'end of schedule: btm={m.get_bar_status("btm").id!r}, ' \
        f'expected {wht_after.btm_beam!r}'

def test_get_bar_status_before_start_returns_init_item_beams():
    """A date before start_date falls back to the init item, even when later
    jobs in the schedule use different beams."""
    m, styles = make_machine(init_idx=1)  # init AU0420 BLK
    m.add_job(styles[0], styles[0].get_rate_on_mchn('M1'))  # AU1234 WHT
    before = START - timedelta(hours=1)
    init_cfg = styles[1].configuration
    assert m.get_bar_status('top', before).id == init_cfg.top_beam, \
        f'top before start={m.get_bar_status("top", before).id!r}, ' \
        f'expected init {init_cfg.top_beam!r}'
    assert m.get_bar_status('btm', before).id == init_cfg.btm_beam, \
        f'btm before start={m.get_bar_status("btm", before).id!r}, ' \
        f'expected init {init_cfg.btm_beam!r}'

def test_get_bar_status_at_transition_boundary_uses_next_job():
    """At the exact instant where one job ends and the next begins
    (j1.end == j2.start), the new job's beams are reported."""
    m, styles = make_machine(init_idx=0)  # AU1234 WHT
    m.add_job(styles[1], styles[1].get_rate_on_mchn('M1'))  # AU0420 BLK, 9-10am
    m.add_job(styles[2], styles[2].get_rate_on_mchn('M1'))  # AU1985 WHT, 10-11am
    boundary = datetime(2025, 6, 2, 10)  # j1.end == j2.start
    next_cfg = styles[2].configuration
    assert m.get_bar_status('top', boundary).id == next_cfg.top_beam, \
        f'at boundary: top={m.get_bar_status("top", boundary).id!r}, ' \
        f'expected next-job {next_cfg.top_beam!r}'
    assert m.get_bar_status('btm', boundary).id == next_cfg.btm_beam, \
        f'at boundary: btm={m.get_bar_status("btm", boundary).id!r}, ' \
        f'expected next-job {next_cfg.btm_beam!r}'

def test_get_bar_status_invalid_bar_raises_value_error():
    m, _ = make_machine()
    raised = False
    try:
        m.get_bar_status('left')
    except ValueError:
        raised = True
    assert raised, 'expected ValueError for bar not in {"top", "btm"}'

# ---- predict_job_end ------------------------------------------------------
# AU1234 on M1 has rate 863 lbs/hr in the GREIGE_STYLE_DATA fixture, so
# 863 lbs = 1 work hour, 6904 lbs = 8 work hours = one full work day, etc.
def test_predict_job_end_one_hour():
    m, styles = make_machine(mchn_id='M1')
    end = m.predict_job_end(styles[0], 863)
    assert end == datetime(2025, 6, 2, 10), \
        f'predicted={end!r}, expected Mon 10am'

def test_predict_job_end_full_workday_lands_on_day_end():
    m, styles = make_machine(mchn_id='M1')
    end = m.predict_job_end(styles[0], 863 * 8)
    assert end == datetime(2025, 6, 2, 17), \
        f'predicted={end!r}, expected Mon 5pm'

def test_predict_job_end_spills_into_next_workday():
    m, styles = make_machine(mchn_id='M1')
    # 9 work hours from Mon 9am: 8 hrs Mon + 1 hr Tue = Tue 10am.
    end = m.predict_job_end(styles[0], 863 * 9)
    assert end == datetime(2025, 6, 3, 10), \
        f'predicted={end!r}, expected Tue 10am'

def test_predict_job_end_does_not_mutate_state():
    m, styles = make_machine(mchn_id='M1')
    nje_before = m.next_job_end
    sched_before = m.schedule
    m.predict_job_end(styles[0], 863)
    assert m.next_job_end == nje_before, 'predict_job_end must not advance next_job_end'
    assert m.schedule == sched_before, 'predict_job_end must not modify schedule'

def test_predict_job_end_uses_per_machine_rate():
    # Different machines could have different rates (here the fixture happens
    # to use the same rate per style, but the call should still go through
    # `Greige.get_rate_on_mchn(machine.id)` rather than e.g. a fixed first-rate).
    styles = make_greige_styles()
    for mchn_id in MACHINE_DATA:
        m = Machine(mchn_id, styles[0], START, make_workcal())
        rate = styles[0].get_rate_on_mchn(mchn_id)
        end = m.predict_job_end(styles[0], rate)  # exactly 1 work hour
        assert end == datetime(2025, 6, 2, 10), \
            f'[{mchn_id}] predicted={end!r}, expected Mon 10am'

# ---- add_job --------------------------------------------------------------
def test_add_job_returns_job_with_correct_fields():
    m, styles = make_machine(mchn_id='M1')
    item = styles[0]
    job = m.add_job(item, 863)
    assert job.start == START, f'job.start={job.start!r}, expected {START!r}'
    assert job.end == datetime(2025, 6, 2, 10), \
        f'job.end={job.end!r}, expected Mon 10am'
    assert job.lbs == 863, f'job.lbs={job.lbs!r}, expected 863'
    assert job.item is item, 'job.item should be the input Greige'

def test_add_job_appends_to_schedule_in_order():
    m, styles = make_machine(mchn_id='M1')
    assert m.schedule == ()
    j1 = m.add_job(styles[0], 863)
    assert m.schedule == (j1,), f'schedule={m.schedule!r}, expected (j1,)'
    j2 = m.add_job(styles[1], 840)
    assert m.schedule == (j1, j2), f'schedule={m.schedule!r}, expected (j1, j2)'

def test_add_job_advances_next_job_end():
    m, styles = make_machine(mchn_id='M1')
    m.add_job(styles[0], 863)  # 1 hr
    assert m.next_job_end == datetime(2025, 6, 2, 10)
    m.add_job(styles[0], 863)  # +1 hr
    assert m.next_job_end == datetime(2025, 6, 2, 11)

def test_add_job_chains_consecutive_jobs():
    # j2 must start exactly where j1 ends — schedule has no gaps.
    m, styles = make_machine(mchn_id='M1')
    j1 = m.add_job(styles[0], 863)
    j2 = m.add_job(styles[1], 840 * 3)
    assert j2.start == j1.end, \
        f'consecutive jobs should chain: j2.start={j2.start!r}, j1.end={j1.end!r}'

# ---- avail_hours_in_week --------------------------------------------------
def test_avail_hours_empty_schedule_returns_full_week():
    # Mon-Fri, 8 hrs/day, no holidays => 40 hrs/week.
    m, _ = make_machine()
    assert m.avail_hours_in_week(2025, 23) == 40.0, \
        f'avail_hours={m.avail_hours_in_week(2025, 23)!r}, expected 40.0'

def test_avail_hours_decreases_after_jobs():
    m, styles = make_machine(mchn_id='M1')
    m.add_job(styles[0], 863)  # +1 hr (Mon 10am)
    assert m.avail_hours_in_week(2025, 23) == 39.0
    m.add_job(styles[0], 863 * 7)  # +7 hrs => Mon 5pm (full Monday consumed)
    assert m.avail_hours_in_week(2025, 23) == 32.0

def test_avail_hours_past_week_returns_zero():
    # Schedule starts in week 23; week 22 already lies before the schedule.
    m, _ = make_machine()
    assert m.avail_hours_in_week(2025, 22) == 0.0

def test_avail_hours_future_week_returns_full():
    # Empty schedule never reaches week 24, so all hours remain available.
    m, _ = make_machine()
    assert m.avail_hours_in_week(2025, 24) == 40.0

def main():
    test_id_matches_input()
    test_prefix()
    print('Identity tests passed.')

    test_initial_schedule_is_empty()
    test_initial_next_job_end_equals_start_date()
    test_workcal_property_returns_input_calendar()
    print('Initial state tests passed.')

    test_get_bar_status_initial_returns_init_item_beams()
    test_get_bar_status_default_on_dt_reflects_end_of_schedule()
    test_get_bar_status_with_on_dt_during_running_job()
    test_get_bar_status_transitions_across_multiple_jobs()
    test_get_bar_status_before_start_returns_init_item_beams()
    test_get_bar_status_at_transition_boundary_uses_next_job()
    test_get_bar_status_invalid_bar_raises_value_error()
    print('get_bar_status tests passed.')

    test_predict_job_end_one_hour()
    test_predict_job_end_full_workday_lands_on_day_end()
    test_predict_job_end_spills_into_next_workday()
    test_predict_job_end_does_not_mutate_state()
    test_predict_job_end_uses_per_machine_rate()
    print('predict_job_end tests passed.')

    test_add_job_returns_job_with_correct_fields()
    test_add_job_appends_to_schedule_in_order()
    test_add_job_advances_next_job_end()
    test_add_job_chains_consecutive_jobs()
    print('add_job tests passed.')

    test_avail_hours_empty_schedule_returns_full_week()
    test_avail_hours_decreases_after_jobs()
    test_avail_hours_past_week_returns_zero()
    test_avail_hours_future_week_returns_full()
    print('avail_hours_in_week tests passed.')

if __name__ == '__main__':
    main()