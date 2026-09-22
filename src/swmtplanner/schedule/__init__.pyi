from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from swmtplanner.products import BeamSet, Greige, VariantMapFile
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
from .inventory import Inventory, InventoryView, build_inventory, worth_stocking

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
    'Inventory', 'InventoryView', 'build_inventory', 'worth_stocking',
    'read_machines', 'machines_from_list',
]


def read_machines(
    path: str | Path, *,
    start_date: datetime,
    workcal: WorkCal,
    greige_by_id: dict[str, Greige],
    variant_masters: Mapping[str, str] | None = ...,
    variant_map: VariantMapFile | None = ...,
    beam_sets: Mapping[str, BeamSet] | None = ...,
    assigned_sets: list[Any] | None = ...,
) -> dict[str, Machine]: ...
def machines_from_list(
    cfg: list[Any], *,
    start_date: datetime,
    workcal: WorkCal,
    greige_by_id: dict[str, Greige],
    variant_masters: Mapping[str, str] | None = ...,
    variant_map: VariantMapFile | None = ...,
    beam_sets: Mapping[str, BeamSet] | None = ...,
    assigned_sets: list[Any] | None = ...,
    source: str = ...,
) -> dict[str, Machine]:
    """An entry's optional `init_top_set` / `init_btm_set` is a
    `{set_no, merge, vendor}` object (or a bare set number); `beam_sets`
    (inventory export by set number, matched by set number + vendor) fills
    in what it leaves out. `assigned_sets` (records of set_no / merge /
    vendor / machine / bar, bar 1 the bottom) become each machine bar's
    queue of next-up sets."""
    ...
