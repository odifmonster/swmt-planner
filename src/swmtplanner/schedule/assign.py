#!/usr/bin/env python

"""Assigning real sets to a planned schedule in runout order — the second
pass over a plan made with no inventory (see "Assigning sets after
planning" in DESIGN.md)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping, TYPE_CHECKING

from swmtplanner.schedule.activity import (
    Knit, Waste, TapeOut, Hanging, BEAM_FLOOR_LBS,
)
from swmtplanner.schedule.inventory import worth_stocking
from swmtplanner.schedule.machine import choose_stock

if TYPE_CHECKING:
    from swmtplanner.products import BeamSet, BeamSetDesc
    from swmtplanner.schedule.inventory import Inventory
    from swmtplanner.schedule.machine import Machine

__all__ = ['Assigned', 'SetAssignment', 'assign_sets']

Bar = Literal['top', 'btm']


@dataclass(frozen=True)
class Assigned:
    """One placeholder hang and what the second pass gave it: the machine,
    bar and hang start; the bar's requirement; the placeholder (`NEW…`);
    the real set hung in its place (`None` when stock had nothing, the
    placeholder stays); `source` `'stock'` or `'new'`; the plan's pounds
    (the placeholder's, which timed the runouts) and the real set's; the
    pounds the plan draws from the bar before its next hang (`consumed`),
    and `short_by` — how far the real set falls short of that (0 when it
    covers the plan, or when nothing was assigned)."""
    machine: str
    bar: Bar
    at: datetime
    desc: 'BeamSetDesc'
    placeholder: 'BeamSet'
    hung: 'BeamSet | None'
    source: str
    plan_lbs: float
    set_lbs: float | None
    consumed: float
    short_by: float


@dataclass(frozen=True)
class SetAssignment:
    """The second pass's result: every placeholder hang in walk order and
    the `{placeholder id: real set}` mapping the machines were rebound
    with."""
    hangs: tuple[Assigned, ...]
    mapping: Mapping[str, 'BeamSet']

    @property
    def still_new(self) -> tuple[Assigned, ...]:
        return tuple(h for h in self.hangs if h.hung is None)


def assign_sets(machines: Mapping[str, 'Machine'], inventory: 'Inventory',
                *, now: datetime) -> SetAssignment:
    """Give every placeholder hang across `machines`, in time order (hang
    start, then machine id, then bar), the set the walk would have picked
    at that moment from `inventory` — the stock available then, plus the
    sets earlier assigned hangs tape out again — by `choose_stock` for
    continuity with the set that came off the bar; then relabel each
    machine's schedule with the assignments (`Machine.rebind_sets`).
    `inventory` is read, never mutated; `now` is only the fallback
    availability of a returned set with no tape-out end (never the case in
    a walked plan). See "Assigning sets after planning" in DESIGN.md."""
    stock: dict = {k: list(v) for k, v in inventory.items()}
    taken: set[str] = set()
    mapping: dict[str, 'BeamSet'] = {}
    # (time, order, machine, bar, kind, payload): hangs and the tape-outs
    # of placeholders, returns walked before hangs at the same moment.
    events: list[tuple] = []
    consumed: dict[str, float] = {}      # placeholder id -> lbs the plan draws
    prev_of: dict[str, 'BeamSet | None'] = {}   # placeholder id -> set it replaced
    for mid, m in machines.items():
        last: dict[str, 'BeamSet | None'] = {
            bar: m.initial_status.beam(bar) for bar in ('top', 'btm')}
        on: dict[str, 'BeamSet | None'] = dict(last)
        for a in m.activities:
            if isinstance(a, Hanging):
                for bar in ('top', 'btm'):
                    bs = getattr(a, f'{bar}_beam')
                    if bs is None:
                        continue
                    if bs.is_new:
                        events.append((a.start, 1, mid, bar, 'hang', bs))
                        consumed[bs.id] = 0.0
                        prev_of[bs.id] = last[bar]
                    on[bar] = last[bar] = bs
            elif isinstance(a, Knit):
                cfg = a.item.configuration
                for bar, pct in (('top', cfg.top_pct), ('btm', cfg.btm_pct)):
                    bs = on[bar]
                    if bs is not None and bs.id in consumed:
                        consumed[bs.id] += a.lbs * pct
            elif isinstance(a, TapeOut):
                for bar in ('top', 'btm'):
                    bs = getattr(a, f'{bar}_beam')
                    if bs is None:
                        continue
                    if bs.id in consumed:
                        events.append((a.end, 0, mid, bar, 'return', bs))
                    on[bar] = None
            elif isinstance(a, Waste):
                on[a.bar] = None
    events.sort(key=lambda e: (e[0], e[1], e[2], e[3]))

    hangs: list[Assigned] = []
    for at, _order, mid, bar, kind, bs in events:
        if kind == 'return':
            real = mapping.get(bs.id)
            if real is None:
                continue
            left = max(0.0, real.lbs - consumed[bs.id])
            back = real.returned(left, at)
            taken.discard(real.id)
            # The set as it went on leaves the pool; what comes back enters
            # it only with enough yarn to be worth hanging again.
            pool = stock.setdefault(back.desc.physical, [])
            pool[:] = [b for b in pool if b.id != back.id]
            if worth_stocking(back):
                pool.append(back)
            continue
        want = bs.desc.physical
        # Only real sets are stock: a placeholder an earlier plan taped out
        # and returned to the inventory is never handed to another hang.
        cands = [b for b in stock.get(want, ())
                 if not b.is_new and b.available_at(at) and b.id not in taken
                 and machines[mid].accepts(b)]       # a large set only on a new machine
        if cands:
            real = choose_stock(cands)
            taken.add(real.id)
            mapping[bs.id] = real
            short = max(0.0, consumed[bs.id] - (real.lbs - BEAM_FLOOR_LBS))
            hangs.append(Assigned(mid, bar, at, bs.desc, bs, real, 'stock',
                                  bs.lbs, real.lbs, consumed[bs.id], short))
        else:
            hangs.append(Assigned(mid, bar, at, bs.desc, bs, None, 'new',
                                  bs.lbs, None, consumed[bs.id], 0.0))
    for m in machines.values():
        m.rebind_sets(mapping)
    return SetAssignment(tuple(hangs), mapping)
