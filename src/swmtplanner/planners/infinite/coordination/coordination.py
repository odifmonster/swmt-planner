#!/usr/bin/env python

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from swmtplanner.products import Greige
    from swmtplanner.planners.infinite.state import Move, State


# ----- Order identity & types ---------------------------------------------

@dataclass(frozen=True)
class OrderKey:
    """Canonical identity of an eligible order across calls. Used as the
    key into `ScoringContext.priorities` so the cost layer can look up a
    move's rank without re-running the priority sort.

    `week_idx` is the week index for regular orders, or `None` for
    safety orders. The discriminator pairs with `Move.week_idx` so the
    cost layer can form the key directly from a candidate move."""
    item_id: str
    week_idx: int | None


@dataclass(frozen=True)
class RegularOrder:
    """The earliest week of unmet demand for an item, read from the
    item's safety-aware view. `due_date` drives the carrying-avoidance
    idle calculation when this order is paired with a decision point.

    `order_id` is the id of the demand-layer `SafetyAwareOrder` this
    order corresponds to (`P{week_idx}@{item.id}`), captured directly
    from that order so it never has to be rebuilt. The enumerator threads
    it into `Machine.plan_production` as `tgt_order`."""
    item: 'Greige'
    week_idx: int
    due_date: datetime
    lbs: float
    order_id: str


@dataclass(frozen=True)
class SafetyOrder:
    """A request to top up an item's safety pool to its target. Safety
    fills don't accrue carrying cost in the demand view, so they're not
    subject to carrying-avoidance idle.

    `order_id` is the id of the safety view's `Safety` order
    (`S@{item.id}`), captured directly from it; the enumerator threads it
    into `Machine.plan_production` as `tgt_order`."""
    item: 'Greige'
    lbs: float
    order_id: str


# ----- Scoring context ----------------------------------------------------

@dataclass(frozen=True)
class ScoringContext:
    """Per-iteration bundle of cross-candidate scoring inputs the cost
    layer reads from. Built once per main-loop iteration after
    `enumerate_candidates` returns and passed to every
    `Costing.score_after_move` call.

    Fields:

    - `priorities` maps every eligible order's `OrderKey` to its rank
      (1 = highest priority). Drives the priority cost's "higher-
      priority than this move" filter.
    - `regular_orders_by_key` maps each `OrderKey` of a `RegularOrder`
      to the order itself so the priority cost can read its
      `due_date` and remaining `lbs` without re-running eligibility.
      Safety orders are absent from this dict (they don't contribute
      to the priority cost).
    - `earliest_dp_excluding` maps each `machine_id` that appears in
      the candidate pool to the earliest decision-point time across
      candidates *not* on that machine. The priority cost uses it as
      the "another machine could pick it up" arrival time for higher-
      priority orders the move is skipping. Missing keys (no other
      machine has a DP this iteration) fall back to
      `earliest_dp_time`.
    - `earliest_dp_time` is the earliest decision-point time across
      the whole candidate pool — the zero point for the level-loading
      cost and the fallback for `earliest_dp_excluding`.
    - `new_machine_avail` maps each `Greige` that appears in the
      candidate pool to `True` iff at least one of that item's
      candidates targets a `Machine.is_new` machine, used by the
      old-machine penalty."""
    priorities: dict[OrderKey, int]
    regular_orders_by_key: dict[OrderKey, 'RegularOrder']
    earliest_dp_excluding: dict[str, datetime]
    earliest_dp_time: datetime
    new_machine_avail: dict['Greige', bool]


# ----- Order eligibility --------------------------------------------------

