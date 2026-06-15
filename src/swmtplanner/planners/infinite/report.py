#!/usr/bin/env python

import math
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from swmtplanner.schedule import (
    Knit, Waste, Doff, TapeOut, Hanging, Threading,
    StyleChange, RunnerChange, PatternChange, Idle,
)

if TYPE_CHECKING:
    from swmtplanner.schedule import Activity
    from .loop import PlanReport

__all__ = [
    'demand_dataframe',
    'schedule_dataframe', 'production_dataframe', 'xref_dataframe',
    'unmet_demand_dataframe',
    'late_orders_dataframe', 'write_plan_report_xlsx',
]


# ----- DataFrame builders -------------------------------------------------

def demand_dataframe(report: 'PlanReport') -> pd.DataFrame:
    """Flat table of the original input demand — one row per order across
    all `rls_items`, **regular and safety**.

    Columns:

    - `order_id` — `P{week_idx}@{item}` for a regular order, `S@{item}`
      for a safety order.
    - `item` — greige id.
    - `due_date` — the order's due date; `NaT` (renders blank) for safety
      orders, which have no due date.
    - `demand` — the original ordered quantity (a regular order's weekly
      `qty_lbs`, a safety order's `safety_target`).
    - `covered_on_hand` — lbs of the order met by the item's initial
      on-hand inventory, from `RlsItem.on_hand_coverage`.
    - `remaining` — `demand - covered_on_hand`, what production must still
      place after initial inventory.

    Rows group by item (in `rls_items` order); within an item the regular
    orders come week-ordered, then that item's safety order."""
    rows = []
    for item_id, rls in report.rls_items.items():
        coverage = rls.on_hand_coverage
        view = rls.safety_view
        for order in view.orders:
            demand = order.week.qty_lbs
            covered = coverage.get(order.id, 0.0)
            rows.append({
                'order_id': order.id,
                'item': item_id,
                'due_date': order.week.due_date,
                'demand': demand,
                'covered_on_hand': covered,
                'remaining': demand - covered,
            })
        safety_demand = view.safety_target
        safety_covered = coverage.get(view.safety.id, 0.0)
        rows.append({
            'order_id': view.safety.id,
            'item': item_id,
            'due_date': pd.NaT,                 # safety orders have no due date
            'demand': safety_demand,
            'covered_on_hand': safety_covered,
            'remaining': safety_demand - safety_covered,
        })
    df = pd.DataFrame(rows, columns=[
        'order_id', 'item', 'due_date', 'demand', 'covered_on_hand',
        'remaining',
    ])
    for col in ('demand', 'covered_on_hand', 'remaining'):
        df[col] = _round_int(df[col])
    return df


def schedule_dataframe(report: 'PlanReport') -> pd.DataFrame:
    """One row per activity across all machines, indexed by
    `(machine, activity_id)` so the rows visibly group by machine when
    written to Excel (pandas merges repeated outer-index cells with
    `merge_cells=True`, the `to_excel` default).

    Index levels:

    - `machine` — machine id.
    - `activity_id` — the activity's stable id (e.g. `KNIT00001`).

    Columns:

    - `start`, `end` — `datetime`s.
    - `lbs` — populated for `Knit` and `Waste`; `NaN` for everything else
      (including `Hanging`, whose per-bar lbs go in `desc`) so the cell
      renders blank in Excel.
    - `desc` — short human-readable description, dispatched on type:
      Knit shows the greige item id, Waste shows `'<beam> on <bar>'`,
      Hanging shows each loaded bar's `'<bar> <beam> (<lbs> lbs)'`,
      Threading shows the bar(s), TapeOut shows the bar(s), the changeover
      activities show `'from <item> to <item>'`, Doff/Idle are blank.

    Within each machine, rows are in chronological order (the order
    `Machine.add_activities` appended them)."""
    rows = []
    for machine_id, activities in report.schedules.items():
        for a in activities:
            rows.append({
                'machine': machine_id,
                'activity_id': a.id,
                'start': a.start,
                'end': a.end,
                'lbs': _activity_lbs(a),
                'desc': _activity_desc(a),
            })
    df = pd.DataFrame(
        rows,
        columns=['machine', 'activity_id', 'start', 'end', 'lbs', 'desc'],
    )
    df['lbs'] = _round_int(df['lbs'])
    return df.set_index(['machine', 'activity_id'])


