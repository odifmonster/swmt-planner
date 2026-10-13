"""Rebuild the 10-01 greedy plan as manual steps, check fidelity, then apply
the detour edits and compare tape-outs / lateness.

Usage: replay.py baseline|edited [out.json]
"""
import json, sys, collections, importlib
from datetime import datetime, timedelta
from pathlib import Path

from swmtplanner.planners.manual import ManualSchedule, Step
from swmtplanner.planners.infinite import Costing
from swmtplanner.planners.infinite.report import late_orders_dataframe
from swmtplanner.schedule import TapeOut
P_mod = importlib.import_module('swmtplanner.planners.infinite.loop.plan')
R = importlib.import_module('swmtplanner.planners.infinite.run')

CFG = Path('/Users/lamanwyner/git-repos/swmt-projs/knit-input-files/master.json')
PLAN = Path('/Users/lamanwyner/Desktop/Shawmut Projects/Scheduling/knit_plan_20261001.json')
LOCAL = timedelta(hours=4)
P = lambda s: datetime.fromisoformat(s).replace(tzinfo=None) - LOCAL

mode = sys.argv[1] if len(sys.argv) > 1 else 'baseline'
ms = ManualSchedule.from_config(CFG)
state = ms.state
plan = json.load(open(PLAN))

# ----- steps from the plan ---------------------------------------------------
# per machine: jobs after the initial (advanced-to-change-date) ones
steps = []          # (sort_time, Step, orig_job)
orig = {}           # machine -> list of (item, rolls, end) for fidelity
for m in plan:
    mid = m['id']
    jobs = sorted((e for e in m['schedule'] if e['kind'] == 'job'), key=lambda e: e['start'])
    orig[mid] = [(j['item'], len(j['rolls']), P(j['end']), j['tgt_order']) for j in jobs]
    n_init = len(state.machines[mid].jobs)
    planner_jobs = jobs[n_init:]
    pending_cont = None   # a None-order continuation job awaiting its next_runout move
    for j in planner_jobs:
        if j['tgt_order'] is None:
            pending_cont = j
            continue
        at = 'schedule_tail'
        hang_src = [j]
        sort_t = P(j['start'])
        if pending_cont is not None:
            at = 'next_runout'
            hang_src = [pending_cont, j]
            sort_t = P(pending_cont['start'])
            pending_cont = None
        top, btm = [], []
        for src in hang_src:
            for a in src['activities']:
                if a['kind'] == 'Hanging':
                    for bar, lst in (('top', top), ('btm', btm)):
                        b = a.get(f'{bar}_beam')
                        if b is not None:
                            s = str(b['set_no'])
                            lst.append(None if s.startswith('NEW') else s)
        steps.append((sort_t, Step(mid, j['item'], len(j['rolls']), at, tuple(top), tuple(btm)), j))
steps.sort(key=lambda x: x[0])
print(f'{len(steps)} planner steps reconstructed')

# ----- edits -----------------------------------------------------------------
def drop(mid, item, rolls, order=None):
    global steps
    before = len(steps)
    steps = [s for s in steps if not (s[1].machine == mid and s[1].item == item and s[1].rolls == rolls
                                      and (order is None or s[2]['tgt_order'] == order))]
    assert len(steps) == before - 1, (mid, item, rolls, before - len(steps))

def replace_rolls(mid, item, order, new_rolls):
    for i, (t, s, j) in enumerate(steps):
        if s.machine == mid and s.item == item and j['tgt_order'] == order:
            steps[i] = (t, Step(mid, item, new_rolls, s.at, s.top, s.btm), j)
            return
    raise KeyError((mid, item, order))

def swap_item(mid, item, order, new_item):
    for i, (t, s, j) in enumerate(steps):
        if s.machine == mid and s.item == item and j['tgt_order'] == order:
            steps[i] = (t, Step(mid, new_item, s.rolls, s.at), j)
            return
    raise KeyError((mid, item, order))

def insert_before(mid, before_item, before_order, item, rolls):
    for i, (t, s, j) in enumerate(steps):
        if s.machine == mid and s.item == before_item and j['tgt_order'] == before_order:
            steps.insert(i, (t - timedelta(seconds=1), Step(mid, item, rolls), {'tgt_order': 'EDIT'}))
            return
    raise KeyError((mid, before_item, before_order))

def insert_after(mid, after_item, after_order, item, rolls):
    """Add a step on `mid` right after the step (after_item, after_order)."""
    for i, (t, s, j) in enumerate(steps):
        if s.machine == mid and s.item == after_item and j['tgt_order'] == after_order:
            steps.insert(i + 1, (t + timedelta(seconds=1), Step(mid, item, rolls), {'tgt_order': 'EDIT'}))
            return
    raise KeyError((mid, after_item, after_order))

POST = []   # ordered: ('fill', machine, item, until) | ('tack', machine, item, rolls), applied after the replay

