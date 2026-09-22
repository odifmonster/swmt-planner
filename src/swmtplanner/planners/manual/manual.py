#!/usr/bin/env python

"""Manual scheduling — see `planners/manual/DESIGN.md`."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, TYPE_CHECKING

from swmtplanner.products import BeamSetDesc
from swmtplanner.schedule import Hanging
from swmtplanner.planners.infinite.state import Move, State
from swmtplanner.planners.infinite.run import load_config
from swmtplanner.planners.infinite.schedule_json import (
    machines_schedule_json, write_machines_schedule_json,
)

if TYPE_CHECKING:
    from swmtplanner.products import BeamSet
    from swmtplanner.schedule import Inventory, InventoryView, Machine, ProductionPlan

__all__ = ['Step', 'ManualSchedule']

StartAt = Literal['schedule_tail', 'next_runout']


@dataclass(frozen=True)
class Step:
    """One committed manual move: `rolls` whole rolls of `item` on `machine`,
    at the schedule tail or after the current beams run out, with the set
    numbers to hang on each bar (in hang order)."""
    machine: str
    item: str
    rolls: int
    at: StartAt = 'schedule_tail'
    # Set numbers per hang, in hang order; None leaves that hang to the
    # machine's own queue / stock (JSON null).
    top: tuple[str | None, ...] = ()
    btm: tuple[str | None, ...] = ()

    def to_json(self) -> dict[str, Any]:
        d: dict[str, Any] = {'machine': self.machine, 'item': self.item,
                             'rolls': self.rolls, 'at': self.at}
        if self.top:
            d['top'] = list(self.top)
        if self.btm:
            d['btm'] = list(self.btm)
        return d

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> 'Step':
        return cls(
            machine=str(d['machine']), item=str(d['item']), rolls=int(d['rolls']),
            at=d.get('at', 'schedule_tail'),
            top=tuple(d.get('top', ())), btm=tuple(d.get('btm', ())),
        )


class ManualSchedule:
    """Build a schedule by hand on the planner's `State`: stage a move per
    machine with `rolls`, inspect the plans, `commit` (or `discard`) one or
    all, and write the result as schedule JSON. See DESIGN.md."""

    def __init__(self, state: State) -> None:
        self._state = state
        self._steps: list[Step] = []
        # Staged plans by machine, in staging order (dicts keep insertion order).
        self._staged: dict[str, tuple[Step, Move]] = {}

    @classmethod
    def from_config(cls, config: 'str | Path', *, quiet: bool = True) -> 'ManualSchedule':
        """Load a run-config the way `plan infinite` does and start from its
        machines, inventory and demand."""
        echo = (lambda _s: None) if quiet else print
        _cfg, inputs = load_config(Path(config), echo=echo)
        state = State(
            machines=inputs.machines, rls_items=inputs.rls_items,
            start_date=inputs.start_date, window_end=inputs.start_date,
            inventory=inputs.inventory,
        )
        return cls(state)

    # ----- read side -----------------------------------------------------

    @property
    def state(self) -> State:
        return self._state

    @property
    def machines(self) -> Mapping[str, 'Machine']:
        return self._state.machines

    @property
    def inventory(self) -> 'Inventory':
        return self._state.inventory

    @property
    def steps(self) -> tuple[Step, ...]:
        return tuple(self._steps)

    @property
    def staged(self) -> Mapping[str, 'ProductionPlan']:
        """The staged plans by machine, in staging order."""
        return {m: move.plan for m, (_step, move) in self._staged.items()}

    def pending(self) -> list[dict[str, Any]]:
        """Where each machine stands: current item, schedule tail, predicted
        next runout and the whole rolls doffed before it
        (`rolls_before_runout`, `Machine.whole_rolls_before_runout`), lbs left
        on the roll in progress, each bar's set, lbs remaining and queue, and
        whether a plan is staged on it."""
        out = []
        for m_id, m in self._state.machines.items():
            s = m.current_status
            row: dict[str, Any] = {
                'machine': m_id, 'item': s.current_item.id,
                'schedule_tail': m.schedule_tail, 'next_runout': m.next_runout,
                'rolls_before_runout': m.whole_rolls_before_runout,
                'roll_lbs_remaining': round(s.roll_lbs_remaining, 1),
                'jobs': len(m.jobs), 'staged': m_id in self._staged,
            }
            for bar in ('top', 'btm'):
                b = s.beam(bar)
                row[f'{bar}_set'] = None if b is None else b.set_no
                row[f'{bar}_desc'] = None if b is None else b.desc.id
                row[f'{bar}_lbs'] = round(s.lbs_remaining(bar), 1)
                row[f'{bar}_queue'] = [q.set_no for q in s.queue(bar)]
            out.append(row)
        return out

    def stock(self, desc: str, at: datetime | None = None) -> list['BeamSet']:
        """Stock sets that fit the beam-set label `desc` (`S/L` or not), are
        available at `at` (default: the start date) and are not assigned by
        hand in any staged plan, oldest received first then by set number —
        the order the warehouse wants them pulled. A set another staging
        picked automatically is still listed: assigning it moves that pick
        on (see `rolls`)."""
        want = BeamSetDesc(desc)
        when = at or self._state.start_date
        held = {s for s, (_m, manual) in self._holds().items() if manual}
        sets = [b for b in self._state.inventory.get(want.physical, ())
                if b.available_at(when) and b.id not in held]
        return sorted(sets, key=lambda b: (b.avail_date.date(), b.set_no))

    # ----- write side ----------------------------------------------------

    def rolls(
        self, machine: str, item: str, n: int, at: StartAt = 'schedule_tail',
        top: Iterable[str | None] = (), btm: Iterable[str | None] = (),
    ) -> 'ProductionPlan':
        """Plan `n` rolls of `item` on `machine` and stage it, replacing any
        earlier staging on that machine (other machines' stagings stay). The
        plan is made against the committed inventory less the sets other
        staged plans hang — except that a set named here in `top` / `btm`
        is taken even if another staging had picked it **automatically**:
        that staging is re-planned and its automatic pick moves on to the
        next set. Naming a set another staging assigned *by hand* raises.
        Nothing is committed until `commit()`."""
        if n <= 0:
            raise ValueError(f'rolls must be positive, got {n}')
        greige = self._greige(item)
        if machine not in self._state.machines:
            raise KeyError(f'unknown machine {machine!r}')
        if not greige.can_run_on_mchn(machine):
            raise ValueError(f'{item!r} cannot run on machine {machine!r}')
        step = Step(machine, greige.id, int(n), at, tuple(top), tuple(btm))
        displaced = self._displaced_by(step)
        snapshot = dict(self._staged)
        try:
            self._stage(step, greige)
            for other in displaced:               # their auto picks move on
                o_step, _ = self._staged[other]
                self._stage(o_step, self._greige(o_step.item))
        except Exception:
            self._staged = snapshot
            raise
        return self._staged[machine][1].plan

    def runouts(self, machine: str | None = None) -> list[dict[str, Any]]:
        """The hang points — every place a staged plan mounts a set — of
        `machine`'s plan, or of every staged plan, chronologically across
        machines (so the list can be walked from the top, handing the next
        set to the next runout). Per hang: `machine`, `bar`, `at` (the
        hang's start), `desc` (the bar's
        requirement), the set coming off the bar (`prev_set`, `prev_merge`,
        `prev_vendor`; None when the bar held nothing), the set going on
        (`auto`: a stock set number or an invented `NEW…`, with `lbs` and
        `vendor`), `assigned` (whether this step named it in `assign` —
        also True for a plant-queued set the step confirmed by name),
        `source` (where the set came from: `queued` at the machine by the
        plant, `assigned` from stock by name, `stock` automatically, or
        `new`), `locked` (a plant-assigned set that a manual assignment
        cannot displace), `queue_idx` (the set's position in that
        bar's queue, for `assign`) and `options` — `(set_no, lbs, merge,
        vendor)` of the stock sets that fit and are available at that
        moment, oldest received first then by set number (the warehouse's
        pull order, as `stock()`), excluding sets this plan hangs earlier or
        another staging assigned by hand; just the queued set for a locked
        hang. Options another staging picked *automatically* are included
        and listed in `held_elsewhere` (`{set_no: machine}`): assigning one
        here moves that machine's pick on. Empty when nothing is staged."""
        if machine is not None:
            if machine not in self._staged:
                raise ValueError(f'nothing staged on {machine!r}')
            items = [(machine, self._staged[machine])]
        else:
            items = list(self._staged.items())
        out: list[dict[str, Any]] = []
        for m_id, (step, move) in items:
            out.extend(self._runouts_of(m_id, step, move))
        return sorted(out, key=lambda x: x['at'])

    def _runouts_of(self, m_id: str, step: Step, move: Move) -> list[dict[str, Any]]:
        plan = move.plan
        mchn = self._state.machines[m_id]
        # Sets other stagings assigned by hand are not options here; their
        # automatic picks are (assigning one moves that pick on), flagged in
        # `held_elsewhere`.
        holds = self._holds(exclude=m_id)
        taken_before: set[str] = {s for s, (_m, manual) in holds.items() if manual}
        auto_held = {s: m for s, (m, manual) in holds.items() if not manual}
        out: list[dict[str, Any]] = []
        idx = {'top': 0, 'btm': 0}
        status = mchn.current_status
        last_beam = {bar: status.beam(bar) for bar in ('top', 'btm')}
        for a in plan.activities:
            for bar in ('top', 'btm'):
                if status.beam(bar) is not None:
                    last_beam[bar] = status.beam(bar)
            if isinstance(a, Hanging):
                for bar in ('top', 'btm'):
                    bs = getattr(a, f'{bar}_beam')
                    if bs is None:
                        continue
                    queue = step.top if bar == 'top' else step.btm
                    i = idx[bar]
                    idx[bar] += 1
                    prev = last_beam[bar]
                    named = i < len(queue) and queue[i] is not None   # this step named it
                    if bs.assigned:
                        source = 'queued'            # staged at the machine by the plant
                    elif named:
                        source = 'assigned'          # pulled from stock by name
                    elif bs.is_new:
                        source = 'new'               # invented placeholder
                    else:
                        source = 'stock'
                    locked = source == 'queued'
                    if locked:
                        options = [bs]
                    else:
                        options = [
                            b for b in self._state.inventory.get(bs.desc.physical, ())
                            if b.available_at(a.start) and b.id not in taken_before
                        ]
                        options.sort(key=lambda b: (b.avail_date.date(), b.set_no))
                    out.append({
                        'machine': m_id, 'bar': bar, 'at': a.start, 'desc': bs.desc.id,
                        'prev_set': None if prev is None else prev.set_no,
                        'prev_merge': None if prev is None else prev.merge,
                        'prev_vendor': None if prev is None else prev.vendor,
                        'auto': bs.set_no, 'lbs': round(bs.lbs, 1), 'vendor': bs.vendor,
                        'assigned': named, 'source': source,
                        'locked': locked, 'queue_idx': i,
                        'options': [(b.set_no, round(b.lbs, 1), b.merge, b.vendor)
                                    for b in options],
                        'held_elsewhere': {b.set_no: auto_held[b.id]
                                           for b in options if b.id in auto_held},
                    })
                    if not bs.is_new:
                        taken_before.add(bs.id)
            status = status.apply_activity(a)
        return out

    def assignments(self, machine: str | None = None, *,
                    all_hangs: bool = False) -> dict[str, list[str | None]]:
        """A staged machine's set numbers per bar (`{'top': [...], 'btm':
        [...]}`) in hang order — the same lists `assign` appends to. By
        default just what this step assigned by hand (`None` where a hang
        was left to the machine's queue / stock, as in the step file); with
        `all_hangs=True` the set every hang of the staged plan actually
        mounts, whether assigned, queued by the plant, picked from stock or
        invented. `machine` may be omitted when exactly one plan is staged."""
        machine = self._one_staged(machine)
        step, _ = self._staged[machine]
        if not all_hangs:
            return {'top': list(step.top), 'btm': list(step.btm)}
        out: dict[str, list[str | None]] = {'top': [], 'btm': []}
        for r in self.runouts(machine):
            out[r['bar']].append(r['auto'])
        return out

    def assign(self, top: Iterable[str | None] = (),
               btm: Iterable[str | None] = (), *,
               machine: str | None = None,
               replace: bool = False) -> 'ProductionPlan':
        """Re-stage one machine's staged step with these set numbers queued
        for its hangs (in `runouts()` order per bar). By default the entries
        are **appended** to the bar's existing assignments, so consecutive
        calls hand out one set per hang as you walk down the runouts;
        `replace=True` redefines the bar's whole list instead. `machine` may
        be omitted when exactly one plan is staged. A `None` entry leaves
        that hang to the machine's own queue or stock — `top=[None,
        '3-0625']` keeps the plant's queued set for the first top hang and
        names the second. When appending, a bar given nothing keeps what it
        had; with `replace=True` each bar becomes exactly what is passed
        (nothing = automatic picks). Raises, and leaves the previous staging
        in place, if an assignment is unusable."""
        machine = self._one_staged(machine)
        step, _ = self._staged[machine]
        top, btm = tuple(top), tuple(btm)
        if not replace:
            top = step.top + top
            btm = step.btm + btm
        previous = dict(self._staged)
        try:
            return self.rolls(step.machine, step.item, step.rolls, step.at, top, btm)
        except Exception:
            self._staged = previous
            raise

    def commit(self, machine: str | None = None) -> list[Step]:
        """Commit `machine`'s staged plan, or every staged plan in staging
        order, through `State.commit_move`; returns the `Step`s committed."""
        if machine is not None:
            if machine not in self._staged:
                raise ValueError(f'nothing staged on {machine!r}')
            todo = [machine]
        else:
            if not self._staged:
                raise ValueError('nothing staged — call rolls() first')
            todo = list(self._staged)
        done: list[Step] = []
        for m_id in todo:
            step, move = self._staged.pop(m_id)
            self._state.commit_move(move)
            self._steps.append(step)
            done.append(step)
        return done

    def discard(self, machine: str | None = None) -> None:
        """Drop `machine`'s staged plan, or all of them."""
        if machine is None:
            self._staged.clear()
        else:
            self._staged.pop(machine, None)

    def replay(self, steps: Iterable[Step]) -> None:
        """`rolls` + `commit` each step in order."""
        for s in steps:
            self.rolls(s.machine, s.item, s.rolls, s.at, s.top, s.btm)
            self.commit(s.machine)

    # ----- output ----------------------------------------------------------

    def schedule_json(self) -> list[dict[str, Any]]:
        return machines_schedule_json(self._state.machines)

    def write_json(self, path: 'str | Path') -> None:
        write_machines_schedule_json(self._state.machines, path)

    def save_steps(self, path: 'str | Path') -> None:
        with open(path, 'w') as fh:
            json.dump([s.to_json() for s in self._steps], fh, indent=2)
            fh.write('\n')

    @staticmethod
    def load_steps(path: 'str | Path') -> list[Step]:
        with open(path) as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            raise TypeError(f'{path}: a step file is a JSON list of steps')
        return [Step.from_json(d) for d in data]

    # ----- helpers -------------------------------------------------------

    def _greige(self, item: str):
        for m in self._state.machines.values():
            g = m.current_status.current_item
            if g.id == item:
                return g
        for rls in self._state.rls_items.values():
            if rls.item.id == item:
                return rls.item
        raise KeyError(f'unknown greige item {item!r}')

    def _one_staged(self, machine: str | None) -> str:
        if machine is not None:
            if machine not in self._staged:
                raise ValueError(f'nothing staged on {machine!r}')
            return machine
        if not self._staged:
            raise ValueError('nothing staged — call rolls() first')
        if len(self._staged) > 1:
            raise ValueError(
                f'plans are staged on {sorted(self._staged)}; say which machine'
            )
        return next(iter(self._staged))

    def _holds(self, exclude: str | None = None) -> dict[str, tuple[str, bool]]:
        """The stock sets the staged plans (other than `exclude`) hang:
        `{set_no: (machine, manual)}`, `manual` True when that step named
        the set itself, False for an automatic pick."""
        out: dict[str, tuple[str, bool]] = {}
        for m_id, (step, move) in self._staged.items():
            if m_id == exclude:
                continue
            named = {s for s in step.top + step.btm if s is not None}
            for bs in move.plan.beam_sets_taken:
                out[bs.id] = (m_id, bs.id in named)
        return out

    def _stock_view(self, exclude: str, free: set[str]) -> 'InventoryView':
        """The committed inventory less the sets other staged plans hang,
        except those in `free` (sets this step names, which it may take from
        another staging's automatic pick)."""
        taken = set(self._holds(exclude=exclude)) - free
        if not taken:
            return self._state.inventory
        return {k: [b for b in v if b.id not in taken]
                for k, v in self._state.inventory.items()}

    def _displaced_by(self, step: Step) -> list[str]:
        """The other staged machines whose *automatic* pick `step` names (they
        must be re-planned after `step` is staged), in staging order. A set
        another staging assigned by hand is a conflict and raises."""
        holds = self._holds(exclude=step.machine)
        displaced: list[str] = []
        for bar, sets in (('top', step.top), ('btm', step.btm)):
            for set_no in sets:
                if set_no is None or set_no not in holds:
                    continue
                m_id, manual = holds[set_no]
                if manual:
                    raise ValueError(
                        f'set {set_no!r} ({bar}) is assigned by hand to the '
                        f'plan staged on {m_id}'
                    )
                if m_id not in displaced:
                    displaced.append(m_id)
        displaced.sort(key=list(self._staged).index)
        return displaced

    def _stage(self, step: Step, greige) -> None:
        """Plan `step` against the stock other stagings leave (plus the sets
        it names) and store it under its machine, keeping that machine's
        place in the staging order."""
        mchn = self._state.machines[step.machine]
        named = {s for s in step.top + step.btm if s is not None}
        assign = {bar: list(sets) for bar, sets in (('top', step.top), ('btm', step.btm)) if sets}
        lbs = step.rolls * greige.tgt_wt
        plan = mchn.plan_production(
            greige, lbs, start_at=step.at,
            inventory=self._stock_view(exclude=step.machine, free=named),
            assign=assign or None,
        )
        move = Move(machine_id=step.machine, item=greige, lbs=lbs,
                    start_at=step.at, idle_for=timedelta(0), plan=plan)
        self._staged[step.machine] = (step, move)