def production_dataframe(report: 'PlanReport') -> pd.DataFrame:
    """One row per committed `Job` record across all rls_items, indexed
    by `(item, job_id)` so rows visibly group by item in Excel.

    Index levels:

    - `item` — greige id.
    - `job_id` — the `Job`'s stable id (e.g. `JOB00045`).

    Columns: `total_rolls`, `total_lbs`, `completion` (the job's last
    roll's `completion_time`; `NaT` for a job with no rolls), and
    `tgt_order` (the id of the order the job was raised to target,
    `Job.tgt_order`; `pd.NA`/blank when the job targeted no specific
    order, e.g. a `'next_runout'` run-up job). Rows are sorted by
    `(item, completion)` so each item's production reads as a
    chronological run."""
    rows = []
    for item_id, jobs in report.jobs_by_item.items():
        for job in jobs:
            completion = (
                job.rolls[-1].completion_time if job.rolls else pd.NaT
            )
            rows.append({
                'item': item_id,
                'job_id': job.id,
                'total_rolls': job.total_rolls,
                'total_lbs': job.total_lbs,
                'completion': completion,
                'tgt_order': (
                    job.tgt_order if job.tgt_order is not None else pd.NA
                ),
            })
    df = pd.DataFrame(
        rows,
        columns=['item', 'job_id', 'total_rolls', 'total_lbs', 'completion',
                 'tgt_order'],
    )
    if not df.empty:
        df = df.sort_values(['item', 'completion']).reset_index(drop=True)
    df['total_lbs'] = _round_int(df['total_lbs'])
    return df.set_index(['item', 'job_id'])


def xref_dataframe(report: 'PlanReport') -> pd.DataFrame:
    """Flat roll/knit/order cross-reference — one row per `Knit` activity
    across every committed job (run-up and production). Joins `Roll.knits`
    (knit → roll), `SafetyAwareView.roll_order_links` (roll → the order it
    actually fills), and `Job.rolls` (roll → job).

    Columns: `item`, `job_id`, `roll_idx` (the roll's 0-based index within
    its job — a `Roll` has no id of its own), `roll_completion`,
    `knit_id`, `knit_lbs` (a roll straddling a beam swap has two knit rows
    summing to the roll's lbs), and `order_id` — the order the roll
    actually fills, looked up by roll identity from the item's
    `roll_order_links`; `pd.NA`/blank when the roll reached no order (its
    lbs went entirely to excess). `order_id` is the *resolved* fill,
    distinct from the job's `tgt_order` on the `production` sheet (what the
    job aimed at).

    Rows are ordered by `(item, job completion, roll_idx, knit order
    within the roll)` — the natural walk order, since each item's
    `rls.jobs` is completion-sorted."""
    rows = []
    for item_id, rls in report.rls_items.items():
        link_map = {
            id(roll): order_id
            for roll, order_id in rls.safety_view.roll_order_links
        }
        for job in rls.jobs:
            for roll_idx, roll in enumerate(job.rolls):
                order_id = link_map.get(id(roll), pd.NA)
                for knit in roll.knits:
                    rows.append({
                        'item': item_id,
                        'job_id': job.id,
                        'roll_idx': roll_idx,
                        'roll_completion': roll.completion_time,
                        'knit_id': knit.id,
                        'knit_lbs': knit.lbs,
                        'order_id': order_id,
                    })
    df = pd.DataFrame(rows, columns=[
        'item', 'job_id', 'roll_idx', 'roll_completion', 'knit_id',
        'knit_lbs', 'order_id',
    ])
    df['knit_lbs'] = _round_int(df['knit_lbs'])
    return df


def late_orders_dataframe(report: 'PlanReport') -> pd.DataFrame:
    rows = [
        {
            'order_id': order.id,
            'item': order.rls_item.item.id,
            'week_idx': order.week.week_idx,
            'late_lbs': order.late_lbs,
            'fill_date': order.late_fill_date
        }
        for order in report.late_orders
    ]
    df = pd.DataFrame(rows, columns=['order_id', 'week_idx', 'late_lbs', 'fill_date'])
    df['late_lbs'] = _round_int(df['late_lbs'])
    return df.set_index('order_id')


