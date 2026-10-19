#!/usr/bin/env python

"""Carry an existing plan forward to the plant's current position without
re-deciding it. See DESIGN.md."""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from swmtplanner.products import BeamSetDesc
from swmtplanner.schedule import assign_sets, UnhungAssignments
from swmtplanner.planners.infinite.run import load_config
from swmtplanner.planners.infinite.costing import Costing
from swmtplanner.planners.infinite.loop import PlanReport, build_report
from swmtplanner.planners.infinite.state import State
from swmtplanner.planners.infinite.report import write_plan_report_xlsx
from swmtplanner.planners.infinite.schedule_json import PLANT_TZ, write_schedule_json
from swmtplanner.planners.manual import ManualSchedule

__all__ = [
    'Ticket', 'PriorJob', 'Position', 'HangRecord', 'RetimeResult',
    'read_tickets', 'prior_jobs', 'locate', 'retime',
]

_TICKET_KEYS = ('ticket_no', 'ticket')
_TIME_KEYS = ('doff_ts', 'scan_ts', 'ts', 'time', 'timestamp')
_STYLE_KEYS = ('style', 'item', 'variant')


def _norm_id(machine_id: str) -> str:
    """`02` -> `O2`, `N01` -> `N1` (the machines file's normalisation)."""
    s = str(machine_id).strip().upper()
    if re.fullmatch(r'0\d+', s):
        s = 'O' + s[1:]
    m = re.fullmatch(r'([A-Z]+)0*(\d+)', s)
    return f'{m.group(1)}{int(m.group(2))}' if m else s


def _local(stamp: str) -> datetime:
    """A schedule-JSON time (UTC with offset) or a ticket time (plant local,
    naive) as a naive plant-local datetime."""
    t = datetime.fromisoformat(str(stamp).strip())
    if t.tzinfo is not None:
        t = t.astimezone(PLANT_TZ).replace(tzinfo=None)
    return t


# ----- inputs ----------------------------------------------------------------

@dataclass(frozen=True)
class Ticket:
    """One doffed roll: the ticket, its machine, when it was scanned, the
    plant's style name and the planner master it resolves to (None when it
    resolves to nothing)."""
    ticket: str
    machine: str
    time: datetime
    style: str
    item: str | None


def _first(d: Mapping[str, Any], keys: Iterable[str]) -> Any:
    for k in keys:
        if d.get(k) not in (None, ''):
            return d[k]
    return None


def read_tickets(path: 'str | Path', machines: Iterable[str],
                 variant_masters: Mapping[str, str] | None,
                 greige_ids: Iterable[str]) -> tuple[dict[str, list[Ticket]], int]:
    """The doffed-rolls file grouped by machine (each list in time order),
    for the machines named; tickets of other machines are dropped and
    counted (the second value). The file is an object keyed by machine id
    (`{"A02": [{"ticket_no", "style", "lbs", "doff_ts"}, ...], ...}`); a
    flat list of such records, the machine read off the ticket prefix, is
    accepted too. A style resolves to a master through `variant_masters`,
    or is a master id itself."""
    with open(path) as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        records = [(key, rec) for key, lst in data.items() for rec in (lst or ())]
    elif isinstance(data, list):
        records = [(None, rec) for rec in data]
    else:
        raise ValueError(f'{path}: expected a JSON object keyed by machine, or a list of tickets')
    want = set(machines)
    masters = set(greige_ids)
    vm = variant_masters or {}
    out: dict[str, list[Ticket]] = {m: [] for m in want}
    ignored = 0
    for key, rec in records:
        if not isinstance(rec, dict) or _first(rec, _TICKET_KEYS) is None:
            raise ValueError(f'{path}: every roll needs a ticket number, got {rec!r}')
        ticket = str(_first(rec, _TICKET_KEYS)).strip()
        machine = _norm_id(key if key is not None else ticket.split('-', 1)[0])
        if machine not in want:
            ignored += 1
            continue
        stamp = _first(rec, _TIME_KEYS)
        style = _first(rec, _STYLE_KEYS)
        if stamp is None or style is None:
            raise ValueError(f'{path}: ticket {ticket!r} needs a doff time and a style')
        style = str(style).strip()
        item = vm.get(style) or (style if style in masters else None)
        out[machine].append(Ticket(ticket, machine, _local(stamp), style, item))
    for lst in out.values():
        lst.sort(key=lambda t: t.time)
    return out, ignored


