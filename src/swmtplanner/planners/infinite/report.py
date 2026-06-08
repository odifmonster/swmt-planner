#!/usr/bin/env python

import csv
import io
import json
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
    'schedule_dataframe', 'production_dataframe', 'unmet_demand_dataframe',
    'late_orders_dataframe', 'write_plan_report_xlsx',
    'iteration_log_dataframe',
    'cost_detail_dataframe',
    'lateness_detail_dataframe', 'drainage_detail_dataframe',
    'carrying_detail_dataframe', 'excess_detail_dataframe',
    'priority_detail_dataframe',
    'schedule_detail_dataframe',
    'write_verbose_log_tsvs',
    'write_dashboard_html',
]


# ----- DataFrame builders -------------------------------------------------

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
    roll's `completion_time`; `NaT` for a job with no rolls). Rows are
    sorted by `(item, completion)` so each item's production reads as a
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
            })
    df = pd.DataFrame(
        rows,
        columns=['item', 'job_id', 'total_rolls', 'total_lbs', 'completion'],
    )
    if not df.empty:
        df = df.sort_values(['item', 'completion']).reset_index(drop=True)
    df['total_lbs'] = _round_int(df['total_lbs'])
    return df.set_index(['item', 'job_id'])


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
            'item_score_rank': r.item_score_rank,
            'item_id': r.item_id,
            'target_type': r.target_type,
            'target_week': r.target_week,
            'machine_id': r.machine_id,
            'machine_is_new': r.machine_is_new,
            'start_at': r.start_at,
            'idle_hours': r.idle_hours,
            'total_score': r.total_score,
            'cost_id': r.cost_id,
            'sched_id': r.sched_id,
        }
        for r in report.iteration_log
    ]
    df = pd.DataFrame(rows, columns=[
        'iteration', 'role', 'score_rank', 'item_score_rank',
        'item_id', 'target_type', 'target_week',
        'machine_id', 'machine_is_new', 'start_at', 'idle_hours',
        'total_score', 'cost_id', 'sched_id',
    ])
    # Mixed int/None across rows gets promoted to float by pandas; the
    # spec wants regular-row cells to read as plain integers and safety
    # rows to be blank. `Int64` (nullable) does both.
    df['target_week'] = df['target_week'].astype('Int64')
    return df


def cost_detail_dataframe(report: 'PlanReport') -> pd.DataFrame:
    """One row per record in `report.cost_detail`. Columns mirror
    `CostDetailRecord` — 14 weighted scalars, `total`, and the five
    `*_detail_id` foreign keys (nullable, blank in the TSV when the
    cost has no contributing detail rows).

    Raises `ValueError` if the report was not produced with
    `plan(..., verbose=True)`."""
    if report.cost_detail is None:
        raise ValueError(
            'report.cost_detail is None — was the planner run with '
            'verbose=True?'
        )
    rows = [
        {
            'cost_id': r.cost_id,
            'lateness': r.lateness,
            'drainage': r.drainage,
            'carrying': r.carrying,
            'excess': r.excess,
            'tape_out_single': r.tape_out_single,
            'tape_out_both': r.tape_out_both,
            'style_change': r.style_change,
            'runner_change': r.runner_change,
            'pattern_change': r.pattern_change,
            'idle_time': r.idle_time,
            'waste_lbs': r.waste_lbs,
            'priority': r.priority,
            'level_loading': r.level_loading,
            'old_machine': r.old_machine,
            'total': r.total,
            'lateness_detail_id': r.lateness_detail_id,
            'drainage_detail_id': r.drainage_detail_id,
            'carrying_detail_id': r.carrying_detail_id,
            'excess_detail_id': r.excess_detail_id,
            'priority_detail_id': r.priority_detail_id,
        }
        for r in report.cost_detail
    ]
    df = pd.DataFrame(rows, columns=[
        'cost_id',
        'lateness', 'drainage', 'carrying', 'excess',
        'tape_out_single', 'tape_out_both',
        'style_change', 'runner_change', 'pattern_change', 'idle_time',
        'waste_lbs',
        'priority', 'level_loading', 'old_machine',
        'total',
        'lateness_detail_id', 'drainage_detail_id',
        'carrying_detail_id', 'excess_detail_id',
        'priority_detail_id',
    ])
    # nullable int FKs — None should render as blank, not 'nan' / '<NA>'.
    for col in [
        'lateness_detail_id', 'drainage_detail_id',
        'carrying_detail_id', 'excess_detail_id', 'priority_detail_id',
    ]:
        df[col] = df[col].astype('Int64')
    return df


def lateness_detail_dataframe(report: 'PlanReport') -> pd.DataFrame:
    """One row per record in `report.lateness_detail`. See
    DESIGN.md's "Demand-cost detail TSVs" for the column contract.
    Raises if the report was not produced with `verbose=True`."""
    if report.lateness_detail is None:
        raise ValueError(
            'report.lateness_detail is None — was the planner run '
            'with verbose=True?'
        )
    rows = [
        {
            'lateness_detail_id': r.lateness_detail_id,
            'item_id': r.item_id,
            'lateness_delta': r.lateness_delta,
        }
        for r in report.lateness_detail
    ]
    return pd.DataFrame(rows, columns=[
        'lateness_detail_id', 'item_id', 'lateness_delta',
    ])