if mode in ('edited', 'swap'):
    # K7: no AU2958A detour; stay on AU7980 (3 rolls to Friday) then AU8085
    drop('K7', 'AU2958A', 1)
    replace_rolls('K7', 'AU7980', 'P2@AU7980', 3)
    POST.append(('tack', 'P2', 'AU2958A', 1))          # the P3 roll, due 10-19
    # O2: straight from AU3426 to AU4583; the AU4782DREP roll goes into I9's gap
    drop('O2', 'AU4782DREP', 1)
    insert_after('I9', 'AU4782DREP', 'S@AU4782DREP', 'AU4782DREP', 1)
    # M3: straight to AU7389H; AU4583 roll to O3, AU4782K roll to K8
    drop('M3', 'AU4583', 1)
    drop('M3', 'AU4782K', 1)
    insert_after('O3', 'AU4583', 'P0@AU4583', 'AU4583', 1)
    insert_after('K8', 'AU4782K', 'S@AU4782K', 'AU4782K', 1)
    # B8: stays on AU5429D; AU6953 safety to I4's end, the AU8084A roll to K11's end
    drop('B8', 'AU6953', 2)
    drop('B8', 'AU8084A', 1)
    POST.append(('fill', 'B8', 'AU5429D', datetime(2026, 10, 16, 16, 39)))
    POST.append(('tack', 'I4', 'AU6953', 2))
    POST.append(('tack', 'K11', 'AU8084A', 1))
    # J9 / K5 / R1: no end-of-plan safety tape-outs; stay on their yarn, safety tacked on elsewhere
    drop('J9', 'AU4782', 2)
    POST.append(('fill', 'J9', 'AU5429D', datetime(2026, 10, 15, 19, 3)))
    POST.append(('tack', 'G6', 'AU4782', 2))
    drop('K5', 'AU3426H', 2)
    POST.append(('fill', 'K5', 'AU8154', datetime(2026, 10, 16, 7, 4)))
    POST.append(('tack', 'N1', 'AU3426H', 2))
    drop('R1', 'AU3426H', 2)
    POST.append(('fill', 'R1', 'AU5429D', datetime(2026, 10, 16, 7, 37)))
    POST.append(('tack', 'O3', 'AU3426H', 2))


if mode == 'swap':
    def unpost(*key):
        global POST
        n = len(POST); POST = [p for p in POST if p[1:1 + len(key)] != key]; assert len(POST) == n - 1, key
    # N1, P2, M3 stay on black for the whole plan
    drop('N1', 'AU3426H', 6); unpost('N1', 'AU3426H')
    POST.append(('fill', 'N1', 'AU7980', datetime(2026, 10, 21, 0, 0)))
    drop('P2', 'AU3426H', 5); unpost('P2', 'AU2958A')
    POST.append(('fill', 'P2', 'AU7980', datetime(2026, 10, 21, 0, 0)))
    for it, r in (('AU7389H', 2), ('AU7389G', 6), ('AU7389G', 5), ('AU7980', 1), ('AU7980', 4)):
        drop('M3', it, r)
    POST.insert(0, ('fill', 'M3', 'AU8084A', datetime(2026, 10, 20, 0, 0)))   # first, so its 10-02 hangs see the stock
    # I3, K11, O2, I9 stay on white / their own yarn
    drop('I3', 'AU7980', 1); drop('I3', 'AU8084A', 4)
    swap_item('I3', 'AU4782', 'S@AU4782', 'AU3426H')          # week-2 AU3426H instead of AU4782 safety
    POST.append(('fill', 'I3', 'AU4782', datetime(2026, 10, 17, 0, 0)))     # week-3 AU4782 before the weekend
    drop('K11', 'AU7980', 1); drop('K11', 'AU8084A', 1); unpost('K11', 'AU8084A')
    swap_item('K11', 'AU4782', 'S@AU4782', 'AU3426H')
    swap_item('K11', 'AU2958A', 'S@AU2958A', 'AU7389G')     # AU2958A safety goes to the end, AU7389G week 2 comes forward
    POST.append(('tack', 'K11', 'AU2958A', 3))                       # the P3 roll, due 10-19, plus the safety
    POST.append(('fill', 'K11', 'AU3426H', datetime(2026, 10, 20, 0, 0)))
    drop('O2', 'AU7980', 1); drop('O2', 'AU7980', 5)
    POST.append(('tack', 'O2', 'AU4782', 2))                          # week-3 AU4782, done before the weekend
    POST.append(('fill', 'O2', 'AU7389G', datetime(2026, 10, 21, 0, 0)))
    # K8: one roll of AU4782K for the week-2 order, AU7389G week 2 next, the AU4782K safety at the end
    replace_rolls('K8', 'AU4782K', 'S@AU4782K', 1)
    insert_after('K8', 'AU4782K', 'S@AU4782K', 'AU7389G', 2)
    POST.append(('tack', 'K8', 'AU4782K', 2))
    drop('I9', 'AU7980', 1); drop('I9', 'AU8084A', 4)
    POST.append(('fill', 'I9', 'AU4782DREP', datetime(2026, 10, 17, 0, 0)))
    # P4 skips the AU7992T2A yarn: white AU3426H until its black move; Q6 makes all the AU7992T2A
    drop('P4', 'AU7992T2A', 1); drop('P4', 'AU7992T2A', 2, 'S@AU7992T2A'); drop('P4', 'AU7992T2A', 2, 'P3@AU7992T2A')
    drop('P4', 'AU7389G', 4)
    insert_before('P4', 'AU8085', 'P2@AU8085', 'AU7389G', 8)      # the week-2 AU7389G that M3 was making
    replace_rolls('Q6', 'AU7992T2A', 'S@AU7992T2A', 6); drop('Q6', 'AU7992T2A', 1, 'P3@AU7992T2A')
    POST.append(('fill', 'Q6', 'AU8084A', datetime(2026, 10, 22, 0, 0)))
    # the AU3426H safety that N1 was going to tack on goes to O3 as well
    # AU4782 safety displaced from I3/K11 joins G6's tack
    # (G6 keeps its two safety rolls of AU4782)

