"""Build a self-contained Gantt page from a plan JSON.
Usage: make_gantt.py <plan.json> <out.html>

Rows: new machines first, then old machines, both by id (the plan JSON
no longer carries machines that only idle). Every schedule
activity is drawn as its own segment, coloured by the page's selected
overlay: activity type, the yarn a knit uses, yarn plus pattern family,
or the style. Yarn changes, tape-outs, pattern changes and slot waits are
marked on top; weekends and holidays are shaded."""
import json, sys, html
from datetime import datetime, timedelta, date
from pathlib import Path

plan_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
INPUTS = Path('/Users/lamanwyner/git-repos/swmt-projs/knit-input-files')
LOCAL = timedelta(hours=4)             # plan JSON is UTC; plant is EDT
T0 = datetime(2026, 10, 1)              # local midnight of the plan's first day

def loc(s):
    return datetime.fromisoformat(s).replace(tzinfo=None) - LOCAL
def mins(dt):
    return round((dt - T0).total_seconds() / 60)

styles = json.load(open(INPUTS / 'greige-styles.json'))
styles = styles if isinstance(styles, list) else list(styles.values())
pattern = {s['id']: s.get('pattern', '?') for s in styles}
yarn = {s['id']: (s['beam_cfg']['top']['beamset'], s['beam_cfg']['btm']['beamset']) for s in styles}
norm = lambda d: (d or '').replace(' S/L', '').strip()

machines_in = json.load(open(INPUTS / 'machines.json'))
machines_in = machines_in if isinstance(machines_in, list) else list(machines_in.values())
is_new = {m['id']: bool(m.get('is_new')) for m in machines_in}

FAMILY = {
    ('40D BLK 1172X4', '75D BLK TX 1172X4'): 'Black 1172',
    ('40D WHT 1172X4', '75D WHT TX 1172X4'): 'White 1172',
    ('75D WHT TX 1172X4', '40D WHT 1172X4'): 'White 1172 reversed',
    ('40D BLK REP TX 1172X4', '75D BLK TX 1172X4'): 'Black REP top',
    ('40D W CAT 1172X4', '75D WHT TX 1172X4'): 'White CAT top',
    ('40D WHT 1172X4', '75D W REP TX 1172X4'): 'White REP btm',
    ('75D BLK 1172X4', '75D WHT TX 1172X4'): '75D black top / white',
    ('40D W REP 1172X4', '75D W REP TX 1172X4'): 'White REP both',
    ('40D WHT 1340X4', '75D WHT TX 1340X4'): 'White 1340',
    ('40D BLK 1300X4', '75D BLK TX 1300X4'): 'Black 1300',
}
def yarn_key(item):
    t, b = yarn[item]
    return FAMILY.get((norm(t), norm(b)), f'{norm(t)} / {norm(b)}')

def mid_sort(mid):
    return (mid[0], int(mid[1:]) if mid[1:].isdigit() else 0)

plan = json.load(open(plan_path))
machines = []
horizon_end = T0
for m in sorted(plan, key=lambda m: mid_sort(m['id'])):
    mid = m['id']
    ents = sorted(m['schedule'], key=lambda e: e['start'])
    jobs = [e for e in ents if e['kind'] == 'job']
    if not jobs:
        continue                       # nothing planned: not a row
    row = dict(id=mid, new=is_new.get(mid, False),
               jobs=[], acts=[], hangs=[], tapeouts=[], pattern=[], waits=[])
    bar_desc = {'top': None, 'btm': None}
    for e in ents:
        if e['kind'] == 'Idle':
            a0, a1 = mins(loc(e['start'])), mins(loc(e['end']))
            row['acts'].append(dict(k='Idle', s=a0, e=a1, reason=e.get('reason') or ''))
            if e.get('reason'):
                row['waits'].append([a0, a1, e['reason']])
            continue
        if e['kind'] == 'Waste':
            a0 = mins(loc(e['start']))
            row['acts'].append(dict(k='Waste', s=a0, e=a0, bar=e['bar'], lbs=round(e['lbs']),
                                    set=e['beam']['set_no'], desc=norm(e['beam']['desc'])))
            continue
        if e['kind'] != 'job':
            continue
        it = e['item']
        s, en = loc(e['start']), loc(e['end'])
        horizon_end = max(horizon_end, en)
        ykey = yarn_key(it)
        row['jobs'].append(dict(item=it, s=mins(s), e=mins(en), rolls=len(e['rolls']),
                                lbs=round(e['total_lbs']), order=e.get('tgt_order') or '',
                                yarn=ykey, pat=pattern.get(it, '?'),
                                top=norm(yarn[it][0]), btm=norm(yarn[it][1])))
        for a in e['activities']:
            k = a['kind']; a0, a1 = mins(loc(a['start'])), mins(loc(a['end']))
            act = dict(k=k, s=a0, e=a1)
            if k == 'Knit':
                act.update(item=a['item'], lbs=round(a['lbs']), variant=a.get('variant') or '',
                           yarn=ykey, fam=f"{ykey} · {pattern.get(a['item'], '?')}",
                           pat=pattern.get(a['item'], '?'))
            elif k == 'Hanging':
                act['bars'] = a['bars']
                for bar in ('top', 'btm'):
                    b = a.get(f'{bar}_beam')
                    if not b:
                        continue
                    d = norm(b['desc'])
                    prev = bar_desc[bar]
                    change = prev is not None and prev != d
                    row['hangs'].append(dict(t=a0, t1=a1, bar=bar, set=b['set_no'], desc=d,
                                             frm=prev or '', change=change,
                                             new=str(b['set_no']).startswith('NEW'),
                                             lbs=round(b['lbs'] or 0), merge=b.get('merge') or '',
                                             vendor=b.get('vendor') or ''))
                    bar_desc[bar] = d
                act['sets'] = ', '.join(f"{bar} {a[f'{bar}_beam']['set_no']} {norm(a[f'{bar}_beam']['desc'])}"
                                        for bar in ('top', 'btm') if a.get(f'{bar}_beam'))
            elif k == 'Threading':
                act['bars'] = a['bars']
            elif k == 'TapeOut':
                off = []
                for bar in ('top', 'btm'):
                    b = a.get(f'{bar}_beam')
                    if b:
                        off.append(f"{bar}: {b['set_no']} {norm(b['desc'])} ({round(b['lbs'] or 0)} lbs left)")
                act.update(bars=a['bars'], off=off)
                row['tapeouts'].append(dict(t=a0, t1=a1, bars=a['bars'], off=off))
            elif k in ('PatternChange', 'RunnerChange', 'StyleChange'):
                act.update(frm=a['from_item'], to=a['to_item'])
                if k == 'PatternChange':
                    row['pattern'].append(dict(t=a0, t1=a1, frm=a['from_item'], to=a['to_item']))
            elif k == 'Idle':
                act['reason'] = a.get('reason') or ''
                if a.get('reason'):
                    row['waits'].append([a0, a1, a['reason']])
            row['acts'].append(act)
        for bar in ('top', 'btm'):
            if bar_desc[bar] is None:
                bar_desc[bar] = norm(yarn[it][0] if bar == 'top' else yarn[it][1])
    machines.append(row)

