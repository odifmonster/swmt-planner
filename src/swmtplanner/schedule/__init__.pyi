from datetime import datetime
from pathlib import Path

from swmtplanner.products import Greige
from swmtplanner.support import WorkCal
from .activity import (
    Activity, Job, Waste, TapeOut, BeamLoad, StyleChange, Idle,
    TAPE_OUT_SINGLE_DURATION, TAPE_OUT_BOTH_DURATION, BEAM_LOAD_DURATION,
)
from .machine import Status, Machine, fresh_beam_lbs

__all__ = [
    'Activity', 'Job', 'Waste', 'TapeOut', 'BeamLoad', 'StyleChange', 'Idle',
    'TAPE_OUT_SINGLE_DURATION', 'TAPE_OUT_BOTH_DURATION', 'BEAM_LOAD_DURATION',
    'Status', 'Machine', 'fresh_beam_lbs', 'read_machines',
]


def read_machines(
    path: str | Path, *,
    start_date: datetime,
    workcal: WorkCal,
    greige_by_id: dict[str, Greige],
) -> dict[str, Machine]: ...