@dataclass
class PriorJob:
    """One job of the prior plan on a machine: its item, the order it was
    raised for, its roll count, when it started, and the set numbers its
    hangs mounted per bar in hang order (an invented `NEW…` set is None)."""
    job_id: str
    item: str
    order: str | None
    rolls: int
    start: datetime
    top: tuple[str | None, ...] = ()
    btm: tuple[str | None, ...] = ()
    # The target order's due date, when the JSON carries one (plant local).
    due_date: datetime | None = None
    # The item the job's opening changeover changed from, when it has one:
    # how `locate` tells the plan's own first change from a wrong style.
    opens_from: str | None = None


_CHANGES = ('StyleChange', 'RunnerChange', 'PatternChange')


def prior_jobs(plan: list[dict], machines: Iterable[str]) -> dict[str, list[PriorJob]]:
    """The prior plan's jobs per machine (chronological), for the machines
    named; a machine the plan does not have gets an empty list."""
    out: dict[str, list[PriorJob]] = {m: [] for m in machines}
    for m in plan:
        mid = _norm_id(m['id'])
        if mid not in out:
            continue
        jobs = sorted((e for e in m.get('schedule', ()) if e.get('kind') == 'job'),
                      key=lambda e: e['start'])
        for j in jobs:
            top: list[str | None] = []
            btm: list[str | None] = []
            opens_from: str | None = None
            for a in j.get('activities', ()):
                if opens_from is None and a.get('kind') in _CHANGES:
                    opens_from = str(a['from_item']) if a.get('from_item') else None
                if a.get('kind') != 'Hanging':
                    continue
                for bar, lst in (('top', top), ('btm', btm)):
                    b = a.get(f'{bar}_beam')
                    if b is not None:
                        s = str(b['set_no'])
                        lst.append(None if s.startswith('NEW') else s)
            out[mid].append(PriorJob(
                job_id=str(j['id']), item=str(j['item']), order=j.get('tgt_order'),
                rolls=len(j.get('rolls', ())), start=_local(j['start']),
                top=tuple(top), btm=tuple(btm),
                due_date=_local(j['due_date']) if j.get('due_date') else None,
                opens_from=opens_from))
    return out


# ----- where each machine is -------------------------------------------------

@dataclass
class Position:
    """Where a machine stands against its prior plan after the tickets and
    the load's run-up are applied, and what is left to replay."""
    machine: str
    status_item: str
    tickets: int = 0                      # tickets from the prior start to the status
    after_status: int = 0                 # tickets scanned after the status (ignored)
    consumed: int = 0                     # prior rolls accounted for
    run_up_rolls: int = 0                 # rolls the load's run-up produced
    extra: list[str] = field(default_factory=list)      # tickets for extra rolls of a style
    extra_in_progress: bool = False       # the status's roll is an extra one
    early: list[str] = field(default_factory=list)      # rolls dropped by an early change
    wrong_style: str | None = None        # how the machine left the plan, if it did
    finished: bool = False                # the plan had nothing left for it
    in_progress_order: str | None = None  # the order of the roll the run-up finishes
    opening_change: bool = False          # the plan's own first move is a changeover
    remaining: list[PriorJob] = field(default_factory=list)

    @property
    def replayable(self) -> bool:
        return self.wrong_style is None and bool(self.remaining)


