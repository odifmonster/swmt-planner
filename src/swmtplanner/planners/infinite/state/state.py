#!/usr/bin/env python

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal, TYPE_CHECKING

from swmtplanner.schedule import Job, ProductionPlan

if TYPE_CHECKING:
    from swmtplanner.products import Greige
    from swmtplanner.schedule import Machine
    from swmtplanner.demand.rlsitem import RlsItem


@dataclass
class Move:
    """A candidate placement: produce `lbs` of `item` on `machine_id`
    starting at `start_at`, with `idle_for` of leading idle time.

    `plan` is the cached `ProductionPlan` from
    `machine.plan_production(item, lbs, start_at, idle_for)`. The loop
    computes it once at enumeration time and reuses it for scoring (via
    `Costing.score_after_move`) and committing (via `State.commit_move`),
    reading `plan.activities` for the machine schedule and `plan.jobs`
    for the production records.

    `week_idx` is the week index of the order this move addresses, or
    `None` for safety-replenishment moves. The cost layer uses it to
    form the `OrderKey` for priority-cost lookup; defaults to `None`
    so directly-constructed `Move`s in tests don't have to set it
    when priority weights are zero.

    `order_remaining_lbs` is the unfulfilled lbs on the targeted order at
    enumeration time (the eligible `RegularOrder.lbs` / `SafetyOrder.lbs`).
    Carried for the debug log's `iteration_log`; defaults to `0.0` so
    directly-constructed `Move`s in tests don't have to set it."""
    machine_id: str
    item: 'Greige'
    lbs: float
    start_at: Literal['schedule_tail', 'next_runout']
    idle_for: timedelta
    plan: ProductionPlan
    week_idx: int | None = None
    order_remaining_lbs: float = 0.0


@dataclass
class State:
    """Plant-wide planning state. A thin container that lets any function
    accept `state` as a single argument rather than threading machines,
    rls_items, and configuration through every call signature.

    Owns two mutation operations:

    - `commit_move` applies a chosen `Move` by updating the underlying
      `Machine` (via `add_activities`) and the relevant `RlsItem`(s)
      (via `register_jobs`) in lockstep.
    - `advance_window` extends `window_end` forward by
      `window_advance_amount`, admitting additional decisions into the
      candidate pool.

    Both keep the main loop free of the mechanics of state updates."""
    machines: dict[str, 'Machine']
    rls_items: dict[str, 'RlsItem']
    start_date: datetime
    window_end: datetime
    # Tuneable: the right value depends on plant size + planning load.
    # 24h is a placeholder; refined after testing per DESIGN.md.
    window_advance_amount: timedelta = field(
        default_factory=lambda: timedelta(hours=24),
    )
    # Allowance under `due_date - lead_time` for carrying-avoidance idle.
    # Production may start this much earlier than the strict no-carry
    # moment, trading a bounded amount of carrying cost for less idle.
    # Tuneable; 24h is the initial guess.
    carrying_avoidance_margin: timedelta = field(
        default_factory=lambda: timedelta(hours=24),
    )
    # Minimum number of in-window candidates the main loop tries to keep
    # in the pool. When the pool falls below this, the loop calls
    # `advance_window()` until the threshold is met or the planning
    # horizon is reached. Tuneable; 1 is the conservative default
    # (advance only when the pool is fully drained).
    candidate_threshold: int = 1
    # Buffer added to the latest rls_item due_date to form the planning
    # horizon — the cutoff past which the loop won't advance the
    # decision window. Lets the planner schedule late production /
    # safety top-ups after the demand horizon without running away
    # indefinitely. Tuneable.
    planning_horizon_buffer: timedelta = field(
        default_factory=lambda: timedelta(weeks=4),
    )
    # --- Phase 2: priority-assignment reference week ---
    # The right edge of the "urgent" bucket in `assign_priorities`. Orders
    # with `week_idx <= reference_week_idx` are urgent regulars (rank above
    # any safety order); orders past it are future regulars (rank below
    # safety). Starts at 1 — next week's demand should be in production
    # this week — and the main loop advances it forward as urgent items
    # get filled.
    reference_week_idx: int = 1
    # How many weeks `advance_reference_week()` advances per call.
    reference_advance_amount: int = 1
    # Minimum count of items with at least one unmet RegularOrder at or
    # before reference_week_idx. When this falls below the threshold, the
    # main loop calls `advance_reference_week()` until met or until the
    # reference week exceeds the latest order's week_idx.
    reference_threshold: int = 5

    def commit_move(self, move: Move) -> None:
        """Apply `move` to the appropriate machine and rls_items. The
        plan's activities are appended to the machine's activity schedule
        and its `Job` records to the machine's production schedule; the
        same `Job` records are grouped by `job.item.id` and submitted to
        each `RlsItem` as a batch via `register_jobs` — matching the
        contract documented in `demand/DESIGN.md` and
        `schedule/DESIGN.md`."""
        machine = self.machines[move.machine_id]
        machine.add_activities(move.plan.activities)
        machine.add_jobs(move.plan.jobs)

        jobs_by_item: dict[str, list[Job]] = {}
        for job in move.plan.jobs:
            jobs_by_item.setdefault(job.item.id, []).append(job)

        for item_id, jobs in jobs_by_item.items():
            self.rls_items[item_id].register_jobs(jobs)

    def advance_window(self) -> None:
        """Extend `window_end` forward by `window_advance_amount`. Called
        by the main loop when in-window candidate count falls below the
        configured threshold (or when the pool is fully drained)."""
        self.window_end += self.window_advance_amount

    def advance_reference_week(self) -> None:
        """Extend `reference_week_idx` forward by
        `reference_advance_amount`. Called by the main loop's reference-
        week-advance step when the count of items with at least one
        unmet `RegularOrder` at or before `reference_week_idx` falls
        below `reference_threshold` (see `coordination.assign_priorities`
        for how the reference week feeds into the priority sort)."""
        self.reference_week_idx += self.reference_advance_amount
