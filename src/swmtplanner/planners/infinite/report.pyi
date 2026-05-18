from pathlib import Path

import pandas as pd

from .loop import PlanReport

__all__ = [
    'schedule_dataframe', 'production_dataframe', 'unmet_demand_dataframe',
    'write_plan_report_xlsx',
]


def schedule_dataframe(report: PlanReport) -> pd.DataFrame: ...
def production_dataframe(report: PlanReport) -> pd.DataFrame: ...
def unmet_demand_dataframe(report: PlanReport) -> pd.DataFrame: ...
def write_plan_report_xlsx(
    report: PlanReport, path: str | Path,
) -> None: ...