def locate(machine: str, jobs: list[PriorJob], tickets: list[Ticket],
           prior_start: datetime, status_at: datetime, status_item: str,
           run_up_rolls: int, roll_in_progress: bool) -> Position:
    """Walk the machine's tickets — those scanned from `prior_start` up to
    the status snapshot at `status_at`; later ones are the future the
    status already describes — and then the load's run-up rolls against
    the prior plan's rolls — see "Where each machine is" in DESIGN.md."""
    pos = Position(machine, status_item, run_up_rolls=run_up_rolls)
    rolls = [(i, j.item, j.order) for i, j in enumerate(jobs) for _ in range(j.rolls)]
    at = 0
    last_item: str | None = None

    def consume() -> None:
        nonlocal at, last_item
        last_item = rolls[at][1]
        at += 1

    def next_job_item() -> str | None:
        """The item of the job after the one the next scheduled roll is in."""
        if at >= len(rolls):
            return None
        nxt = rolls[at][0] + 1
        return jobs[nxt].item if nxt < len(jobs) else None

    def change_early(because: str) -> None:
        """The floor moved on to the next job before finishing this one:
        drop the rest of this job's rolls and go on from the next job."""
        nonlocal at
        cur = rolls[at][0]
        n = 0
        while at < len(rolls) and rolls[at][0] == cur:
            at += 1
            n += 1
        pos.early.append(f'{n} roll(s) of {jobs[cur].item} ({jobs[cur].order or "no order"}) '
                         f'dropped: {because}')

    for t in tickets:
        if t.time < prior_start:
            continue
        if t.time > status_at:
            pos.after_status += 1
            continue
        pos.tickets += 1
        if at < len(rolls) and t.item == rolls[at][1]:
            consume()
        elif t.item is not None and t.item == last_item:
            pos.extra.append(t.ticket)
        elif t.item is not None and t.item == next_job_item():
            change_early(f'changed early, first seen at ticket {t.ticket} '
                         f'({t.time:%m-%d %H:%M})')
            consume()
        else:
            pos.wrong_style = (f'ticket {t.ticket} ({t.style}) at {t.time:%m-%d %H:%M}: '
                               f'the plan expected '
                               f'{rolls[at][1] if at < len(rolls) else "nothing more"}')
            break
    if pos.wrong_style is None:
        # The status: the machine is on `status_item`, with a roll in
        # progress or between rolls.
        next_item = rolls[at][1] if at < len(rolls) else None
        if (next_item is not None and status_item != next_item
                and status_item != last_item and status_item == next_job_item()):
            change_early('changed early per the status')
            next_item = rolls[at][1] if at < len(rolls) else None
        if next_item is None:
            pos.finished = True
        elif status_item == next_item:
            # The load's run-up finished the roll in progress and may have
            # run whole rolls to the change date: each is a scheduled roll.
            for _ in range(run_up_rolls):
                if at < len(rolls) and rolls[at][1] == status_item:
                    if pos.in_progress_order is None and roll_in_progress:
                        pos.in_progress_order = rolls[at][2]
                    consume()
                else:
                    break
            pos.finished = at >= len(rolls)
        elif status_item == last_item:
            pos.extra_in_progress = roll_in_progress
            if run_up_rolls > (1 if roll_in_progress else 0):
                pos.extra.append(f'run-up ({run_up_rolls} roll(s) of {status_item})')
        elif (at == 0 and pos.tickets == 0 and run_up_rolls == 0
              and (prior_start >= status_at or jobs[0].opens_from == status_item)):
            # The plan's own opening changeover — see "Where each machine is"
            # in DESIGN.md: nothing accounted for, and the plan either starts
            # at this status or says it changed from the status item.
            pos.opening_change = True
        else:
            pos.wrong_style = (f'the status says {status_item}; the plan expected '
                               f'{next_item} (after {last_item or "nothing"})')
    pos.consumed = at
    if pos.wrong_style is None and not pos.finished:
        left: dict[int, int] = {}
        for i, _item, _order in rolls[at:]:
            left[i] = left.get(i, 0) + 1
        for i, n in left.items():
            j = jobs[i]
            pos.remaining.append(PriorJob(j.job_id, j.item, j.order, n, j.start, j.top, j.btm))
    return pos


# ----- replay ----------------------------------------------------------------