# Row order: new machines, then old machines, each group by machine id.
machines.sort(key=lambda r: ((0 if r['new'] else 1), mid_sort(r['id'])))

end_day = (horizon_end + timedelta(days=1)).date()
offwork = []
d = T0.date()
oct_mondays = [date(2026, 10, x) for x in range(1, 32) if date(2026, 10, x).weekday() == 0]
holidays = {oct_mondays[1]: 'Columbus Day'}
while d <= end_day:
    label = holidays.get(d) or ('Weekend' if d.weekday() >= 5 else None)
    if label:
        s = datetime.combine(d, datetime.min.time())
        offwork.append([mins(s), mins(s + timedelta(days=1)), label])
    d += timedelta(days=1)

days = []
d = T0.date()
while d <= end_day:
    days.append([mins(datetime.combine(d, datetime.min.time())), d.strftime('%a'), d.strftime('%b %-d')])
    d += timedelta(days=1)

# changeover ration per local day: tape-out bars and pattern changes used
master = json.load(open(INPUTS / 'master.json'))
ration = master.get('changeover_capacity') or {}
cap_limits = {k: v['units_per_period'] for k, v in ration.items() if isinstance(v, dict)}
cap_used = {}
_EMPTY = {'tape_out': 0, 'pattern_change': 0, 'change': 0}
for r in machines:
    for t in r['tapeouts']:
        dk = (T0 + timedelta(minutes=t['t'])).date().isoformat()
        cap_used.setdefault(dk, dict(_EMPTY))['tape_out'] += 2 if t['bars'] == 'both' else 1
    for p in r['pattern']:
        dk = (T0 + timedelta(minutes=p['t'])).date().isoformat()
        cap_used.setdefault(dk, dict(_EMPTY))['pattern_change'] += 1
    # one change per preamble that changed the machine: a changeover
    # activity (counted on the day of the tape-out that opened the
    # preamble, if any), or a tape-out with no changeover before the next knit
    pending = None
    for a in sorted(r['acts'], key=lambda a: a['s']):
        if a['k'] == 'TapeOut':
            if pending is not None:
                cap_used.setdefault(pending, dict(_EMPTY))['change'] += 1
            pending = (T0 + timedelta(minutes=a['s'])).date().isoformat()
        elif a['k'] in ('PatternChange', 'RunnerChange', 'StyleChange'):
            dk = pending or (T0 + timedelta(minutes=a['s'])).date().isoformat()
            cap_used.setdefault(dk, dict(_EMPTY))['change'] += 1
            pending = None
        elif a['k'] == 'Knit' and pending is not None:
            cap_used.setdefault(pending, dict(_EMPTY))['change'] += 1
            pending = None
    if pending is not None:
        cap_used.setdefault(pending, dict(_EMPTY))['change'] += 1

keys = {
    'yarn': sorted({a['yarn'] for r in machines for a in r['acts'] if a['k'] == 'Knit'}),
    'fam': sorted({a['fam'] for r in machines for a in r['acts'] if a['k'] == 'Knit'}),
    'style': sorted({a['item'] for r in machines for a in r['acts'] if a['k'] == 'Knit'}),
}
data = dict(machines=machines, offwork=offwork, days=days, keys=keys,
            cap_limits=cap_limits, cap_used=cap_used,
            t_end=mins(datetime.combine(end_day, datetime.min.time())),
            source=plan_path.name)
totals = dict(
    yarn_changes=sum(h['change'] for r in machines for h in r['hangs']),
    tapeouts=sum(len(r['tapeouts']) for r in machines),
    pattern=sum(len(r['pattern']) for r in machines),
    hangs=sum(len(r['hangs']) for r in machines),
    invented=sum(h['new'] for r in machines for h in r['hangs']),
)
data['totals'] = totals

page = open(Path(__file__).with_name('gantt_template.html')).read()
page = page.replace('/*__DATA__*/null', json.dumps(data, separators=(',', ':')))
page = page.replace('__SOURCE__', html.escape(plan_path.name))
out_path.write_text(page)
print(out_path, f'{out_path.stat().st_size/1024:.0f} KB', totals)
