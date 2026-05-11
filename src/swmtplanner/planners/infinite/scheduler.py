#!/usr/bin/env python

import math
from datetime import date, datetime, timedelta
from typing import Generator, TypedDict

from ...support import workcal, WorkCal
from ...demand import *
from ...schedule import *

HOLIDAYS: list[workcal.FixedDate | workcal.FlexDate] = [
    workcal.FixedDate(month=1, day=1), # new year's day
    workcal.FlexDate(month=1, weekday=0, n=3), # mlk day
    workcal.FlexDate(month=2, weekday=0, n=3), # presidents' day
    workcal.FlexDate(month=5, weekday=0, n=-1), # memorial day
    workcal.FixedDate(month=6, day=19), # juneteenth
    workcal.FixedDate(month=7, day=4), # 4th of july
    workcal.FlexDate(month=9, weekday=0, n=1), # labor day
    workcal.FlexDate(month=10, weekday=0, n=2), # columbus day
    workcal.FixedDate(month=11, day=11), # veterans' day
    workcal.FlexDate(month=11, weekday=3, n=4), # thanksgiving
    workcal.FixedDate(month=12, day=25) # christmas
]

_OrderPrty = tuple[int, Order | Safety]
_SchedPair = tuple[machine.Decision, _OrderPrty]

class _State(TypedDict):
    workcal: WorkCal
    machines: dict[str, Machine] # maps machine ids to machines
    release: dict[str, RlsItem] # maps greige item ids to release items
    rem_demand: list[_OrderPrty]
    boundary: datetime
    current_ordinal: int # the monday of the current week as an ordinal

def _week_ord(dt: datetime) -> int:
    iso = dt.isocalendar()
    return date.fromisocalendar(iso[0], iso[1], 1).toordinal()

def _next_unfulfilled_order(rls: RlsItem) -> Order | None:
    for o in rls.orders:
        if o.remaining().regular > 0:
            return o
    return None

def get_next_demand(release: list[RlsItem], cur_year: int, cur_week: int) -> list[_OrderPrty]:
    cur_wk_ord = date.fromisocalendar(cur_year, cur_week, 1).toordinal()
    boundary_ord = cur_wk_ord + 14  # start of week n + 2

    next_demands: list[Order | Safety] = []
    for rls in release:
        nxt = _next_unfulfilled_order(rls)
        if nxt is None:
            continue
        if _week_ord(nxt.due_date) < boundary_ord:
            next_demands.append(nxt)
        else:
            sfty = rls.safety
            next_demands.append(sfty if sfty.lbs > 0 else nxt)

    wk0_ord = None
    for d in next_demands:
        if isinstance(d, Order):
            wk = _week_ord(d.due_date)
            if wk < boundary_ord and (wk0_ord is None or wk < wk0_ord):
                wk0_ord = wk
    if wk0_ord is None:
        wk0_ord = cur_wk_ord

    result: list[_OrderPrty] = []
    for d in next_demands:
        if isinstance(d, Order):
            wk = _week_ord(d.due_date)
            offset = (wk - wk0_ord) // 7
            priority = offset if wk < boundary_ord else offset + 1
        else:
            priority = (boundary_ord - wk0_ord) // 7
        result.append((priority, d))

    return result

def get_next_decisions(machines: dict[str, Machine], boundary: datetime) -> list[machine.Decision]:
    ret = []
    for m in machines.values():
        for d in m.next_decisions():
            if d.dt <= boundary:
                ret.append(d)
    return ret

def get_earliest_decision(machines: dict[str, Machine]) -> machine.Decision:
    earliest = None

    for m in machines.values():
        for d in m.next_decisions():
            if earliest is None:
                earliest = d
            elif d.dt < earliest.dt:
                earliest = d
    
    if earliest is None:
        raise RuntimeError('this should not happen')
    
    return earliest

def get_all_pairs(decisions: list[machine.Decision], demand: list[_OrderPrty]) -> Generator[_SchedPair]:
    for dec in decisions:
        for prty, req in demand:
            if not req.item.can_run_on_mchn(dec.mchn_id):
                continue
            yield (dec, (prty, req))

def cost(pair: _SchedPair, state: _State):
    decision, (cur_prty, req) = pair

    total = 0.0

    if isinstance(req, Order):
        mchn = state['machines'][decision.mchn_id]
        lbs = req.remaining().regular
        end = mchn.predict_job_end(req.item, lbs)
        if end > req.due_date:
            d = math.ceil(((end - req.due_date).total_seconds() - 2 * 3600) / 86400)
            total += 500 * (2 ** d)

    for prty_other, req_other in state['rem_demand']:
        if req_other is req:
            continue
        if prty_other < cur_prty:
            total += 750 * (cur_prty - prty_other)

    return total

def schedule_next_pair(state: _State):
    decisions = get_next_decisions(state['machines'], state['boundary'])
    while len({d.mchn_id for d in decisions}) < 2:
        state['boundary'] = state['workcal'].offset_work_hours(state['boundary'], 12)
        monday = state['boundary'].date() - timedelta(days=state['boundary'].weekday())
        state['current_ordinal'] = monday.toordinal()
        decisions = get_next_decisions(state['machines'], state['boundary'])

    iso = date.fromordinal(state['current_ordinal']).isocalendar()
    state['rem_demand'] = get_next_demand(list(state['release'].values()), iso.year, iso.week)

    best_pair = None
    best_cost = None
    for pair in get_all_pairs(decisions, state['rem_demand']):
        c = cost(pair, state)
        if best_cost is None or c < best_cost:
            best_cost = c
            best_pair = pair

    if best_pair is None:
        return None

    decision, (_, req) = best_pair
    mchn = state['machines'][decision.mchn_id]
    lbs = req.remaining().regular if isinstance(req, Order) else req.lbs
    job = mchn.add_job(req.item, lbs)
    state['release'][req.item.id].assign(job)
    return best_pair

def make_schedule(release: list[RlsItem], machines: list[Machine], workcal: WorkCal) -> _State:
    state: _State = {
        'workcal': workcal,
        'machines': {m.id: m for m in machines},
        'release': {r.item.id: r for r in release},
        'rem_demand': [],
        'boundary': min(m.next_job_end for m in machines),
        'current_ordinal': 0,
    }

    while True:
        result = schedule_next_pair(state)
        if result is None:
            return state