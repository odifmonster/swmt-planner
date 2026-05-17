#!/usr/bin/env python

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal, TYPE_CHECKING

from swmtplanner.schedule import Activity, Job

if TYPE_CHECKING:
    from swmtplanner.products import Greige
    from swmtplanner.schedule import Machine
    from swmtplanner.demand.rlsitem import RlsItem


@dataclass
class Move:
    """A candidate placement: produce `lbs` of `item` on `machine_id`
    starting at `start_at`, with `idle_for` of leading idle time.

    `plan` is the cached output of `machine.plan_production(item, lbs,
    start_at, idle_for)`. The loop computes it once at enumeration time
    and reuses it for scoring (via `Costing.score_after_move`) and
    committing (via `State.commit_move`)."""
    machine_id: str
    item: 'Greige'
    lbs: float
    start_at: Literal['next_job_end', 'next_runout']
    idle_for: timedelta
    plan: list[Activity]


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

    def commit_move(self, move: Move) -> None:
        """Apply `move` to the appropriate machine and rls_items. All
        `Job` activities in `move.plan` are grouped by `job.item.id` and
        submitted to each `RlsItem` as a batch via `register_jobs` —
        matching the contract documented in `demand/DESIGN.md` and
        `schedule/DESIGN.md`."""
        machine = self.machines[move.machine_id]
        machine.add_activities(move.plan)

        jobs_by_item: dict[str, list[Job]] = {}
        for a in move.plan:
            if isinstance(a, Job):
                jobs_by_item.setdefault(a.item.id, []).append(a)

        for item_id, jobs in jobs_by_item.items():
            self.rls_items[item_id].register_jobs(jobs)

    def advance_window(self) -> None:
        """Extend `window_end` forward by `window_advance_amount`. Called
        by the main loop when in-window candidate count falls below the
        configured threshold (or when the pool is fully drained)."""
        self.window_end += self.window_advance_amount