@dataclass(frozen=True)
class HangRecord:
    """One hang of the retimed plan: where and when, the bar's requirement,
    the set hung and its source (`queued` by the plant, `stock` from the
    second pass, `new` when stock had nothing), the plan's pounds and the
    real set's, how far the set falls short of what the plan draws before
    the bar's next hang, and the set the prior plan had at this hang
    (`None` for an invented one; `no_prior` when the prior job had fewer
    hangs on the bar)."""
    machine: str
    bar: str
    at: datetime
    desc: str
    hung: str
    source: str
    plan_lbs: float
    set_lbs: float | None
    short_by: float
    prior: str | None
    no_prior: bool = False
    note: str = ''
    """With `keep_sets`, why the prior set was not kept (invented; named by
    an earlier step; not in the new inventory; the planner's refusal); in a
    later round, why an assigned set was dropped from this hang."""
    rolls: int = 0
    """The whole rolls the schedule doffs from the set on this bar — the
    rolls whose last knit names it; a roll that straddles a swap counts
    for the set it finishes on."""


@dataclass
class RetimeResult:
    report: PlanReport
    start_date: datetime
    positions: dict[str, Position]
    steps: list[tuple[str, str, int, str | None]]      # (machine, item, rolls, order) replayed
    hangs: list[HangRecord]
    failures: list[str]
    tickets_ignored: int
    not_in_plan: list[str]
    rounds: int = 1
    """How many replay-and-assign rounds the re-timing took (see "Re-timing
    on the real pounds" in DESIGN.md)."""
    withheld: list[str] = field(default_factory=list)
    """Sets a round assigned that the next round's replay could not hang
    (not yet back in stock when the step was staged), kept out of the later
    rounds' pool; still free stock for the floor."""


# The cap on re-timing rounds: a round replays the steps with the sets the
# previous round assigned, then assigns stock to the hangs the new timing
# left open; the loop stops sooner when a round assigns nothing.
MAX_ROUNDS = 6


def _usable(name: str | None, label: str, state: State, used: set[str],
            queued: set[str], machine: 'Any' = None) -> tuple[str | None, str]:
    """With `keep_sets`: a prior hang's set name kept when the stock can
    still supply it for the bar's `label` — or the plant has it queued on
    that bar (`queued`) — else None with the reason: the set was invented,
    an earlier step named it, or the new inventory does not have it (gone,
    or taken by the load's run-up)."""
    if name is None:
        return None, 'invented'
    if name in used:
        return None, 'named by an earlier step'
    if name in queued:
        return name, ''
    stock = state.inventory.get(BeamSetDesc(label).physical, ())
    found = next((b for b in stock if b.set_no == name), None)
    if found is None:
        return None, 'not in the new inventory'
    if machine is not None and not machine.accepts(found):
        return None, 'too large for the machine'
    return name, ''


