#!/usr/bin/env python

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from swmtplanner.products import Greige
    from swmtplanner.planners.infinite.state import State


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
    idle calculation when this order is paired with a decision point."""
    item: 'Greige'
    week_idx: int
    due_date: datetime
    lbs: float


@dataclass(frozen=True)
class SafetyOrder:
    """A request to top up an item's safety pool to its target. Safety
    fills don't accrue carrying cost in the demand view, so they're not
    subject to carrying-avoidance idle."""
    item: 'Greige'
    lbs: float


# ----- Scoring context ----------------------------------------------------

@dataclass(frozen=True)
class ScoringContext:
    """Per-iteration bundle of cross-candidate scoring inputs the cost
    layer reads from. Built once per main-loop iteration after
    `enumerate_candidates` returns and passed to every
    `Costing.score_after_move` call.

    `priorities` maps every eligible order's `OrderKey` to its rank
    (1 = highest priority); `earliest_dp_time` is the earliest decision
    point time across the iteration's candidate pool, used as the zero
    point for the level-loading cost."""
    priorities: dict[OrderKey, int]
    earliest_dp_time: datetime


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
                ))
                break
        # Safety: top-up if pool is below target.
        safety_gap = (
            rls.safety_view.safety_target - rls.safety_view.safety_pool
        )
        if safety_gap > 0:
            out.append(SafetyOrder(item=rls.item, lbs=safety_gap))
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
