from datetime import datetime
from pathlib import Path
from typing import Any

from swmtplanner.products import Greige
from swmtplanner.support import WorkCal
from .activity import (
    Activity, Knit, Waste, TapeOut, BeamLoad, StyleChange, Idle,
    TAPE_OUT_SINGLE_DURATION, TAPE_OUT_BOTH_DURATION, BEAM_LOAD_DURATION,
)
from .job import Roll, Job
from .machine import Status, Machine, ProductionPlan, fresh_beam_lbs

__all__ = [
    'Activity', 'Knit', 'Waste', 'TapeOut', 'BeamLoad', 'StyleChange', 'Idle',
    'Roll', 'Job',
    'TAPE_OUT_SINGLE_DURATION', 'TAPE_OUT_BOTH_DURATION', 'BEAM_LOAD_DURATION',
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