def retime(config: 'str | Path', prior_plan: 'str | Path', tickets: 'str | Path',
           *, keep_sets: bool = False,
           echo: Callable[[str], Any] = lambda _s: None) -> RetimeResult:
    """Load the config as `plan infinite` does, locate every machine against
    the prior plan with the tickets, replay what is left through the manual
    planner (placeholders for every hang, or with `keep_sets` the prior
    plan's sets where still usable), hand the inventory out to the
    placeholders in runout order, and report the state."""
    _cfg, inputs = load_config(Path(config), echo=echo)
    # Pass one plans in a restricted stock mode: every hang the steps need
    # invents a placeholder with the default pounds (the plant's queued
    # sets aside) — or, with keep_sets, hangs the prior set it names; the
    # inventory left is handed out afterwards, in runout order (see
    # DESIGN.md, "Two passes over the sets").
    state = State(
        machines=inputs.machines, rls_items=inputs.rls_items,
        start_date=inputs.start_date, window_end=inputs.start_date,
        inventory=inputs.inventory, capacity=inputs.capacity,
    )
    ms = ManualSchedule(state, stock='named' if keep_sets else 'none')
    with open(prior_plan) as fh:
        plan = json.load(fh)
    if not isinstance(plan, list):
        raise ValueError(f'{prior_plan}: expected a schedule JSON list')
    prior_start = min((_local(j['start']) for m in plan for j in m.get('schedule', ())
                       if j.get('kind') == 'job' and j.get('start')), default=inputs.start_date)
    jobs = prior_jobs(plan, state.machines)
    tix, ignored = read_tickets(tickets, state.machines, inputs.variant_masters,
                                inputs.greige_by_id)

    positions: dict[str, Position] = {}
    not_in_plan: list[str] = []
    for mid, m in state.machines.items():
        if not jobs[mid]:
            not_in_plan.append(mid)
        s = m.current_status
        # The load ran the machine up to the change date: its jobs are the
        # roll that was in progress (a short first roll) and any whole rolls
        # that followed.
        run_up = sum(len(j.rolls) for j in m.jobs)
        in_progress = False
        if m.jobs and m.jobs[0].rolls:
            first = m.jobs[0].rolls[0]
            wound = sum(k.lbs for k in first.knits)
            in_progress = wound < m.jobs[0].item.tgt_wt - 1e-6
        positions[mid] = locate(
            mid, jobs[mid], tix[mid], prior_start, inputs.start_date, s.current_item.id,
            run_up_rolls=run_up, roll_in_progress=in_progress)
        if jobs[mid]:
            echo(f'{mid}: {positions[mid].tickets} ticket(s), {positions[mid].consumed} roll(s) '
                 f'accounted for, {sum(j.rolls for j in positions[mid].remaining)} left')

    # Steps in the prior plan's order across machines.
    queue = sorted(((j.start, mid, j) for mid, p in positions.items() if p.replayable
                    for j in p.remaining), key=lambda x: (x[0], x[1]))

    # Rounds (see "Re-timing on the real pounds" in DESIGN.md): each replays
    # the steps with the sets the previous round assigned named at their
    # hangs, then assigns stock to the hangs the new timing left open; the
    # loop stops when a round assigns nothing more.
    names: dict[tuple[str, str, str], list[str | None]] = {}   # (machine, job, bar) -> hang names
    notes: dict[tuple[str, str, str], list[str]] = {}          # round one's keep-sets notes
    prior_kept: set[str] = set()
    withheld: set[str] = set()      # sets refused at their hang: kept out of later rounds' pool
    rounds = 0
    while True:
        rounds += 1
        if rounds > 1:
            _cfg, inputs = load_config(Path(config), echo=lambda _s: None)
            state = State(
                machines=inputs.machines, rls_items=inputs.rls_items,
                start_date=inputs.start_date, window_end=inputs.start_date,
                inventory=inputs.inventory, capacity=inputs.capacity,
            )
            ms = ManualSchedule(state, stock='named')
        steps, hangs, failures, job_hangs, dropped, why_by_job, refused = _replay(
            ms, state, inputs, queue, names, keep_sets and rounds == 1, prior_kept, notes)
        if rounds == 1:
            notes = why_by_job
        withheld |= refused
        pool = {k: [b for b in v if b.set_no not in withheld]
                for k, v in state.inventory.items()} if withheld else state.inventory
        assignment = assign_sets(state.machines, pool, now=inputs.start_date)
        by_hang = {(a.machine, a.bar, a.at): a for a in assignment.hangs if a.hung is not None}
        for i, h in enumerate(hangs):
            a = by_hang.get((h.machine, h.bar, h.at))
            if a is None:
                continue
            hangs[i] = HangRecord(h.machine, h.bar, h.at, h.desc, a.hung.set_no, 'stock',
                                  a.plan_lbs, a.set_lbs, a.short_by, h.prior, h.no_prior, h.note)
        echo(f'round {rounds}: {len(by_hang)} set(s) assigned from stock'
             + (f', {dropped} name(s) dropped' if dropped else ''))
        if not by_hang or rounds >= MAX_ROUNDS:
            break
        # The next round names every set this one hung from stock (or kept
        # from the prior plan), per job and bar in hang order.
        names = {}
        for (mid, job_id), rows in job_hangs.items():
            for bar in ('top', 'btm'):
                mine = sorted((r for r in rows if r['bar'] == bar), key=lambda r: r['queue_idx'])
                lst: list[str | None] = []
                for r in mine:
                    h = next((x for x in hangs if (x.machine, x.bar, x.at) == (mid, bar, r['at'])), None)
                    lst.append(h.hung if h is not None and h.source in ('stock', 'assigned') else None)
                if any(n is not None for n in lst):
                    names[(mid, job_id, bar)] = lst

    # Rolls off each set: the rolls doffed from it on that bar — those whose
    # last knit names it (a roll that straddles a swap counts for the set it
    # finishes on).
    for i, h in enumerate(hangs):
        n = 0
        for job in state.machines[h.machine].jobs:
            for roll in job.rolls:
                if not roll.knits:
                    continue
                last = roll.knits[-1].top_beam if h.bar == 'top' else roll.knits[-1].btm_beam
                if last is not None and last.set_no == h.hung:
                    n += 1
        hangs[i] = HangRecord(h.machine, h.bar, h.at, h.desc, h.hung, h.source, h.plan_lbs,
                              h.set_lbs, h.short_by, h.prior, h.no_prior, h.note, rolls=n)
    hangs.sort(key=lambda h: (h.at, h.machine, h.bar))
    report = build_report(state, Costing(inputs.weights))
    return RetimeResult(report, inputs.start_date, positions, steps, hangs, failures,
                        ignored, not_in_plan, rounds, sorted(withheld))