def eligible_orders(state: 'State') -> list[RegularOrder | SafetyOrder]:
    """For each `RlsItem`, return up to two eligible orders:

    - One `RegularOrder` for the earliest week with unmet demand, read
      from the safety-aware view. At most one per item per call.
    - One `SafetyOrder` if `safety_view.safety_pool < safety_target`.
      At most one per item per call.

    Items whose demand is fully met *and* whose safety pool is at-or-
    above target contribute nothing.

    Lives in `coordination/` (rather than `loop/candidates.py`) because
    the eligible-order set is plant-wide — both candidate enumeration
    and priority assignment consume it, and `coordination/` is the
    architectural home for cross-cutting order data."""
    out: list[RegularOrder | SafetyOrder] = []
    for rls in state.rls_items.values():
        # Regular: earliest safety-aware order with unmet demand. The
        # safety_view.orders tuple is week_idx-ordered by construction.
        for order in rls.safety_view.orders:
            if order.remaining_lbs > 0:
                out.append(RegularOrder(
                    item=rls.item,
                    week_idx=order.week.week_idx,
                    due_date=order.week.due_date,
                    lbs=order.remaining_lbs,
                    order_id=order.id,
                ))
                break
        # Safety: top-up if pool is below target.
        safety_gap = (
            rls.safety_view.safety_target - rls.safety_view.safety_pool
        )
        if safety_gap > 0:
            out.append(SafetyOrder(
                item=rls.item, lbs=safety_gap,
                order_id=rls.safety_view.safety.id,
            ))
    return out


# ----- Priority assignment ------------------------------------------------

def assign_priorities(state: 'State') -> dict[OrderKey, int]:
    """Compute the priority rank of every eligible order in `state`.

    Returns a `{OrderKey: rank}` dict where rank 1 is highest priority
    (lowest cost contribution). The cost layer looks up each move's
    rank via `OrderKey(move.item.id, move.week_idx)` and adds
    `rank × w.priority` to the move's score.

    Priority order (rank 1 first):

    1. **Urgent regulars** — `RegularOrder`s with
       `week_idx <= state.reference_week_idx`. Sorted by
       `(due_date asc, safety_pool / safety_target asc)` so an item
       that's already light on safety gets pulled forward when its
       order shares a due date with a safer item's.
    2. **Safety orders** — sorted by `safety_pool / safety_target`
       ascending (largest relative depletion first; this scales fairly
       across items whose `safety_target`s differ in absolute lbs).
    3. **Future regulars** — `RegularOrder`s with
       `week_idx > state.reference_week_idx`. Same intra-bucket sort.

    Placing safety in the middle is intentional — see "Priority order"
    in DESIGN.md."""
    orders = eligible_orders(state)

    # Helper: relative safety-pool fraction per item. `safety_target ==
    # 0` is rare (items whose Greige sets safety=0) but plausible; we
    # treat it as ratio = 0 so those items don't dominate the sort.
    def _relative_safety(item_id: str) -> float:
        view = state.rls_items[item_id].safety_view
        if view.safety_target <= 0:
            return 0.0
        return view.safety_pool / view.safety_target

    regs = [o for o in orders if isinstance(o, RegularOrder)]
    safes = [o for o in orders if isinstance(o, SafetyOrder)]

    ref = state.reference_week_idx
    urgent = [r for r in regs if r.week_idx <= ref]
    future = [r for r in regs if r.week_idx > ref]

    def _reg_key(r: RegularOrder) -> tuple:
        return (r.due_date, _relative_safety(r.item.id))

    urgent.sort(key=_reg_key)
    future.sort(key=_reg_key)
    safes.sort(key=lambda s: _relative_safety(s.item.id))

    ranks: dict[OrderKey, int] = {}
    rank = 1
    for r in urgent:
        ranks[OrderKey(item_id=r.item.id, week_idx=r.week_idx)] = rank
        rank += 1
    for s in safes:
        ranks[OrderKey(item_id=s.item.id, week_idx=None)] = rank
        rank += 1
    for r in future:
        ranks[OrderKey(item_id=r.item.id, week_idx=r.week_idx)] = rank
        rank += 1

    return ranks


# ----- New-machine availability -------------------------------------------

