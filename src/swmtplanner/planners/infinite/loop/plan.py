#!/usr/bin/env python

from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from swmtplanner.demand.rlsitem import CostComponents, RlsItem
from swmtplanner.schedule import (
    TapeOut, Hanging, StyleChange, RunnerChange, PatternChange, Idle,
)

from swmtplanner.planners.infinite.coordination import (
    RegularOrder, build_context, eligible_orders,
)
from swmtplanner.planners.infinite.costing import Costing
from swmtplanner.planners.infinite.report import (
    demand_dataframe, unmet_demand_dataframe,
)
from swmtplanner.planners.infinite.state import Move, PriorCommit, State

from .candidates import enumerate_candidates, fill_for

if TYPE_CHECKING:
    from swmtplanner.demand.order import RawOrder
    from swmtplanner.schedule import Activity, Job, ChangeoverCapacity, PassedOver
    from swmtplanner.debuglog import DebugLog
    from swmtplanner.planners.infinite.state import Move
    from swmtplanner.planners.infinite.coordination import ScoringContext


@dataclass
class PlanReport:
    """Snapshot of a `plan` invocation's output. Bundles the schedules,
    registered jobs, final cost picture, unmet-demand summary,
    late-order summary, and the input demand (`rls_items`, which also
    carry each item's post-plan views and `roll_order_links`) so callers
    can persist or render the result without holding the mutable `State`
    around. The schedules themselves also still live on the `Machine`
    instances inside `state` — this is a copy.

    The verbose audit trail is no longer reconstructed onto the report:
    when a run wants it, the planner populates a `DebugLog` live as it runs
    (see `debuglog/DESIGN.md`), so `PlanReport` carries only the finished
    plan snapshot."""
    schedules: dict[str, tuple['Activity', ...]]
    jobs_by_item: dict[str, tuple['Job', ...]]
    # Each machine's production schedule (`Machine.jobs`), in commit order —
    # the jobs whose `activities` partition that machine's `schedules` entry
    # (bar the orphaned `Idle` / `Waste` / first tape-out; see the schedule
    # JSON output).
    jobs_by_machine: dict[str, tuple['Job', ...]]
    total_score: float
    cost_components_by_item: dict[str, CostComponents]
    unmet_lbs_by_item_week: dict[tuple[str, int], float]
    late_orders: tuple['RawOrder', ...]
    rls_items: dict[str, RlsItem]
    # The changeover ration with its final bookings (None for a hand-built
    # report) — the `changeovers` sheet reads the periods from it.
    capacity: 'ChangeoverCapacity | None' = None
    # Per machine, the plant-assigned sets its committed plans passed over
    # because they did not fit the bar at the hang (`Machine.queue_passed_over`;
    # see "Assigned sets and bar queues" in schedule/DESIGN.md). Machines
    # with none are left out.
    queue_passed_over: 'dict[str, tuple[PassedOver, ...]]' = field(default_factory=dict)
    # The prior plan's jobs, each with its fate in this run (see "Sticking
    # to the prior plan" in DESIGN.md); empty without a prior plan.
    prior: 'tuple[PriorCommit, ...]' = ()


