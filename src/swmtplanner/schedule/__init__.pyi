from datetime import datetime
from pathlib import Path
from typing import Any

from swmtplanner.products import Greige
from swmtplanner.support import WorkCal
from .activity import (
    Activity, Knit, Waste, Doff, TapeOut, Hanging, Threading,
    StyleChange, RunnerChange, PatternChange, Idle,
    TAPE_OUT_SINGLE_DURATION, TAPE_OUT_BOTH_DURATION,
    HANGING_SINGLE_DURATION, HANGING_BOTH_DURATION,
    THREADING_SINGLE_DURATION, THREADING_BOTH_DURATION,
    DOFF_DURATION,
    STYLE_CHANGE_DURATION, RUNNER_CHANGE_DURATION, PATTERN_CHANGE_DURATION,
)
from .job import Roll, Job
from .machine import Status, Machine, ProductionPlan, fresh_beam_lbs

__all__ = [
    'Activity', 'Knit', 'Waste', 'Doff', 'TapeOut', 'Hanging', 'Threading',
    'StyleChange', 'RunnerChange', 'PatternChange', 'Idle',
    'Roll', 'Job',
    'TAPE_OUT_SINGLE_DURATION', 'TAPE_OUT_BOTH_DURATION',
    'HANGING_SINGLE_DURATION', 'HANGING_BOTH_DURATION',
    'THREADING_SINGLE_DURATION', 'THREADING_BOTH_DURATION',
    'DOFF_DURATION',
    'STYLE_CHANGE_DURATION', 'RUNNER_CHANGE_DURATION', 'PATTERN_CHANGE_DURATION',
    'Status', 'Machine', 'ProductionPlan', 'fresh_beam_lbs',
    'read_machines', 'machines_from_list',
]


def read_machines(
    path: str | Path, *,
    start_date: datetime,
    workcal: WorkCal,
    greige_by_id: dict[str, Greige],
) -> dict[str, Machine]: ...
def machines_from_list(
    cfg: list[Any], *,
    start_date: datetime,
    workcal: WorkCal,
    greige_by_id: dict[str, Greige],
    source: str = ...,
) -> dict[str, Machine]: ...