def drainage_detail_dataframe(report: 'PlanReport') -> pd.DataFrame:
    """Same shape as `lateness_detail_dataframe`, for drainage."""
    if report.drainage_detail is None:
        raise ValueError(
            'report.drainage_detail is None — was the planner run '
            'with verbose=True?'
        )
    rows = [
        {
            'drainage_detail_id': r.drainage_detail_id,
            'item_id': r.item_id,
            'drainage_delta': r.drainage_delta,
        }
        for r in report.drainage_detail
    ]
    return pd.DataFrame(rows, columns=[
        'drainage_detail_id', 'item_id', 'drainage_delta',
    ])


def carrying_detail_dataframe(report: 'PlanReport') -> pd.DataFrame:
    """Same shape as `lateness_detail_dataframe`, for carrying."""
    if report.carrying_detail is None:
        raise ValueError(
            'report.carrying_detail is None — was the planner run '
            'with verbose=True?'
        )
    rows = [
        {
            'carrying_detail_id': r.carrying_detail_id,
            'item_id': r.item_id,
            'carrying_delta': r.carrying_delta,
        }
        for r in report.carrying_detail
    ]
    return pd.DataFrame(rows, columns=[
        'carrying_detail_id', 'item_id', 'carrying_delta',
    ])


def excess_detail_dataframe(report: 'PlanReport') -> pd.DataFrame:
    """Same shape as `lateness_detail_dataframe`, for excess."""
    if report.excess_detail is None:
        raise ValueError(
            'report.excess_detail is None — was the planner run '
            'with verbose=True?'
        )
    rows = [
        {
            'excess_detail_id': r.excess_detail_id,
            'item_id': r.item_id,
            'excess_delta': r.excess_delta,
        }
        for r in report.excess_detail
    ]
    return pd.DataFrame(rows, columns=[
        'excess_detail_id', 'item_id', 'excess_delta',
    ])


def priority_detail_dataframe(report: 'PlanReport') -> pd.DataFrame:
    """One row per record in `report.priority_detail`. Columns:
    `priority_detail_id`, `item_id`, `week_idx`, `remaining_lbs`,
    `priority` (absolute weighted contribution — not a delta; see
    DESIGN.md). Raises if the report was not produced with
    `verbose=True`."""
    if report.priority_detail is None:
        raise ValueError(
            'report.priority_detail is None — was the planner run '
            'with verbose=True?'
        )
    rows = [
        {
            'priority_detail_id': r.priority_detail_id,
            'item_id': r.item_id,
            'week_idx': r.week_idx,
            'remaining_lbs': r.remaining_lbs,
            'priority': r.priority,
        }
        for r in report.priority_detail
    ]
    return pd.DataFrame(rows, columns=[
        'priority_detail_id', 'item_id', 'week_idx',
        'remaining_lbs', 'priority',
    ])


def schedule_detail_dataframe(report: 'PlanReport') -> pd.DataFrame:
    """One row per record in `report.schedule_detail`. Columns:
    `sched_id`, `activity_id`, `machine_id`, `start`, `end`,
    `description`. Raises if the report was not produced with
    `verbose=True`."""
    if report.schedule_detail is None:
        raise ValueError(
            'report.schedule_detail is None — was the planner run '
            'with verbose=True?'
        )
    rows = [
        {
            'sched_id': r.sched_id,
            'activity_id': r.activity_id,
            'machine_id': r.machine_id,
            'start': r.start,
            'end': r.end,
            'description': r.description,
        }
        for r in report.schedule_detail
    ]
    return pd.DataFrame(rows, columns=[
        'sched_id', 'activity_id', 'machine_id',
        'start', 'end', 'description',
    ])


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