def plan(
    state: State, costing: Costing, *, debuglog: 'DebugLog | None' = None,
    tape_out_report: 'Path | None' = None,
) -> PlanReport:
    """Greedy planner. Iterates enumerate → score → commit-lowest,
    advancing the decision window as needed to keep the candidate pool
    at or above `state.candidate_threshold` (up to a horizon computed
    from the rls_items' latest due_date plus
    `state.planning_horizon_buffer`).

    Terminates only when no candidates remain — even after advancing
    the window to the horizon. The greedy commits *every* move that's
    available; there is no "best must improve" check, because committing
    demand reliably is more important than minimizing the score at any
    one iteration. The score serves only as a tie-breaker among
    eligible candidates within an iteration.

    Mutates `state` in place (each chosen move is committed via
    `state.commit_move`) and returns a `PlanReport` summarizing the
    result.

    `debuglog` is an optional `DebugLog` (its tables already configured by the
    caller — see `run.py`'s `_build_debug_log`). When present, the planner takes
    a debug scoring path that populates the log as it runs: `iteration_log` and
    `cost_summary` (plus the `inv_cost_detail` / `sched_cost_detail` /
    `priority_detail` leaf tables and the per-`Knit` `production` table) are
    written live per candidate, and the post-hoc `demand` / `unmet_demand`
    copies are written once from the finished report. When absent, the hot path
    (scalar score, pick the min) runs and nothing is logged. (The old
    `verbose`-flag audit reconstruction stays divorced; the `PlanReport` detail
    tuples remain `None`.)

    `tape_out_report` is an optional text file: every time the move chosen
    carries a `TapeOut`, the iteration's whole candidate list is appended to
    it with each candidate's score, so the alternatives to that tape-out and
    what they would have cost are on record (see `_tape_out_block`)."""
    horizon = _compute_horizon(state)
    if tape_out_report is not None:
        tape_out_report.write_text(
            'Tape-out decisions: at every iteration whose chosen move tapes a set '
            'out, every candidate of that iteration and its score (lower is '
            'better; "delta" is the score above the chosen move).\n')

    if debuglog is not None:
        _emit_run_configs(debuglog, state, costing)

    # 0. Start from the prior plan: its jobs that fill urgent demand are
    #    recommitted before anything is scored.
    move_count = recommit_prior(state)

    while True:
        print(f'Total moves committed: {move_count}', end='\r')
        candidates = enumerate_candidates(state)
        unique_machines = set(m.machine_id for m in candidates)
        # Advance the window as needed: when below threshold AND the
        # window hasn't reached the horizon, ask for more decisions.
        while (
            len(unique_machines) < state.candidate_threshold
            and state.window_end < horizon
        ):
            state.advance_window()
            candidates = enumerate_candidates(state)
            unique_machines = set(m.machine_id for m in candidates)

        # Terminate when nothing more is eligible — even after the
        # window has been pushed to the horizon.
        if not candidates:
            break

        # Advance the reference week while too few items have an urgent
        # regular order, then build the per-iteration scoring context
        # (earliest DP time, new-machine availability, fill predictor)
        # once before scoring.
        while (
            len(_urgent_items(state)) < state.reference_threshold
            and state.reference_week_idx <= 8
        ):
            state.advance_reference_week()
            candidates = enumerate_candidates(state)
        ctx = build_context(state, candidates)

        if debuglog is None:
            # Hot path: scalar score only, pick the min.
            scored = [(costing.score_after_move(state, m, ctx), m) for m in candidates]
            _, best_move = min(scored, key=lambda pair: pair[0])
            if tape_out_report is not None and _has_tape_out(best_move):
                with open(tape_out_report, 'a') as fh:
                    fh.write(_tape_out_block(move_count, state, scored, best_move, costing, ctx))
        else:
            # Debug path: record this iteration's window/reference-week state
            # (parent of the iteration_log rows), then score and rank the full
            # candidate list, writing each to `iteration_log` (and, via
            # score_after_move, `cost_summary`).
            debuglog.add_row(
                'iteration_states', iteration_idx=move_count,
                window_end=state.window_end,
                reference_week=state.reference_week_idx,
            )
            best_move = _log_iteration(
                debuglog, state, costing, ctx, candidates, move_count,
            )
        state.commit_move(best_move)

        move_count += 1

    print()
    report = build_report(state, costing)
    if debuglog is not None:
        _emit_demand_tables(debuglog, report)
    return report


def recommit_prior(state: State) -> int:
    """The pre-pass (see "Sticking to the prior plan" in DESIGN.md): walk
    the prior plan's jobs in prior start order across machines and
    recommit each whose order is still urgent and open — the prior roll
    count at the machine's schedule tail, targeting the order matched by
    item and due date, with the current item's fill — stamped with the
    prior job's id. A job whose order is open but not urgent, or starting
    at or past `start_date + frozen_window` (when set), is left open for
    the loop with the reason noted; one whose order is filled or cannot be
    matched, whose item the machine cannot run (or `plan_production`
    refuses) is dropped with the reason. Returns the number of moves
    committed."""
    jobs = sorted((pc for lst in state.prior.values() for pc in lst),
                  key=lambda pc: (pc.start, pc.machine))
    cutoff = (state.start_date + state.frozen_window
              if state.frozen_window is not None else None)
    committed = 0
    for pc in jobs:
        if pc.status != 'open':
            continue
        if cutoff is not None and pc.start >= cutoff:
            pc.note = 'outside the frozen window'
            continue
        current, why = _current_order_for(state, pc)
        if current is None:
            if why == 'not urgent':
                pc.note = why                   # left open for the loop
            else:
                pc.status, pc.note = 'dropped', why
            continue
        machine = state.machines[pc.machine]
        item = current.item
        if not item.can_run_on_mchn(pc.machine):
            pc.status, pc.note = 'dropped', f'{item.id} cannot run on {pc.machine}'
            continue
        lbs = pc.rolls * item.tgt_wt
        try:
            plan = machine.plan_production(
                item, lbs, start_at='schedule_tail', tgt_order=current.order_id,
                inventory=state.inventory, capacity=state.capacity,
                prior_job=pc.prior_job, fill=fill_for(state, machine, item),
            )
        except (ValueError, KeyError) as e:
            pc.status, pc.note = 'dropped', str(e)
            continue
        move = Move(machine_id=pc.machine, item=item, lbs=lbs, start_at='schedule_tail',
                    idle_for=timedelta(0), plan=plan, week_idx=current.week_idx,
                    order_remaining_lbs=current.lbs)
        state.commit_move(move)
        new_job = next((j for j in plan.jobs if j.tgt_order is not None), None)
        pc.status, pc.job_id, pc.note = 'consumed', (new_job.id if new_job else None), ''
        committed += 1
    return committed


