from pathlib import Path

import pandas as pd

from .loop import PlanReport

__all__ = [
    'demand_dataframe',
    'schedule_dataframe', 'production_dataframe', 'xref_dataframe',
    'unmet_demand_dataframe',
    'late_orders_dataframe', 'changeovers_dataframe', 'prior_jobs_dataframe',
    'unassign_dataframe',
    'write_plan_report_xlsx',
]


def demand_dataframe(report: PlanReport) -> pd.DataFrame: ...
def schedule_dataframe(report: PlanReport) -> pd.DataFrame: ...
def production_dataframe(report: PlanReport) -> pd.DataFrame: ...
def xref_dataframe(report: PlanReport) -> pd.DataFrame: ...
def late_orders_dataframe(report: PlanReport) -> pd.DataFrame: ...
def unmet_demand_dataframe(report: PlanReport) -> pd.DataFrame: ...
def unassign_dataframe(report: PlanReport) -> pd.DataFrame:
    """The `unassign` sheet: assigned sets the plan passed over at a hang
    (`queued`) or took off a bar unthreaded (`hung`), with the bar's
    requirement and the reason; empty with the same columns when none."""
    ...
def write_plan_report_xlsx(
    report: PlanReport, path: str | Path,
) -> None: ...


def prior_jobs_dataframe(report: PlanReport) -> pd.DataFrame:
    """The `prior_jobs` sheet: one row per prior-plan job with its fate
    (machine, prior_job, item, rolls, order, due_date, start, status, job_id,
    note), in start order."""
    ...