def write_verbose_log_tsvs(
    report: 'PlanReport', dir_path: str | Path,
) -> None:
    """Write all eight verbose-log tables as TSV files inside
    `dir_path`. Creates the directory (and parents) if it doesn't
    already exist; existing files inside are overwritten.

    The TSV layout is documented in DESIGN.md's "Verbose iteration
    log" section. Files emitted:

    - `iteration_log.tsv` — one row per logged candidate
    - `cost_detail.tsv` — one row per logged candidate, with FKs
    - `lateness_detail.tsv`, `drainage_detail.tsv`,
      `carrying_detail.tsv`, `excess_detail.tsv` — per-item deltas
    - `priority_detail.tsv` — per-item absolute priority attribution
    - `schedule_detail.tsv` — per-Activity rows for each candidate's
      `move.plan`

    Cross-file joins are by integer id (`cost_id`, `sched_id`,
    `activity_id`, and the five `*_detail_id`s on
    `cost_detail.tsv`).

    Raises `ValueError` if `report` was not produced with
    `plan(..., verbose=True)` (the eight verbose tuples on `report`
    are all `None` in that case)."""
    if report.iteration_log is None:
        raise ValueError(
            'report.iteration_log is None — was the planner run with '
            'verbose=True?'
        )
    dir_path = Path(dir_path)
    dir_path.mkdir(parents=True, exist_ok=True)
    files = [
        ('iteration_log.tsv', iteration_log_dataframe(report)),
        ('cost_detail.tsv', cost_detail_dataframe(report)),
        ('lateness_detail.tsv', lateness_detail_dataframe(report)),
        ('drainage_detail.tsv', drainage_detail_dataframe(report)),
        ('carrying_detail.tsv', carrying_detail_dataframe(report)),
        ('excess_detail.tsv', excess_detail_dataframe(report)),
        ('priority_detail.tsv', priority_detail_dataframe(report)),
        ('schedule_detail.tsv', schedule_detail_dataframe(report)),
    ]
    for filename, df in files:
        df.to_csv(dir_path / filename, sep='\t', index=False)


# ----- Dashboard writer ---------------------------------------------------

def write_dashboard_html(
    report: 'PlanReport', path: str | Path,
) -> None:
    """Write a single self-contained HTML dashboard at `path`. The
    dashboard embeds the same eight tables that `write_verbose_log_tsvs`
    emits as TSVs, plus a foreign-key schema that lets the operator
    drill across tables (iteration_log → cost_detail / schedule_detail,
    cost_detail → the five per-cost detail tables). No external assets
    — all CSS and JavaScript are inlined.

    Each table's rows are serialized via `<dataframe>.to_csv(sep='\\t')`
    and parsed back, so the string representations exactly match the
    corresponding `*.tsv` files emitted by `write_verbose_log_tsvs`.

    Raises `ValueError` if `report` was not produced with
    `plan(..., verbose=True)`."""
    if report.iteration_log is None:
        raise ValueError(
            'report.iteration_log is None — was the planner run with '
            'verbose=True?'
        )
    table_builders = [
        ('iteration_log', iteration_log_dataframe),
        ('cost_detail', cost_detail_dataframe),
        ('schedule_detail', schedule_detail_dataframe),
        ('lateness_detail', lateness_detail_dataframe),
        ('drainage_detail', drainage_detail_dataframe),
        ('carrying_detail', carrying_detail_dataframe),
        ('excess_detail', excess_detail_dataframe),
        ('priority_detail', priority_detail_dataframe),
    ]
    tables: dict[str, dict] = {}
    for name, build in table_builders:
        tables[name] = _table_payload(build(report))
    payload = {'schema': _DASHBOARD_SCHEMA, 'tables': tables}
    # separators=(',',':') matches the original script's compact JSON.
    data_json = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
    html = _DASHBOARD_TEMPLATE.replace('__DATA_JSON__', data_json)
    Path(path).write_text(html, encoding='utf-8')


def _table_payload(df: pd.DataFrame) -> dict:
    """Serialize `df` as TSV (in-memory) and parse it back as
    string-only rows, so the dashboard sees the exact same cell
    contents as the on-disk TSVs. Returns the shape the embedded
    JavaScript expects: `{'columns': [...], 'rows': [[...], ...],
    'rowCount': int}`."""
    buf = io.StringIO()
    df.to_csv(buf, sep='\t', index=False)
    buf.seek(0)
    reader = csv.reader(buf, delimiter='\t')
    all_rows = list(reader)
    if not all_rows:
        return {'columns': [], 'rows': [], 'rowCount': 0}
    return {
        'columns': all_rows[0],
        'rows': all_rows[1:],
        'rowCount': len(all_rows) - 1,
    }


_DASHBOARD_SCHEMA = {
    'iteration_log': {
        'title': 'Iteration Log',
        'pk': None,
        'fks': [
            {'col': 'cost_id', 'table': 'cost_detail', 'pk': 'cost_id'},
            {'col': 'sched_id', 'table': 'schedule_detail', 'pk': 'sched_id'},
        ],
    },
    'cost_detail': {
        'title': 'Cost Detail',
        'pk': 'cost_id',
        'fks': [
            {'col': 'lateness_detail_id', 'table': 'lateness_detail', 'pk': 'lateness_detail_id'},
            {'col': 'drainage_detail_id', 'table': 'drainage_detail', 'pk': 'drainage_detail_id'},
            {'col': 'carrying_detail_id', 'table': 'carrying_detail', 'pk': 'carrying_detail_id'},
            {'col': 'excess_detail_id', 'table': 'excess_detail', 'pk': 'excess_detail_id'},
            {'col': 'priority_detail_id', 'table': 'priority_detail', 'pk': 'priority_detail_id'},
        ],
    },
    'schedule_detail': {'title': 'Schedule Detail', 'pk': 'sched_id', 'fks': []},
    'lateness_detail': {'title': 'Lateness Detail', 'pk': 'lateness_detail_id', 'fks': []},
    'drainage_detail': {'title': 'Drainage Detail', 'pk': 'drainage_detail_id', 'fks': []},
    'carrying_detail': {'title': 'Carrying Detail', 'pk': 'carrying_detail_id', 'fks': []},
    'excess_detail': {'title': 'Excess Detail', 'pk': 'excess_detail_id', 'fks': []},
    'priority_detail': {'title': 'Priority Detail', 'pk': 'priority_detail_id', 'fks': []},
}


