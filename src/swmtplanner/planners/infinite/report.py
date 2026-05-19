#!/usr/bin/env python

import math
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from swmtplanner.schedule import (
    Job, Waste, TapeOut, BeamLoad, StyleChange, Idle,
)

if TYPE_CHECKING:
    from swmtplanner.schedule import Activity
    from .loop import PlanReport

__all__ = [
    'schedule_dataframe', 'production_dataframe', 'unmet_demand_dataframe',
    'late_orders_dataframe', 'write_plan_report_xlsx',
    'iteration_log_dataframe', 'write_iteration_log_tsv',
]


# ----- DataFrame builders -------------------------------------------------

def schedule_dataframe(report: 'PlanReport') -> pd.DataFrame:
    """One row per activity across all machines, indexed by
    `(machine, activity_id)` so the rows visibly group by machine when
    written to Excel (pandas merges repeated outer-index cells with
    `merge_cells=True`, the `to_excel` default).

    Index levels:

    - `machine` — machine id.
    - `activity_id` — the activity's stable id (e.g. `JOB00001`).

    Columns:

    - `start`, `end` — `datetime`s.
    - `lbs` — populated for `Job`, `Waste`, and `BeamLoad`; `NaN` for
      everything else so the cell renders blank in Excel.
    - `desc` — short human-readable description, dispatched on type:
      Job/Waste show the greige item id, BeamLoad shows
      `'<beam> on <bar>'`, TapeOut shows the bar(s), StyleChange shows
      `'from <item> to <item>'`, Idle is blank.

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
    """One row per committed `Job` across all schedules, indexed by
    `(item, activity_id)` so rows visibly group by item in Excel.

    Index levels:

    - `item` — greige id.
    - `activity_id` — the Job's stable id (e.g. `JOB00045`), useful for
      cross-referencing back to the `schedule` sheet.

    Columns: `machine`, `start`, `end`, `lbs`. Rows are sorted by
    `(item, start)` so each item's production reads as a chronological
    run."""
    rows = []
    for machine_id, activities in report.schedules.items():
        for a in activities:
            if isinstance(a, Job):
                rows.append({
                    'item': a.item.id,
                    'machine': machine_id,
                    'activity_id': a.id,
                    'start': a.start,
                    'end': a.end,
                    'lbs': a.lbs,
                })
    df = pd.DataFrame(
        rows,
        columns=['item', 'machine', 'activity_id', 'start', 'end', 'lbs'],
    )
    if not df.empty:
        df = df.sort_values(['item', 'start']).reset_index(drop=True)
    df['lbs'] = _round_int(df['lbs'])
    return df.set_index(['item', 'activity_id'])


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


def iteration_log_dataframe(report: 'PlanReport') -> pd.DataFrame:
    """One row per record in `report.iteration_log`, columns mirroring
    `IterationLogRecord`'s fields. The source for the verbose
    iteration-log TSV — see "Verbose iteration log" in
    `planners/infinite/DESIGN.md` for the column-by-column contract.

    Raises `ValueError` when `report.iteration_log` is `None` — i.e.,
    when the planner wasn't invoked with `verbose=True`. Callers check
    the flag before invoking this builder; gating it inside the
    builder is a safety net."""
    if report.iteration_log is None:
        raise ValueError(
            'report.iteration_log is None — was the planner run with '
            'verbose=True?'
        )
    rows = [
        {
            'iteration': r.iteration_idx,
            'role': r.role,
            'score_rank': r.score_rank,
            'item_id': r.item_id,
            'target_type': r.target_type,
            'target_week': r.target_week,
            'machine_id': r.machine_id,
            'machine_is_new': r.machine_is_new,
            'start_at': r.start_at,
            'idle_hours': r.idle_hours,
            'total_score': r.total_score,
            'lateness': r.lateness,
            'drainage': r.drainage,
            'carrying': r.carrying,
            'excess': r.excess,
            'tape_out_single': r.tape_out_single,
            'tape_out_both': r.tape_out_both,
            'family_change': r.family_change,
            'idle_time': r.idle_time,
            'priority': r.priority,
            'level_loading': r.level_loading,
            'old_machine': r.old_machine,
        }
        for r in report.iteration_log
    ]
    df = pd.DataFrame(rows, columns=[
        'iteration', 'role', 'score_rank',
        'item_id', 'target_type', 'target_week',
        'machine_id', 'machine_is_new', 'start_at', 'idle_hours',
        'total_score',
        'lateness', 'drainage', 'carrying', 'excess',
        'tape_out_single', 'tape_out_both', 'family_change', 'idle_time',
        'priority', 'level_loading', 'old_machine',
    ])
    # Mixed int/None across rows gets promoted to float by pandas; the
    # spec wants regular-row cells to read as plain integers and safety
    # rows to be blank. `Int64` (nullable) does both.
    df['target_week'] = df['target_week'].astype('Int64')
    return df


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
    for non-Job activities (Idle / TapeOut / StyleChange); Int64
    preserves those as `pd.NA`, which `to_excel` renders as a blank
    cell. For columns without NaN this still produces clean integer
    output (no trailing `.0`)."""
    return s.round(0).astype('Int64')


# ----- Per-activity helpers -----------------------------------------------

def _activity_lbs(a: 'Activity') -> float:
    """`lbs` cell value for `a`. Only Job/Waste/BeamLoad have a
    meaningful lbs quantity; everything else is NaN (renders blank in
    Excel)."""
    if isinstance(a, (Job, Waste, BeamLoad)):
        return a.lbs
    return math.nan


def _activity_desc(a: 'Activity') -> str:
    """Short text description for `a`'s `desc` cell."""
    if isinstance(a, (Job, Waste)):
        return a.item.id
    if isinstance(a, BeamLoad):
        return f'{a.beam.id} on {a.bar}'
    if isinstance(a, TapeOut):
        return a.bars
    if isinstance(a, StyleChange):
        return f'from {a.from_item.id} to {a.to_item.id}'
    if isinstance(a, Idle):
        return ''
    return ''


# ----- Excel writer -------------------------------------------------------

def write_plan_report_xlsx(
    report: 'PlanReport', path: str | Path,
) -> None:
    """Write `report` to a single Excel workbook at `path` with three
    sheets: `schedule`, `production`, and `unmet_demand`. The sheets
    correspond to the three DataFrame builders in this module — split
    out so callers who want the data as DataFrames (for testing or for
    other render targets) can use those directly.

    The `schedule` and `production` sheets keep their MultiIndex on the
    leftmost two columns so pandas merges repeated outer-index cells
    (`merge_cells=True` is the `to_excel` default), giving a visibly-
    grouped layout. `unmet_demand` is a flat table."""
    with pd.ExcelWriter(path) as writer:
        schedule_dataframe(report).to_excel(
            writer, sheet_name='schedule',
        )
        production_dataframe(report).to_excel(
            writer, sheet_name='production',
        )
        late_orders_dataframe(report).to_excel(
            writer, sheet_name='late_orders'
        )
        unmet_demand_dataframe(report).to_excel(
            writer, sheet_name='unmet_demand', index=False,
        )


def write_iteration_log_tsv(
    report: 'PlanReport', path: str | Path,
) -> None:
    """Write `report.iteration_log` to a tab-separated file at `path`
    via `iteration_log_dataframe`. `target_week` cells are blank for
    safety-order rows (`pandas` writes `NaN` as an empty cell by
    default). Raises if the report wasn't produced with
    `plan(..., verbose=True)`."""
    iteration_log_dataframe(report).to_csv(path, sep='\t', index=False)