def build_new_machine_avail(
    state: 'State',
    candidates: list['Move'],
) -> dict['Greige', bool]:
    """Map each `Greige` that appears in `candidates` to `True` iff at
    least one of that item's candidate moves targets a `Machine.is_new`
    machine. Items absent from the candidate pool are absent from the
    returned dict; the cost layer reads with `.get(item, False)` so
    missing keys default to "no new alternative" (no penalty applies)."""
    out: dict['Greige', bool] = {}
    for move in candidates:
        is_new = state.machines[move.machine_id].is_new
        out[move.item] = out.get(move.item, False) or is_new
    return out


# ----- Earliest DP excluding self -----------------------------------------

def build_earliest_dp_excluding(
    state: 'State',
    candidates: list['Move'],
) -> dict[str, datetime]:
    """Map each `machine_id` appearing in `candidates` to the earliest
    `dp_time` across candidates *not* on that machine. Used by the
    priority cost to estimate when a skipped higher-priority order
    could be picked up by some other machine if the move being scored
    commits its own machine.

    `dp_time(c)` matches `build_context`:
    `state.machines[c.machine_id].schedule_tail` for
    `start_at='schedule_tail'` and `.next_runout` otherwise.

    Machines whose only DPs are their own (i.e., no other machine has
    a candidate this iteration) are absent from the returned dict —
    callers fall back to `ctx.earliest_dp_time` in that case."""
    def _dp_time(move: 'Move') -> datetime:
        machine = state.machines[move.machine_id]
        if move.start_at == 'schedule_tail':
            return machine.schedule_tail
        return machine.next_runout

    # First pass: best (earliest) DP per machine that has any candidate.
    best_per_machine: dict[str, datetime] = {}
    for move in candidates:
        t = _dp_time(move)
        prev = best_per_machine.get(move.machine_id)
        if prev is None or t < prev:
            best_per_machine[move.machine_id] = t

    # Second pass: for each machine, the min across all OTHER machines'
    # best DP times. O(machines^2), which is fine — the plant has tens
    # of machines, not thousands.
    out: dict[str, datetime] = {}
    for excluded in best_per_machine:
        others = [
            t for mid, t in best_per_machine.items() if mid != excluded
        ]
        if others:
            out[excluded] = min(others)
    return out


# ----- ScoringContext construction ----------------------------------------

def build_context(
    state: 'State',
    candidates: list['Move'],
) -> ScoringContext:
    """Build the per-iteration `ScoringContext` from `state` and the
    enumerated candidate pool. Combines the five cross-candidate inputs:

    - `priorities` from `assign_priorities(state)`.
    - `regular_orders_by_key` derived from `eligible_orders(state)` —
      a `{OrderKey: RegularOrder}` dict that the priority cost reads
      to recover each higher-priority regular's `due_date` and `lbs`.
      Safety orders are dropped.
    - `earliest_dp_excluding` from `build_earliest_dp_excluding(state,
      candidates)`.
    - `earliest_dp_time` from `min(dp_time(c) for c in candidates)`
      where `dp_time` is the machine's `schedule_tail` or `next_runout`
      depending on the move's `start_at` — i.e., the decision point
      time *before* any carrying-avoidance idle.
    - `new_machine_avail` from `build_new_machine_avail(state,
      candidates)`.

    Requires `candidates` to be non-empty — the main loop only invokes
    scoring on a non-empty pool, so an empty list is a programmer
    error (raises `ValueError` via the `min` call)."""
    def _dp_time(move: 'Move') -> datetime:
        machine = state.machines[move.machine_id]
        if move.start_at == 'schedule_tail':
            return machine.schedule_tail
        return machine.next_runout

    regular_orders_by_key: dict[OrderKey, RegularOrder] = {}
    for order in eligible_orders(state):
        if isinstance(order, RegularOrder):
            regular_orders_by_key[OrderKey(
                item_id=order.item.id, week_idx=order.week_idx,
            )] = order

    return ScoringContext(
        priorities=assign_priorities(state),
        regular_orders_by_key=regular_orders_by_key,
        earliest_dp_excluding=build_earliest_dp_excluding(state, candidates),
        earliest_dp_time=min(_dp_time(c) for c in candidates),
        new_machine_avail=build_new_machine_avail(state, candidates),
    )