# ----- replay ---------------------------------------------------------------
fallbacks = []
def commit(step):
    top, btm = list(step.top), list(step.btm)
    for _ in range(12):
        try:
            ms.rolls(step.machine, step.item, step.rolls, step.at, top, btm)
            ms.commit(step.machine)
            return
        except ValueError as ex:
            msg = str(ex)
            # drop the offending named set and retry
            hit = None
            for lst in (top, btm):
                for i, s in enumerate(lst):
                    if s is not None and s in msg:
                        hit = (lst, i, s)
            if hit is None:
                raise
            lst, i, s = hit
            lst[i] = None
            fallbacks.append((step.machine, step.item, s, msg[:90]))
    raise RuntimeError(f'could not commit {step}')

for _t, step, _j in steps:
    commit(step)

def fill(mid, item, until):
    """Whole rolls of `item` at `mid`'s tail, as many as end by `until`."""
    n = 0
    while True:
        pl = ms.rolls(mid, item, n + 1)
        if pl.activities[-1].end > until + timedelta(hours=6):
            ms.discard(mid)
            break
        n += 1
    if n:
        ms.rolls(mid, item, n); ms.commit(mid)
    return n

for op in POST:
    if op[0] == 'fill':
        _, mid, item, until = op
        n = fill(mid, item, until)
    else:
        _, mid, item, n = op
        ms.rolls(mid, item, n); ms.commit(mid)
    print(f'  {op[0]} {mid} {item} x{n} -> tail {state.machines[mid].schedule_tail:%a %m-%d %H:%M}')

if fallbacks:
    print(f'{len(fallbacks)} named sets fell back to automatic:')
    for f in fallbacks: print('   ', f)

# ----- fidelity (baseline) ----------------------------------------------------
if mode == 'baseline':
    worst = []
    for mid, m in state.machines.items():
        mine = [(j.item.id, len(j.rolls), j.activities[-1].end) for j in m.jobs]
        theirs = orig.get(mid, [])
        if len(mine) != len(theirs):
            worst.append((mid, 'count', len(mine), len(theirs))); continue
        for (i1, r1, e1), (i2, r2, e2, _o) in zip(mine, theirs):
            d = (e1 - e2).total_seconds() / 3600
            if i1 != i2 or r1 != r2 or abs(d) > 1.0:
                worst.append((mid, i1, r1, f'{e1:%m-%d %H:%M}', i2, r2, f'{e2:%m-%d %H:%M}', round(d, 1)))
    print(f'fidelity: {len(worst)} job mismatches (>1h or item/rolls differ)')
    for w in worst: print('   ', w)

# ----- metrics ---------------------------------------------------------------
_cfg, inputs = R.load_config(CFG, echo=lambda *a, **k: None)
costing = Costing(inputs.weights)
report = P_mod._build_report(state, costing)
tos = collections.Counter()
for mid, m in state.machines.items():
    for a in m.activities:
        if isinstance(a, TapeOut):
            tos[a.bars] += 1
new_sets = sum(1 for m in state.machines.values() for a in m.activities
               if a.__class__.__name__ == 'Hanging'
               for b in (getattr(a, 'top_beam', None), getattr(a, 'btm_beam', None))
               if b is not None and b.is_new)
print(f'\n=== {mode}: score {report.total_score:,.0f}  tape-outs {dict(tos)}  '
      f'cost {4000*(tos["top"]+tos["btm"]) + 6400*tos["both"]:,}  invented sets {new_sets}')
lo = late_orders_dataframe(report)
lo['fill_date'] = lo['fill_date'].dt.floor('min')
print(lo.to_string())
print('late lbs total', int(lo['late_lbs'].sum()), ' orders', len(lo))
out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
if out:
    from swmtplanner.planners.infinite.report import write_plan_report_xlsx
    ms.write_json(out)
    ms.save_steps(out.with_name(out.stem + '.steps.json'))
    write_plan_report_xlsx(report, out.with_suffix('.xlsx'))
    print('wrote', out, 'and .steps.json / .xlsx')