_REFUSED = re.compile(r"assigned set '(?P<name>[^']+)' \((?P<bar>top|btm)\)")


def _replay(ms: ManualSchedule, state: State, inputs: Any, queue: list,
            names: Mapping[tuple[str, str, str], list[str | None]], keep_prior: bool,
            prior_kept: set[str], notes: Mapping[tuple[str, str, str], list[str]] = {}):
    """One round's replay of the steps in `queue` through `ms`: each step
    names the sets `names` gives its job (or, with `keep_prior`, the prior
    plan's sets where still usable, which are then remembered in
    `prior_kept`), dropping a name the planner cannot hang — a surplus one
    the re-timed plan has no hang for (`UnhungAssignments`), or one refused
    as unavailable or taken — and re-staging without it. A later round takes
    `notes` (round one's reasons a prior set was not kept) for the hangs it
    leaves unnamed. Returns the steps replayed, their `HangRecord`s, the
    failures, the hang rows per job, the count of names dropped, the notes
    per job and bar, and the names refused as unavailable or taken (for the
    caller to withhold from later rounds)."""
    steps: list[tuple[str, str, int, str | None]] = []
    hangs: list[HangRecord] = []
    failures: list[str] = []
    job_hangs: dict[tuple[str, str], list[dict]] = {}
    why_by_job: dict[tuple[str, str, str], list[str]] = {}
    refused: set[str] = set()
    dead: set[str] = set()
    used: set[str] = set()
    dropped = 0
    for _start, mid, job in queue:
        if mid in dead:
            continue
        greige = inputs.greige_by_id.get(job.item)
        if greige is None:
            failures.append(f'{mid}: {job.item} is not a style in this config')
            dead.add(mid); continue
        cfg = greige.configuration
        bar_names: dict[str, list[str | None]] = {'top': [], 'btm': []}
        why: dict[str, list[str]] = {'top': [], 'btm': []}
        if keep_prior:
            for bar, prior, label in (('top', job.top, cfg.top_beam), ('btm', job.btm, cfg.btm_beam)):
                queued = {b.set_no for b in state.machines[mid].current_status.queue(bar)}
                for name in prior:
                    kept, reason = _usable(name, label, state, used, queued,
                                           state.machines[mid])
                    bar_names[bar].append(kept); why[bar].append(reason)
                    if kept is not None:
                        used.add(kept); prior_kept.add(kept)
        else:
            for bar in ('top', 'btm'):
                bar_names[bar] = list(names.get((mid, job.job_id, bar), ()))
                # Round one's note on a hang (why the prior set was not
                # kept) stands whatever a later round hangs there.
                old = list(notes.get((mid, job.job_id, bar), ()))
                why[bar] = old + [''] * max(0, len(bar_names[bar]) - len(old))

        def drop(bar: str, name: str, reason: str) -> None:
            nonlocal dropped
            for i, n in enumerate(bar_names[bar]):
                if n == name:
                    bar_names[bar][i] = None; why[bar][i] = reason
                    used.discard(name); dropped += 1
                    return

        try:
            for _attempt in range(1 + sum(len(v) for v in bar_names.values())):
                try:
                    ms.rolls(mid, job.item, job.rolls, 'schedule_tail',
                             bar_names['top'], bar_names['btm'], order=job.order)
                    break
                except UnhungAssignments as e:
                    for bar, lst in e.leftover.items():
                        for name in lst:
                            drop(bar, name, 'no hang for it in the re-timed plan')
                except ValueError as e:
                    m = _REFUSED.search(str(e))
                    if m is None or not any(n is not None for n in bar_names['top'] + bar_names['btm']):
                        raise
                    refused.add(m.group('name'))
                    drop(m.group('bar'), m.group('name'), f'assignment refused ({e})')
            else:
                raise ValueError('could not stage the step with or without its names')
        except (ValueError, KeyError) as e:
            failures.append(f'{mid}: {job.item} x{job.rolls}: {e}')
            dead.add(mid); continue
        rows = ms.runouts(mid)
        job_hangs[(mid, job.job_id)] = rows
        for bar in ('top', 'btm'):
            why_by_job[(mid, job.job_id, bar)] = list(why[bar])
        for row in rows:
            bar, i = row['bar'], row['queue_idx']
            prior = job.top if bar == 'top' else job.btm
            source = row['source']
            if source == 'assigned' and row['auto'] not in prior_kept:
                source = 'stock'                   # named from a previous round
            hangs.append(HangRecord(
                mid, bar, row['at'], row['desc'], row['auto'], source,
                row['lbs'], None if source == 'new' else row['lbs'], 0.0,
                prior[i] if i < len(prior) else None, no_prior=i >= len(prior),
                note=why[bar][i] if i < len(why[bar]) else ''))
        ms.commit(mid)
        steps.append((mid, job.item, job.rolls, job.order))
    return steps, hangs, failures, job_hangs, dropped, why_by_job, refused