def _current_order_for(state: State, pc: 'PriorCommit') -> 'tuple[RegularOrder | None, str]':
    """The urgent open order of this run a prior job serves — the item's
    regular order with the job's due date, `week_idx <=
    state.reference_week_idx`, remaining lbs — or None with why not:
    `not urgent`, `order filled`, `no such order` (a safety or unmatched
    prior job, or an item the run does not have)."""
    rls = state.rls_items.get(pc.item)
    if rls is None or pc.due_date is None:
        return None, 'no such order'
    for order in rls.safety_view.orders:
        if order.week.due_date != pc.due_date:
            continue
        if order.week.week_idx > state.reference_week_idx:
            return None, 'not urgent'
        if order.remaining_lbs <= 0:
            return None, 'order filled'
        return RegularOrder(item=rls.item, week_idx=order.week.week_idx,
                            due_date=order.week.due_date, lbs=order.remaining_lbs,
                            gross_lbs=order.week.qty_lbs, order_id=order.id), ''
    return None, 'no such order'


def _urgent_items(state: State) -> set[str]:
    """The items whose eligible order is a regular order at or before the
    reference week — what the reference-week advance counts."""
    return {
        o.item.id for o in eligible_orders(state)
        if isinstance(o, RegularOrder)
        and o.week_idx <= state.reference_week_idx
    }


def _has_tape_out(move: 'Move') -> bool:
    return any(isinstance(a, TapeOut) for a in move.plan.activities)


def _move_line(move: 'Move', score: float, best: float,
               recovery: 'tuple[float, list] | None' = None) -> str:
    """One candidate: machine, item, lbs, where it starts, leading idle, the
    order week and order it serves, when its plan starts and ends, the
    changeover it needs (tape-out bars, changeover kind, sets hung), the
    changeover slots it books (`kind@day` with the wait, if any), its
    weighted recovery cost with the items it strands, and its score with
    the gap to the chosen move."""
    acts = move.plan.activities
    tos = [a.bars for a in acts if isinstance(a, TapeOut)]
    hangs = [f"{a.bars}:{'/'.join(b.set_no for b in (a.top_beam, a.btm_beam) if b)}"
             for a in acts if isinstance(a, Hanging)]
    change = next((type(a).__name__ for a in acts
                   if isinstance(a, (StyleChange, RunnerChange, PatternChange))), '-')
    idle = move.idle_for.total_seconds() / 3600
    week = '-' if move.week_idx is None else f'wk{move.week_idx}'
    order = _targeted_order_id(move) or '-'
    starts = f'{acts[0].start:%m-%d %H:%M}' if acts else '-'
    ends = f'{acts[-1].end:%m-%d %H:%M}' if acts else '-'
    waited = sum(((a.end - a.start).total_seconds() / 3600
                  for a in acts if isinstance(a, Idle) and a.reason), 0.0)
    slots = ' '.join(f"{k[:4]}x{u}@{d:%m-%d}" for k, d, u, _t in move.plan.capacity_taken)
    if slots and waited:
        slots += f' wait {waited:.0f}h'
    rec_cost, items = recovery if recovery is not None else (0.0, [])
    strands = ','.join(i for i, _c in items)
    return (f"{move.machine_id:4} {move.item.id:11} {move.lbs:8.0f} lbs  "
            f"{move.start_at:13} idle {idle:6.1f}h  {week:5} {order:22} "
            f"{starts} -> {ends}  "
            f"tape-out {','.join(tos) or '-':5} {change:13} "
            f"hang {' '.join(hangs) or '-':28} "
            f"slot {slots or '-':22} recovery {rec_cost:9.2f} strands {strands or '-':16} "
            f"score {score:14.2f}  delta {score - best:12.2f}")