def unmet_demand_dataframe(report: 'PlanReport') -> pd.DataFrame:
    """One row per `(item, week)` pair with positive remaining lbs in
    the post-plan safety view. Columns: `item`, `week_idx`,
    `unmet_lbs`. Rows are sorted by `(item, week_idx)`."""
    rows = [
        {'item': item_id, 'week_idx': week_idx, 'unmet_lbs': lbs}
        for (item_id, week_idx), lbs
        in report.unmet_lbs_by_item_week.items()
    ]
    df = pd.DataFrame(rows, columns=['item', 'week_idx', 'unmet_lbs'])
    if not df.empty:
        df = df.sort_values(['item', 'week_idx']).reset_index(drop=True)
    df['unmet_lbs'] = _round_int(df['unmet_lbs'])
    return df


# ----- Numeric helpers ----------------------------------------------------

def _round_int(s: pd.Series) -> pd.Series:
    """Round a numeric column to the nearest integer, preserving NaN via
    pandas' nullable `Int64` dtype. The schedule's `lbs` column has NaN
    for non-Job activities (Idle / TapeOut / changeovers); Int64
    preserves those as `pd.NA`, which `to_excel` renders as a blank
    cell. For columns without NaN this still produces clean integer
    output (no trailing `.0`)."""
    return s.round(0).astype('Int64')


# ----- Per-activity helpers -----------------------------------------------

def _activity_lbs(a: 'Activity') -> float:
    """`lbs` cell value for `a`. Only Knit/Waste have a single meaningful
    lbs quantity; everything else is NaN (renders blank in Excel).
    `Hanging`'s per-bar lbs go in its `desc` instead."""
    if isinstance(a, (Knit, Waste)):
        return a.lbs
    return math.nan


def _activity_desc(a: 'Activity') -> str:
    """Short text description for `a`'s `desc` cell."""
    if isinstance(a, Knit):
        return a.item.id
    if isinstance(a, Waste):
        return f'{a.beam.id} on {a.bar}'
    if isinstance(a, Hanging):
        parts = []
        if a.bars in ('top', 'both'):
            parts.append(f'top {a.top_beam.id} ({a.top_lbs:g} lbs)')
        if a.bars in ('btm', 'both'):
            parts.append(f'btm {a.btm_beam.id} ({a.btm_lbs:g} lbs)')
        return ', '.join(parts)
    if isinstance(a, Threading):
        return a.bars
    if isinstance(a, TapeOut):
        return a.bars
    if isinstance(a, (StyleChange, RunnerChange, PatternChange)):
        return f'from {a.from_item.id} to {a.to_item.id}'
    if isinstance(a, (Doff, Idle)):
        return ''
    return ''


# ----- Excel writer -------------------------------------------------------

def write_plan_report_xlsx(
    report: 'PlanReport', path: str | Path,
) -> None:
    """Write `report` to a single Excel workbook at `path` with six
    sheets: `demand`, `schedule`, `production`, `xref`, `unmet_demand`,
    and `late_orders`. Each corresponds to a DataFrame builder in this
    module — split out so callers who want the data as DataFrames (for
    testing or for other render targets) can use those directly.

    The `schedule` and `production` sheets keep their MultiIndex on the
    leftmost two columns so pandas merges repeated outer-index cells
    (`merge_cells=True` is the `to_excel` default), giving a visibly-
    grouped layout. `demand`, `xref`, `unmet_demand`, and `late_orders`
    are flat tables (written with `index=False`)."""
    with pd.ExcelWriter(path) as writer:
        demand_dataframe(report).to_excel(
            writer, sheet_name='demand', index=False,
        )
        schedule_dataframe(report).to_excel(
            writer, sheet_name='schedule',
        )
        production_dataframe(report).to_excel(
            writer, sheet_name='production',
        )
        xref_dataframe(report).to_excel(
            writer, sheet_name='xref', index=False,
        )
        unmet_demand_dataframe(report).to_excel(
            writer, sheet_name='unmet_demand', index=False,
        )
        late_orders_dataframe(report).to_excel(
            writer, sheet_name='late_orders'
        )
