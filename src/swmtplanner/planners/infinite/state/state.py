#!/usr/bin/env python

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal, TYPE_CHECKING

from swmtplanner.schedule import Job, ProductionPlan, Inventory, ChangeoverCapacity

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
    `None` for safety-replenishment moves; carried for the reports and
    the tape-out decision log. Defaults to `None` so directly-constructed
    `Move`s in tests don't have to set it.

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
class PriorCommit:
    """One job of the prior plan and its fate in this run (see "Sticking to
    the prior plan" in DESIGN.md): the machine and the prior plan's job id,
    its item and whole rolls left, the prior plan's target order id and
    that order's due date, its aligned start; `status` is `'open'` until
    the pre-pass recommits it (`'consumed'`, with the new job's id) or
    passes it over (`'dropped'`, with the reason in `note`); a job left to
    the loop stays `'open'` with the note `not urgent` or `outside the
    frozen window`."""
    machine: str
    prior_job: str
    item: str
    rolls: int
    order: str | None
    due_date: datetime | None
    start: datetime
    status: Literal['open', 'consumed', 'dropped'] = 'open'
    job_id: str | None = None
    note: str = ''


@dataclass
class State:
    """Plant-wide planning state. A thin container that lets any function
    accept `state` as a single argument rather than threading machines,
    rls_items, and configuration through every call signature.

    Owns two mutation operations:

    - `commit_move` applies a chosen `Move` by updating the underlying
      `Machine` (via `add_activities`) and the relevant `RlsItem`(s)
      (via `register_jobs`) in lockstep, then the beam-set `inventory`
      (the plan's sets taken leave it, its sets returned re-enter it).
    - `advance_window` extends `window_end` forward by
      `window_advance_amount`, admitting additional decisions into the
      candidate pool.

    Both keep the main loop free of the mechanics of state updates."""
    machines: dict[str, 'Machine']
    rls_items: dict[str, 'RlsItem']
    start_date: datetime
    window_end: datetime
    # The plant's beam-set stock, keyed by physical description (see
    # `schedule/DESIGN.md`, "Beam-set inventory"). Candidate plans read it
    # (`Machine.plan_production(..., inventory=)`) and never mutate it; only
    # `commit_move` changes it. Empty when the run has no `beam_sets` input,
    # in which case every hang invents a set.
    inventory: Inventory = field(default_factory=dict)
    # The plant's changeover ration (see `schedule/DESIGN.md`, "Changeover
    # capacity"). Candidate plans are laid out against its committed
    # bookings (`plan_production(..., capacity=)`); only `commit_move` books.
    # Constrains nothing when the run has no `changeover_capacity` input.
    capacity: ChangeoverCapacity = field(
        default_factory=lambda: ChangeoverCapacity(None, {}))
    # Tuneable: the right value depends on plant size + planning load.
    # 24h is the default; a run sets its own in the config's `state` block.
    window_advance_amount: timedelta = field(
        default_factory=lambda: timedelta(hours=24),
    )
    # Allowance under `due_date - lead_time` for carrying-avoidance idle.
    # Production may start this much earlier than the strict no-carry
    # moment, trading a bounded amount of carrying cost for less idle.
    # Tuneable; 24h is the default; a run sets its own in the config's
    # `state` block.
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
    # --- Phase 2: reference week ---
    # The right edge of the "urgent" bucket in `coordination.eligible_orders`.
    # An item's regular order with `week_idx <= reference_week_idx` is
    # urgent and takes precedence over its safety order; one past it yields
    # to safety replenishment first. Starts at 1 — next week's demand should
    # be in production this week — and the main loop advances it forward as
    # urgent items get filled.
    reference_week_idx: int = 1
    # How many weeks `advance_reference_week()` advances per call.
    reference_advance_amount: int = 1
    # Minimum count of items with at least one unmet RegularOrder at or
    # before reference_week_idx. When this falls below the threshold, the
    # main loop calls `advance_reference_week()` until met or until the
    # reference week exceeds the latest order's week_idx.
    reference_threshold: int = 1
    # --- Economic order quantity (see "Move sizing" in DESIGN.md) ---
    # A regular move for a unique-setup item sized at or under
    # `eoq_threshold_rolls` rolls is batched up to `eoq_batch_rolls` rolls
    # of the item's later demand.
    eoq_threshold_rolls: int = 3
    eoq_batch_rolls: int = 4
    # --- Sticking to the prior plan ---
    # The prior plan's jobs, per machine in start order, each with its fate
    # (`PriorCommit`). Empty without a prior plan.
    prior: dict[str, list[PriorCommit]] = field(default_factory=dict)
    # How far into the prior plan the pre-pass recommits: only jobs starting
    # before `start_date + frozen_window`; None (the default) is unbounded.
    frozen_window: timedelta | None = None

    def commit_move(self, move: Move) -> None:
        """Apply `move` to the appropriate machine and rls_items. The
        plan's activities are appended to the machine's activity schedule
        and its `Job` records to the machine's production schedule; the
        same `Job` records are grouped by `job.item.id` and submitted to
        each `RlsItem` as a batch via `register_jobs` — matching the
        contract documented in `demand/DESIGN.md` and
        `schedule/DESIGN.md`. Finally the plan's inventory effect is
        applied: each set in `beam_sets_taken` is removed from its physical
        description's stock (matched by set id) and each in
        `beam_sets_returned` — a taped-out set with its remaining lbs and
        new `avail_date` — is added back.

        When the plan carries a `replaced_job` (the machine's last job
        recreated with this plan's tape-out appended), the machine swaps it
        in and the job's demand item unregisters the old copy and registers
        the new one, so both sides keep referring to the same `Job`."""
        machine = self.machines[move.machine_id]
        replaced = move.plan.replaced_job
        old = machine.jobs[-1] if replaced is not None else None
        machine.commit_plan(move.plan)

        if replaced is not None and replaced.item.id in self.rls_items:
            rls = self.rls_items[replaced.item.id]
            rls.unregister_jobs([old])
            rls.register_jobs([replaced])

        jobs_by_item: dict[str, list[Job]] = {}
        for job in move.plan.jobs:
            jobs_by_item.setdefault(job.item.id, []).append(job)

        for item_id, jobs in jobs_by_item.items():
            if item_id not in self.rls_items: continue
            self.rls_items[item_id].register_jobs(jobs)

        for bs in move.plan.beam_sets_taken:
            stock = self.inventory.get(bs.desc.physical, [])
            for i, held in enumerate(stock):
                if held.id == bs.id:
                    del stock[i]
                    break
        for bs in move.plan.beam_sets_returned:
            self.inventory.setdefault(bs.desc.physical, []).append(bs)
        for kind, day, units, _start in move.plan.capacity_taken:
            self.capacity.book(kind, day, units)

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
        below `reference_threshold` (see `coordination.eligible_orders`
        for how the reference week feeds into eligibility)."""
        self.reference_week_idx += self.reference_advance_amount