def _tape_out_block(iteration: int, state: State,
                    scored: list[tuple[float, 'Move']], best: 'Move',
                    costing: 'Costing | None' = None,
                    ctx: 'ScoringContext | None' = None) -> str:
    """The report block for one iteration whose chosen move tapes out: the
    chosen move first, then every candidate by ascending score."""
    best_score = next(sc for sc, m in scored if m is best)
    def sc_of(m):
        if costing is None or ctx is None:
            return None
        q, items = costing.recovery_detail(state, m, ctx)
        return (costing.weights.recovery * q, items)
    lines = [
        '',
        f'=== iteration {iteration}  window_end {state.window_end}  '
        f'reference week {state.reference_week_idx}  '
        f'candidates {len(scored)}',
        f'CHOSEN  {_move_line(best, best_score, best_score, sc_of(best))}',
        f'  on {best.machine_id}, now running '
        f'{state.machines[best.machine_id].current_status.current_item.id}; '
        f'tail {state.machines[best.machine_id].schedule_tail}',
        'alternatives:',
    ]
    for sc, m in sorted(scored, key=lambda p: p[0]):
        mark = '*' if m is best else ' '
        lines.append(f'  {mark} {_move_line(m, sc, best_score, sc_of(m))}')
    return '\n'.join(lines) + '\n'


def _targeted_order_id(move: 'Move') -> str | None:
    """The id of the order this move targets — its new-item `Job`'s
    `tgt_order`. (A `'next_runout'` run-up `Job`, if present, carries `None`;
    the new-item `Job` carries the order id.)"""
    return next(
        (job.tgt_order for job in move.plan.jobs if job.tgt_order is not None),
        None,
    )


def _log_iteration(
    debuglog: 'DebugLog', state: State, costing: Costing,
    ctx, candidates: list['Move'], iteration_idx: int,
) -> 'Move':
    """Score and rank every candidate, writing one `iteration_log` row each,
    and return the committed move (lowest total cost). The known-at-emit fields
    are written by `add_row` (which mints `move_id`); `rank` / `role` /
    `total_cost` are patched in via `update_row` once the candidates are sorted.
    Each candidate's `iteration_log` row is minted first (via `add_row`), then
    `score_after_move` is called *with* the log so its `cost_summary` rows link
    to that row's `move_id` (read back via `get_last_pk_val`)."""
    scored: list[tuple[float, object, 'Move']] = []
    for move in candidates:
        move_id = debuglog.add_row(
            'iteration_log',
            iteration_idx=iteration_idx,
            order_id=_targeted_order_id(move),
            order_remaining_lbs=move.order_remaining_lbs,
            machine=move.machine_id,
            decision_point=move.start_at,
        )
        _emit_production(debuglog, move)
        total = costing.score_after_move(state, move, ctx, debuglog=debuglog)
        scored.append((total, move_id, move))

    # Lowest total cost first; the committed move is rank 0. A stable sort
    # keeps the first-encountered candidate ahead on ties, matching the
    # hot path's `min`.
    scored.sort(key=lambda s: s[0])
    for rank, (total, move_id, move) in enumerate(scored):
        debuglog.update_row(
            'iteration_log', move_id,
            rank=rank,
            total_cost=total,
            role='committed' if rank == 0 else 'rejected',
        )
    return scored[0][2]


# State tuning knobs recorded in `run_configs` (kind='state'): the timedelta
# ones are stored in hours, the rest as their scalar value.
_STATE_CFG_HOURS = (
    'window_advance_amount', 'carrying_avoidance_margin',
    'planning_horizon_buffer',
)
_STATE_CFG_SCALAR = (
    'candidate_threshold', 'reference_week_idx', 'reference_advance_amount',
    'reference_threshold',
)


def _emit_run_configs(
    debuglog: 'DebugLog', state: State, costing: Costing,
) -> None:
    """Write this run's configuration to `run_configs` once, before the loop:
    one `kind='cost'` row per `CostWeights` field, and one `kind='state'` row per
    tuneable `State` knob (timedelta knobs recorded in **hours**). The
    `(kind, label)` pair is the table's composite primary key."""
    weights = costing.weights
    for f in fields(weights):
        debuglog.add_row(
            'run_configs', kind='cost', label=f.name,
            value=float(getattr(weights, f.name)),
        )
    for label in _STATE_CFG_SCALAR:
        debuglog.add_row(
            'run_configs', kind='state', label=label,
            value=float(getattr(state, label)),
        )
    for label in _STATE_CFG_HOURS:
        td = getattr(state, label)
        debuglog.add_row(
            'run_configs', kind='state', label=label,
            value=td.total_seconds() / 3600.0,
        )


