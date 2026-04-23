#!/usr/bin/env python

from datetime import datetime
import math

from swmtplanner.support import Queue
from swmtplanner.swmttypes.product import Greige
from swmtplanner.swmttypes.demand import Req, Order, Safety
from swmtplanner.swmttypes.schedule import Decision, Machine

MACHINES: dict[str, Machine] = {}

def get_next_reqs(queue: Queue[Req, int]) -> list[Req]:
    """
    Returns one Req per unique item, selecting the highest-priority Req
    for each. All non-selected Reqs are returned to the queue afterward.

      queue:
        A Queue of Req objects, keyed and ordered by priority.
    """
    best: dict[Greige, Req] = {}
    leftover: list[Req] = []

    while queue:
        req = queue.get()
        if req.item not in best:
            best[req.item] = req
        else:
            leftover.append(req)

    for req in leftover:
        queue.put(req)

    return list(best.values())

def get_next_decisions(
    queue: Queue[Decision, datetime],
    cutoff: datetime,
) -> list[Decision]:
    """
    Returns all decisions from the queue that occur before cutoff.

      queue:
        A Queue of Decision objects, keyed and ordered by their datetime.
      cutoff:
        Only decisions occurring before this datetime are returned.
    """
    decisions = []
    while queue and queue.peek().date < cutoff:
        decisions.append(queue.get())
    return decisions

def cost(decision: Decision, req: Order | Safety) -> float:
    """
    Returns the cost of scheduling the given requirement at the given decision
    point, based on beam changes, tape-outs, run-outs, lateness, earliness,
    and whether the requirement is a safety stock order.

      decision:
        The decision point at which to schedule the requirement.
      req:
        The Order or Safety requirement to be scheduled.
    """
    TAPE_OUT_COST    = 1000
    RUN_OUT_COST     = 200
    BEAM_CHANGE_COST = 200
    EARLY_COST       = 100
    LATE_COST        = 100
    SAFETY_COST      = 50

    machine = MACHINES[decision.mchn_id]
    total = 0.0

    # Tape-out and beam change costs
    wait_for_runout = decision.kind in ('top_ro', 'btm_ro')
    for tapeout in machine.get_tapeouts(req.item, wait_for_runout=wait_for_runout):
        kind = tapeout[0]
        if kind in ('top_to', 'btm_to'):
            total += TAPE_OUT_COST
        else:  # top_chg, btm_chg
            total += BEAM_CHANGE_COST

    # Run-out cost — one per run-out that occurs during the job
    run_outs, job_end = machine.get_runouts(decision.date, req.rolls)
    for _ in run_outs:
        total += RUN_OUT_COST

    # Safety stock flat cost
    if isinstance(req, Safety):
        total += SAFETY_COST

    # Late/early costs only apply to Orders
    if isinstance(req, Order):
        days_late = (job_end - req.date).total_seconds() / 86400

        if days_late > 0:
            total += (2 ** math.ceil(days_late)) * LATE_COST
        else:
            weeks_early = int(-days_late / 7)
            if weeks_early >= 1:
                total += weeks_early * EARLY_COST

    return total

def get_all_pairs(
    decisions: list[Decision],
    reqs: list[Req],
) -> list[tuple[Decision, Req]]:
    """
    Returns all valid (Decision, Req) pairings. Safety requirements are
    excluded from any decision that falls before their target week.

      decisions:
        The list of decision points to pair against.
      reqs:
        The list of requirements to pair against.
    """
    pairs = []
    for decision in decisions:
        iso = decision.date.isocalendar()
        for req in reqs:
            if isinstance(req, Safety):
                if (iso.year, iso.week) < (req.year, req.week):
                    continue
            pairs.append((decision, req))
    return pairs

def get_best_pair(pairs: list[tuple[Decision, Req]]) -> tuple[Decision, Req]:
    """
    Returns the (Decision, Req) pair with the lowest scheduling cost.

      pairs:
        A list of (Decision, Req) pairs as produced by get_all_pairs.
    """
    return min(pairs, key=lambda pair: cost(*pair))