def retime_text(result: RetimeResult) -> str:
    """The retime report (`retime_<date>.txt`)."""
    lines = ['RETIME REPORT', '']
    lines.append(f'tickets from machines outside the config ignored: {result.tickets_ignored}')
    if result.not_in_plan:
        lines.append(f'machines not in the prior plan (left at status): '
                     f'{", ".join(sorted(result.not_in_plan))}')
    lines += ['', 'POSITIONS', '']
    for mid, p in sorted(result.positions.items()):
        if mid in result.not_in_plan:
            continue
        left = sum(j.rolls for j in p.remaining)
        state = ('WRONG STYLE' if p.wrong_style else 'finished' if p.finished
                 else f'{left} roll(s) in {len(p.remaining)} job(s) left')
        lines.append(f'{mid:4} on {p.status_item:12} tickets {p.tickets:3}  accounted {p.consumed:3}'
                     f'  run-up {p.run_up_rolls:2}  {state}'
                     + (f'  ({p.after_status} ticket(s) after the status ignored)' if p.after_status else ''))
    dev = []
    for mid, p in sorted(result.positions.items()):
        if p.wrong_style:
            dev.append(f'{mid}: on a style the plan never put there — {p.wrong_style}; not replayed')
        for t in p.extra:
            dev.append(f'{mid}: extra roll of {p.status_item if p.extra_in_progress else "the previous style"}: {t}')
        for e in p.early:
            dev.append(f'{mid}: {e}')
        if p.extra_in_progress:
            dev.append(f'{mid}: an extra roll of {p.status_item} in progress; the style change follows it')
        if p.finished:
            dev.append(f'{mid}: the floor finished everything the plan had; left at status')
        if p.in_progress_order:
            dev.append(f'{mid}: the roll in progress was for {p.in_progress_order}; finished as a run-up roll')
        if p.opening_change:
            dev.append(f'{mid}: the plan opens with a change from {p.status_item}; at its first roll')
    lines += ['', 'DEVIATIONS', ''] + (dev or ['none'])
    real = [h for h in result.hangs if h.source != 'new']
    still_new = [h for h in result.hangs if h.source == 'new']
    lines += ['', f'SET ASSIGNMENTS (every hang in time order; pounds on the set the schedule '
              f'is timed on; {result.rounds} re-timing round(s))', '']
    if result.withheld:
        lines.append(f'held back from assignment (not back in stock when the hang they were '
                     f'given was staged): {", ".join(result.withheld)}')
        lines.append('')
    if real:
        for h in real:
            prior = 'no prior hang' if h.no_prior else f'prior {h.prior or "NEW"}'
            lbs = (f'{h.set_lbs:.0f} / {h.plan_lbs:.0f} lbs'
                   if h.set_lbs is not None else f'{h.plan_lbs:.0f} lbs')
            short = f'  SHORT BY {h.short_by:.0f} lbs' if h.short_by > 0 else ''
            note = f'; {h.note}' if h.note else ''
            lines.append(f'{h.machine:4} {h.bar:3} {h.at:%m-%d %H:%M}  {h.desc:22} '
                         f'hung {h.hung:12} [{h.source}]  {lbs}  rolls {h.rolls:2}{short}  ({prior}{note})')
    else:
        lines.append('none')
    lines += ['', f'STILL INVENTED (no stock for the bar): {len(still_new)} hang(s)', '']
    for h in still_new:
        note = f'  (prior {h.prior}; {h.note})' if h.note and h.prior else ''
        lines.append(f'{h.machine:4} {h.bar:3} {h.at:%m-%d %H:%M}  {h.desc:22} {h.hung}  '
                     f'rolls {h.rolls:2}{note}')
    by_machine = result.report.queue_passed_over if result.report is not None else {}
    passed = [(mid, p) for mid, ps in sorted(by_machine.items()) for p in ps]
    lines += ['', 'ASSIGNED SETS PASSED OVER (did not fit the bar at the hang, or blacklisted)', '']
    for mid, p in passed:
        lines.append(f'{mid:4} {p.bar:3} {p.at:%m-%d %H:%M}  set {p.beam_set.set_no} '
                     f'({p.beam_set.desc.id}, merge {p.beam_set.merge or "?"})  '
                     f'bar needed {p.wanted.physical.id}  {p.reason}')
    if not passed:
        lines.append('none')
    lines += ['', 'STEPS REPLAYED', '']
    for mid, item, n, order in result.steps:
        lines.append(f'{mid:4} {item:12} x{n:3}  {order or "-"}')
    lines += ['', 'FAILURES', ''] + (result.failures or ['none'])
    return '\n'.join(lines) + '\n'


def write_outputs(result: RetimeResult, output_dir: Path, start_date: datetime,
                  echo: Callable[[str], Any] = lambda _s: None) -> tuple[Path, Path, Path]:
    """`knit_plan_<date>.xlsx` / `.json` (the `_<n>` suffix when taken) and
    `retime_<date>.txt` in `output_dir`."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = start_date.strftime('%Y%m%d')
    xlsx = output_dir / f'knit_plan_{stamp}.xlsx'
    idx = 1
    while xlsx.exists():
        idx += 1
        stamp = f'{start_date.strftime("%Y%m%d")}_{idx}'
        xlsx = output_dir / f'knit_plan_{stamp}.xlsx'
    echo(f'Writing report to {xlsx}')
    write_plan_report_xlsx(result.report, xlsx)
    js = xlsx.with_suffix('.json')
    echo(f'Writing schedule JSON to {js}')
    write_schedule_json(result.report, js)
    txt = output_dir / f'retime_{stamp}.txt'
    txt.write_text(retime_text(result))
    echo(f'Retime report in {txt}')
    return xlsx, js, txt