def _emit_production(debuglog: 'DebugLog', move: 'Move') -> None:
    """Write one `production` row per `Knit` across the move's plan jobs
    (`move.plan.jobs` → `Roll.knits`), spanning the candidate's whole plan
    whether or not it is committed. `roll_id` is synthesized as
    `f'{job_id}_{roll_index}'` (a `Roll` has no id of its own), so a roll
    straddling a beam swap has its two knits sharing one `roll_id`. The
    `knit_id` PK is the `Knit`'s own id (globally unique across plans); the
    `move_id` FK auto-links to the current `iteration_log` row. See
    debuglog/DESIGN.md."""
    for job in move.plan.jobs:
        for roll_idx, roll in enumerate(job.rolls):
            roll_id = f'{job.id}_{roll_idx}'
            for knit in roll.knits:
                debuglog.add_row(
                    'production',
                    knit_id=knit.id,
                    roll_id=roll_id,
                    job_id=job.id,
                    item=knit.item.id,
                    start=knit.start,
                    end=knit.end,
                    lbs=knit.lbs,
                )


def _emit_demand_tables(debuglog: 'DebugLog', report: PlanReport) -> None:
    """Populate the two post-hoc output tables from the finished `report` —
    faithful copies of the regular Excel output's `demand` / `unmet_demand`
    sheets, built via `report.py`'s dataframe builders so they match the
    regular output column-for-column. Unlike the loop-populated tables these
    are snapshots of the final plan, so they are written once after the loop.
    `demand`'s `order_id` is its (non-auto) primary key — unique per
    order/safety across items; `unmet_demand` is key-less. The
    `iteration_log.order_id → demand.order_id` FK resolves now that `demand`
    exists (FK existence isn't checked at insert, so building it last is fine).
    """
    for row in demand_dataframe(report).itertuples(index=False):
        debuglog.add_row(
            'demand',
            order_id=row.order_id,
            item=row.item,
            due_date=row.due_date,
            demand=row.demand,
            covered_on_hand=row.covered_on_hand,
            remaining=row.remaining,
        )
    for row in unmet_demand_dataframe(report).itertuples(index=False):
        debuglog.add_row(
            'unmet_demand',
            item=row.item,
            week_idx=row.week_idx,
            unmet_lbs=row.unmet_lbs,
        )


def _compute_horizon(state: State) -> datetime:
    """The right-edge cutoff for window advancement. Defined as the
    latest `due_date` across all rls_items plus
    `state.planning_horizon_buffer`. Falls back to
    `start_date + planning_horizon_buffer` when no rls_items are
    present (an unusual case — included for robustness)."""
    if not state.rls_items:
        return state.start_date + state.planning_horizon_buffer
    latest_due = max(
        order.week.due_date
        for rls in state.rls_items.values()
        for order in rls.safety_view.orders
    )
    return latest_due + state.planning_horizon_buffer


def build_report(state: State, costing: Costing) -> PlanReport:
    """Build a `PlanReport` from the (post-loop) state. Snapshots the
    machines' activity tuples and the rls_items' job tuples; reads the
    final score and per-item cost components from the demand views;
    summarizes whatever remaining `safety_view.orders` still have unmet
    demand."""
    return PlanReport(
        schedules={
            m_id: m.activities for m_id, m in state.machines.items()
        },
        jobs_by_item={
            item_id: r.jobs for item_id, r in state.rls_items.items()
        },
        jobs_by_machine={
            m_id: m.jobs for m_id, m in state.machines.items()
        },
        total_score=costing.score(state),
        cost_components_by_item={
            item_id: CostComponents(
                lateness=r.raw_view.lateness,
                drainage=r.safety_view.drainage,
                carrying=r.safety_view.carrying,
                excess=r.safety_view.excess,
            )
            for item_id, r in state.rls_items.items()
        },
        unmet_lbs_by_item_week={
            (item_id, order.week.week_idx): order.remaining_lbs
            for item_id, r in state.rls_items.items()
            for order in r.safety_view.orders
            if order.remaining_lbs > 0
        },
        late_orders=tuple(
            order
            for r in state.rls_items.values()
            for order in r.raw_view.orders
            if order.late_lbs > 0
        ),
        rls_items=dict(state.rls_items),
        capacity=state.capacity,
        queue_passed_over={
            m_id: m.queue_passed_over for m_id, m in state.machines.items()
            if m.queue_passed_over
        },
        prior=tuple(pc for jobs in state.prior.values() for pc in jobs),
    )