_DASHBOARD_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Scheduling iteration dashboard</title>
<style>
  :root {
    --bg: #fafafa;
    --panel: #fff;
    --border: #e3e3e3;
    --text: #222;
    --muted: #777;
    --link: #1a66c2;
    --link-hover: #0c4ea3;
    --accent: #f6f8fb;
    --row-hover: #eef4fb;
    --pk: #b35900;
    --fk-bg: #eaf3fc;
    --warn: #b22;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; height: 100%; background: var(--bg); color: var(--text); font: 13px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  body { display: grid; grid-template-columns: 220px 1fr; grid-template-rows: auto 1fr; grid-template-areas: "head head" "side main"; min-height: 100vh; }
  header { grid-area: head; padding: 10px 16px; background: #2b3a4d; color: #fff; display: flex; align-items: center; gap: 16px; }
  header h1 { font-size: 15px; margin: 0; font-weight: 600; }
  header .crumbs { color: #cfd9e6; font-size: 12px; }
  header .crumbs a { color: #fff; text-decoration: none; border-bottom: 1px dotted #88a; }
  header .crumbs a:hover { border-bottom-color: #fff; }
  header .crumbs .sep { margin: 0 6px; color: #7f93ad; }
  nav { grid-area: side; background: var(--panel); border-right: 1px solid var(--border); padding: 12px 0; overflow-y: auto; }
  nav h2 { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin: 12px 16px 6px; }
  nav a { display: block; padding: 6px 16px; color: var(--text); text-decoration: none; font-size: 13px; border-left: 3px solid transparent; }
  nav a:hover { background: var(--accent); }
  nav a.active { background: var(--accent); border-left-color: var(--link); font-weight: 600; }
  nav a .count { float: right; color: var(--muted); font-size: 11px; }
  main { grid-area: main; padding: 16px 20px 40px; overflow: auto; }
  .view-header { display: flex; align-items: baseline; gap: 12px; margin-bottom: 10px; flex-wrap: wrap; }
  .view-header h2 { margin: 0; font-size: 17px; }
  .view-header .meta { color: var(--muted); font-size: 12px; }
  .filter-bar { margin-bottom: 10px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .filter-bar input[type=text] { padding: 5px 8px; border: 1px solid var(--border); border-radius: 4px; font-size: 13px; min-width: 220px; }
  .filter-bar .pager { margin-left: auto; display: flex; gap: 6px; align-items: center; color: var(--muted); }
  .filter-bar button { padding: 4px 10px; border: 1px solid var(--border); background: #fff; border-radius: 4px; cursor: pointer; font-size: 12px; }
  .filter-bar button:disabled { opacity: 0.4; cursor: default; }
  .table-wrap { background: var(--panel); border: 1px solid var(--border); border-radius: 6px; overflow: auto; max-height: calc(100vh - 200px); }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  thead th { position: sticky; top: 0; background: #f1f4f8; border-bottom: 1px solid var(--border); padding: 6px 8px; text-align: left; font-weight: 600; white-space: nowrap; z-index: 1; }
  thead th.pk { color: var(--pk); }
  thead th.fk { color: var(--link); }
  tbody td { padding: 5px 8px; border-bottom: 1px solid #f0f0f0; vertical-align: top; white-space: nowrap; max-width: 360px; overflow: hidden; text-overflow: ellipsis; }
  tbody tr:hover { background: var(--row-hover); }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  td a.fk-link { display: inline-block; padding: 1px 6px; background: var(--fk-bg); border-radius: 3px; color: var(--link); text-decoration: none; font-weight: 600; }
  td a.fk-link:hover { background: #d8e9fb; color: var(--link-hover); }
  td a.pk-link { color: var(--pk); font-weight: 600; text-decoration: none; }
  td a.pk-link:hover { text-decoration: underline; }
  .empty { padding: 20px; color: var(--muted); font-style: italic; text-align: center; }
  th.cb, td.cb { width: 28px; padding: 4px 6px 4px 10px; text-align: center; }
  td.cb input, th.cb input { cursor: pointer; }
  tr.selected { background: #fff6e0 !important; }
  .select-bar { position: fixed; bottom: 0; left: 220px; right: 0; background: #2b3a4d; color: #fff; padding: 8px 16px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; box-shadow: 0 -2px 8px rgba(0,0,0,0.15); z-index: 5; }
  .select-bar .label { font-weight: 600; margin-right: 4px; }
  .select-bar button { padding: 5px 10px; border: 1px solid #6c80a0; background: #3d5273; color: #fff; border-radius: 4px; cursor: pointer; font-size: 12px; }
  .select-bar button:hover { background: #4d6790; }
  .select-bar button.clear { background: transparent; border-color: #88a; }
  .select-bar button:disabled { opacity: 0.4; cursor: default; }
  main.has-selection { padding-bottom: 70px; }
  .schema-card { background: var(--panel); border: 1px solid var(--border); border-radius: 6px; padding: 14px 16px; margin-bottom: 16px; }
  .schema-card h3 { margin: 0 0 6px; font-size: 14px; }
  .schema-card ul { margin: 4px 0 0 0; padding-left: 18px; color: var(--muted); }
  .schema-card code { background: #f3f3f3; padding: 1px 4px; border-radius: 3px; }
  .empty-fk { color: #aaa; font-style: italic; }
</style>
</head>
<body>
<header>
  <h1>Scheduling iteration dashboard</h1>
  <div class="crumbs" id="crumbs"></div>
</header>
<nav id="nav"></nav>
<main id="main"></main>

<script id="payload" type="application/json">__DATA_JSON__</script>
<script>
(function () {
  const PAYLOAD = JSON.parse(document.getElementById("payload").textContent);
  const SCHEMA = PAYLOAD.schema;
  const TABLES = PAYLOAD.tables;
  const PAGE_SIZE = 100;

  // Pre-index: for each table, build {columnName: index}, plus a lookup index for any column referenced as an FK target.
  const COLINDEX = {};
  const PK_INDEX = {};   // table -> col -> Map(value -> [rowIdx, ...])
  for (const t of Object.keys(TABLES)) {
    COLINDEX[t] = {};
    TABLES[t].columns.forEach((c, i) => { COLINDEX[t][c] = i; });
  }
  // For every table, every column used as an FK pk should have a lookup.
  const targets = new Set();
  for (const t of Object.keys(SCHEMA)) {
    for (const fk of SCHEMA[t].fks) {
      targets.add(fk.table + "::" + fk.pk);
    }
  }
  for (const key of targets) {
    const [t, col] = key.split("::");
    const idx = COLINDEX[t][col];
    if (idx === undefined) continue;
    const map = new Map();
    TABLES[t].rows.forEach((row, ri) => {
      const v = row[idx];
      if (v === "" || v == null) return;
      if (!map.has(v)) map.set(v, []);
      map.get(v).push(ri);
    });
    PK_INDEX[t] = PK_INDEX[t] || {};
    PK_INDEX[t][col] = map;
  }

  // ---------- Routing ----------
  // #/home
  // #/table/<name>
  // #/lookup/<table>/<col>/<value1,value2,...>   (values URL-encoded individually, joined with literal ",")
  function parseHash() {
    const h = (location.hash || "#/home").slice(1);
    const parts = h.split("/").filter(Boolean);
    if (parts.length === 0 || parts[0] === "home") return { kind: "home" };
    if (parts[0] === "table" && parts[1]) return { kind: "table", table: decodeURIComponent(parts[1]) };
    if (parts[0] === "lookup" && parts[1] && parts[2] && parts.length >= 4) {
      const rawValues = parts.slice(3).join("/");
      const values = rawValues.split(",").map(decodeURIComponent);
      return {
        kind: "lookup",
        table: decodeURIComponent(parts[1]),
        col: decodeURIComponent(parts[2]),
        values: values
      };
    }
    return { kind: "home" };
  }
  function hashFor(route) {
    if (route.kind === "home") return "#/home";
    if (route.kind === "table") return "#/table/" + encodeURIComponent(route.table);
    if (route.kind === "lookup") {
      const vs = (route.values || [route.value]).map(encodeURIComponent).join(",");
      return "#/lookup/" + encodeURIComponent(route.table) + "/" + encodeURIComponent(route.col) + "/" + vs;
    }
    return "#/home";
  }

  // ---------- Selection state ----------
  // selection[tableName] = Set of row indices into TABLES[tableName].rows
  const selection = {};
  let selectionTable = null; // the table the current selection applies to
  function ensureSelection(tableName) {
    if (selectionTable !== tableName) {
      // moving to a different table — clear selection
      for (const k of Object.keys(selection)) delete selection[k];
      selectionTable = tableName;
    }
    if (!selection[tableName]) selection[tableName] = new Set();
    return selection[tableName];
  }
  function selectedRows(tableName) {
    const set = selection[tableName];
    if (!set || set.size === 0) return [];
    return Array.from(set).sort((a, b) => a - b).map(i => TABLES[tableName].rows[i]);
  }

  // ---------- Sidebar ----------
  const navEl = document.getElementById("nav");
  function renderNav(active) {
    const order = ["iteration_log", "cost_detail", "schedule_detail", "lateness_detail", "drainage_detail", "carrying_detail", "excess_detail", "priority_detail"];
    const parts = ['<h2>Tables</h2>'];
    parts.push('<a href="#/home" class="' + (active && active.kind === "home" ? "active" : "") + '">Overview</a>');
    for (const t of order) {
      const isActive = active && active.table === t;
      parts.push('<a href="' + hashFor({kind: "table", table: t}) + '" class="' + (isActive ? "active" : "") + '">' +
        SCHEMA[t].title + '<span class="count">' + TABLES[t].rowCount.toLocaleString() + '</span></a>');
    }
    navEl.innerHTML = parts.join("");
  }

  // ---------- Cell rendering ----------
  const NUM_RE = /^-?\d+(\.\d+)?(e-?\d+)?$/i;
  function fmtNumber(v) {
    if (v === "" || v == null) return "";
    const n = Number(v);
    if (!isFinite(n)) return v;
    if (Number.isInteger(n) && Math.abs(n) < 1e9) return n.toLocaleString();
    if (Math.abs(n) >= 1e6 || (Math.abs(n) > 0 && Math.abs(n) < 0.001)) return n.toExponential(4);
    return n.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  }

  function cellHtml(table, colName, value, isPk, fkInfo) {
    if (value === "" || value == null) {
      if (fkInfo) return '<span class="empty-fk">—</span>';
      return "";
    }
    if (fkInfo) {
      // Foreign key: link to lookup view in target table.
      const targetMap = PK_INDEX[fkInfo.table] && PK_INDEX[fkInfo.table][fkInfo.pk];
      const matches = targetMap ? (targetMap.get(value) || []).length : 0;
      const href = hashFor({ kind: "lookup", table: fkInfo.table, col: fkInfo.pk, values: [value] });
      const label = escapeHtml(value) + (matches > 1 ? ' <span style="color:#888;font-weight:normal">(' + matches + ')</span>' : "");
      return '<a class="fk-link" href="' + href + '" title="Open ' + matches + ' row(s) in ' + escapeHtml(SCHEMA[fkInfo.table].title) + '">' + label + '</a>';
    }
    if (isPk) {
      const href = hashFor({ kind: "lookup", table: table, col: colName, values: [value] });
      return '<a class="pk-link" href="' + href + '" title="Show only this record">' + escapeHtml(value) + '</a>';
    }
    if (NUM_RE.test(value)) {
      return '<span class="num-val">' + escapeHtml(fmtNumber(value)) + '</span>';
    }
    return escapeHtml(value);
  }

  // ---------- Table view ----------
  function renderTable(tableName, filterIndices, route) {
    const cols = TABLES[tableName].columns;
    const allRows = TABLES[tableName].rows;
    // Work in terms of original row indices so selections survive paging/filtering.
    const baseIndices = filterIndices || allRows.map((_, i) => i);
    const fkByCol = {};
    for (const fk of SCHEMA[tableName].fks) fkByCol[fk.col] = fk;
    const pk = SCHEMA[tableName].pk;
    const selSet = ensureSelection(tableName);

    const state = { page: 0, query: "" };
    const main = document.getElementById("main");

    function renderBody() {
      const q = state.query.trim().toLowerCase();
      let visible = baseIndices;
      if (q) {
        visible = baseIndices.filter(i => allRows[i].some(cell => cell != null && String(cell).toLowerCase().includes(q)));
      }
      const totalPages = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
      if (state.page >= totalPages) state.page = totalPages - 1;
      if (state.page < 0) state.page = 0;
      const start = state.page * PAGE_SIZE;
      const sliceIdx = visible.slice(start, start + PAGE_SIZE);

      const allOnPageSelected = sliceIdx.length > 0 && sliceIdx.every(i => selSet.has(i));
      const someOnPageSelected = sliceIdx.some(i => selSet.has(i));

      const head = '<thead><tr>' +
        '<th class="cb"><input type="checkbox" id="hcb"' + (allOnPageSelected ? ' checked' : '') + (someOnPageSelected && !allOnPageSelected ? ' data-indeterminate="1"' : '') + ' title="Select all on this page"></th>' +
        cols.map(c => {
          let cls = "";
          if (c === pk) cls = "pk";
          else if (fkByCol[c]) cls = "fk";
          return '<th class="' + cls + '">' + escapeHtml(c) + "</th>";
        }).join("") + "</tr></thead>";

      let body = "";
      if (sliceIdx.length === 0) {
        body = '<tbody><tr><td colspan="' + (cols.length + 1) + '"><div class="empty">No rows.</div></td></tr></tbody>';
      } else {
        const trs = sliceIdx.map(rowIdx => {
          const r = allRows[rowIdx];
          const isSel = selSet.has(rowIdx);
          const tds = '<td class="cb"><input type="checkbox" class="rcb" data-ri="' + rowIdx + '"' + (isSel ? ' checked' : '') + '></td>' +
            r.map((v, i) => {
              const c = cols[i];
              const isPkCol = c === pk;
              const fk = fkByCol[c];
              const cls = (NUM_RE.test(v || "") && !isPkCol && !fk) ? "num" : "";
              return '<td' + (cls ? ' class="' + cls + '"' : "") + ' title="' + escapeHtml(v == null ? "" : v) + '">' + cellHtml(tableName, c, v, isPkCol, fk) + "</td>";
            }).join("");
          return '<tr class="' + (isSel ? 'selected' : '') + '">' + tds + "</tr>";
        }).join("");
        body = "<tbody>" + trs + "</tbody>";
      }

      const tableHtml = '<div class="table-wrap"><table>' + head + body + "</table></div>";
      const pagerInfo = visible.length === 0
        ? '0 rows'
        : (start + 1) + '–' + Math.min(start + PAGE_SIZE, visible.length) + ' of ' + visible.length.toLocaleString() + (q ? ' (filtered from ' + baseIndices.length.toLocaleString() + ')' : '');

      let filterNote = '';
      if (filterIndices) {
        const vs = (route.values || []);
        const vsDisplay = vs.length <= 6
          ? vs.map(escapeHtml).join(', ')
          : vs.slice(0, 5).map(escapeHtml).join(', ') + ' …(+' + (vs.length - 5) + ' more)';
        const op = vs.length === 1 ? '=' : '∈';
        const display = vs.length === 1 ? vsDisplay : '{' + vsDisplay + '}';
        filterNote = ' · filtered by <code>' + escapeHtml(route.col) + ' ' + op + ' ' + display + '</code> ' +
          '<a href="' + hashFor({kind: "table", table: tableName}) + '">[show all]</a>';
      }

      const headerHtml =
        '<div class="view-header">' +
          '<h2>' + escapeHtml(SCHEMA[tableName].title) + '</h2>' +
          '<div class="meta">' + baseIndices.length.toLocaleString() + ' row' + (baseIndices.length === 1 ? '' : 's') +
          filterNote +
          '</div>' +
        '</div>' +
        '<div class="filter-bar">' +
          '<input type="text" id="q" placeholder="Filter rows… (any column)" value="' + escapeHtml(state.query) + '">' +
          '<button id="selvis" title="Add all currently-visible (filtered) rows to selection">+ Select all matching filter (' + visible.length + ')</button>' +
          '<div class="pager">' +
            '<button id="prev" ' + (state.page === 0 ? 'disabled' : '') + '>◀ Prev</button>' +
            '<span>' + pagerInfo + '</span>' +
            '<button id="next" ' + (state.page >= totalPages - 1 ? 'disabled' : '') + '>Next ▶</button>' +
          '</div>' +
        '</div>';

      main.innerHTML = headerHtml + tableHtml;
      renderSelectionBar(tableName);

      // Handlers
      const qEl = document.getElementById("q");
      qEl.addEventListener("input", () => { state.query = qEl.value; state.page = 0; renderBody(); const cur = document.getElementById("q"); cur.focus(); cur.setSelectionRange(qEl.value.length, qEl.value.length); });
      document.getElementById("prev").addEventListener("click", () => { state.page--; renderBody(); });
      document.getElementById("next").addEventListener("click", () => { state.page++; renderBody(); });
      document.getElementById("selvis").addEventListener("click", () => { for (const i of visible) selSet.add(i); renderBody(); });

      const hcb = document.getElementById("hcb");
      if (hcb.dataset.indeterminate) hcb.indeterminate = true;
      hcb.addEventListener("change", () => {
        if (hcb.checked) { for (const i of sliceIdx) selSet.add(i); }
        else { for (const i of sliceIdx) selSet.delete(i); }
        renderBody();
      });
      for (const cb of main.querySelectorAll("input.rcb")) {
        cb.addEventListener("change", () => {
          const ri = parseInt(cb.dataset.ri, 10);
          if (cb.checked) selSet.add(ri); else selSet.delete(ri);
          renderBody();
        });
      }
    }
    renderBody();
  }

  // ---------- Selection bar ----------
  function renderSelectionBar(tableName) {
    const existing = document.getElementById("selbar");
    if (existing) existing.remove();
    const set = selection[tableName];
    const main = document.getElementById("main");
    if (!set || set.size === 0) { main.classList.remove("has-selection"); return; }
    main.classList.add("has-selection");

    const rows = selectedRows(tableName);
    const cols = TABLES[tableName].columns;
    const colIdx = {}; cols.forEach((c, i) => { colIdx[c] = i; });

    function distinctNonEmpty(col) {
      const ix = colIdx[col];
      const out = new Set();
      for (const r of rows) {
        const v = r[ix];
        if (v != null && v !== "") out.add(v);
      }
      return Array.from(out);
    }

    const actions = [];
    // FKs declared in this table
    for (const fk of SCHEMA[tableName].fks) {
      const vals = distinctNonEmpty(fk.col);
      const label = 'View ' + vals.length + ' ' + escapeHtml(fk.col) + ' in ' + escapeHtml(SCHEMA[fk.table].title);
      const dis = vals.length === 0;
      const href = vals.length ? hashFor({kind:"lookup", table: fk.table, col: fk.pk, values: vals}) : "#";
      actions.push('<button data-href="' + escapeHtml(href) + '"' + (dis ? ' disabled' : '') + '>' + label + '</button>');
    }
    // PK self-lookup (filter this same table to selected rows by pk)
    if (SCHEMA[tableName].pk) {
      const pk = SCHEMA[tableName].pk;
      const vals = distinctNonEmpty(pk);
      if (vals.length) {
        const href = hashFor({kind:"lookup", table: tableName, col: pk, values: vals});
        actions.push('<button data-href="' + escapeHtml(href) + '">Show only these ' + vals.length + ' row' + (vals.length === 1 ? '' : 's') + '</button>');
      }
    }

    const bar = document.createElement("div");
    bar.id = "selbar";
    bar.className = "select-bar";
    bar.innerHTML = '<span class="label">' + set.size + ' row' + (set.size === 1 ? '' : 's') + ' selected</span>' +
      actions.join("") +
      '<button class="clear" id="selclear">Clear</button>';
    document.body.appendChild(bar);

    for (const b of bar.querySelectorAll("button[data-href]")) {
      b.addEventListener("click", () => { location.hash = b.dataset.href; });
    }
    document.getElementById("selclear").addEventListener("click", () => { set.clear(); applyRoute(); });
  }

  // ---------- Overview ----------
  function renderHome() {
    const main = document.getElementById("main");
    const parts = [];
    parts.push('<div class="view-header"><h2>Overview</h2><div class="meta">Click any foreign-key value to drill into the linked records.</div></div>');
    const order = ["iteration_log", "cost_detail", "schedule_detail", "lateness_detail", "drainage_detail", "carrying_detail", "excess_detail", "priority_detail"];
    for (const t of order) {
      const s = SCHEMA[t];
      const fkList = s.fks.length
        ? s.fks.map(fk => '<li><code>' + escapeHtml(fk.col) + '</code> → ' + escapeHtml(SCHEMA[fk.table].title) + ' (<code>' + escapeHtml(fk.pk) + '</code>)</li>').join("")
        : '<li><em>(leaf table)</em></li>';
      parts.push(
        '<div class="schema-card">' +
          '<h3><a href="' + hashFor({kind:"table", table:t}) + '" style="text-decoration:none;color:inherit">' + escapeHtml(s.title) + '</a> ' +
            '<span style="font-weight:normal;color:#777;font-size:12px">· ' + TABLES[t].rowCount.toLocaleString() + ' rows' +
            (s.pk ? ' · pk <code>' + escapeHtml(s.pk) + '</code>' : '') +
            '</span></h3>' +
          '<ul>' + fkList + '</ul>' +
        '</div>'
      );
    }
    main.innerHTML = parts.join("");
  }

  // ---------- Crumbs ----------
  function renderCrumbs(route) {
    const el = document.getElementById("crumbs");
    if (route.kind === "home") { el.innerHTML = '<a href="#/home">Overview</a>'; return; }
    const parts = ['<a href="#/home">Overview</a>'];
    parts.push('<span class="sep">›</span>');
    parts.push('<a href="' + hashFor({kind:"table", table: route.table}) + '">' + escapeHtml(SCHEMA[route.table].title) + '</a>');
    if (route.kind === "lookup") {
      parts.push('<span class="sep">›</span>');
      const vs = route.values || [];
      const op = vs.length === 1 ? '=' : '∈';
      const disp = vs.length === 1 ? escapeHtml(vs[0]) : '{' + (vs.length <= 6 ? vs.map(escapeHtml).join(', ') : vs.slice(0, 5).map(escapeHtml).join(', ') + ' …(+' + (vs.length - 5) + ')') + '}';
      parts.push('<span>' + escapeHtml(route.col) + ' ' + op + ' ' + disp + '</span>');
    }
    el.innerHTML = parts.join("");
  }

  // ---------- Dispatch ----------
  function applyRoute() {
    const route = parseHash();
    renderNav(route);
    renderCrumbs(route);
    if (route.kind === "home") {
      renderHome();
    } else if (route.kind === "table") {
      if (!TABLES[route.table]) { document.getElementById("main").innerHTML = '<div class="empty">Unknown table: ' + escapeHtml(route.table) + '</div>'; return; }
      renderTable(route.table, null, route);
    } else if (route.kind === "lookup") {
      const t = TABLES[route.table];
      if (!t) { document.getElementById("main").innerHTML = '<div class="empty">Unknown table.</div>'; return; }
      const colIdx = COLINDEX[route.table][route.col];
      if (colIdx === undefined) { document.getElementById("main").innerHTML = '<div class="empty">Unknown column.</div>'; return; }
      const wanted = new Set(route.values || []);
      const filteredIdx = [];
      t.rows.forEach((r, i) => { if (wanted.has(r[colIdx])) filteredIdx.push(i); });
      renderTable(route.table, filteredIdx, route);
    }
    window.scrollTo(0, 0);
  }
  window.addEventListener("hashchange", applyRoute);
  applyRoute();
})();
</script>
</body>
</html>
"""
