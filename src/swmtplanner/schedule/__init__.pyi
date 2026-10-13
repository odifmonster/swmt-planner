from datetime import datetime
from pathlib import Path
from typing import Any, Collection, Mapping

from swmtplanner.products import BeamSet, Greige, VariantMapFile
from swmtplanner.support import WorkCal
from .activity import (
    Activity, Knit, Waste, Doff, TapeOut, Hanging, Threading,
    StyleChange, RunnerChange, PatternChange, Idle, rebind_sets,
    TAPE_OUT_SINGLE_DURATION, TAPE_OUT_BOTH_DURATION,
    HANGING_SINGLE_DURATION, HANGING_BOTH_DURATION,
    THREADING_SINGLE_DURATION, THREADING_BOTH_DURATION,
    DOFF_DURATION,
    STYLE_CHANGE_DURATION, RUNNER_CHANGE_DURATION, PATTERN_CHANGE_DURATION,
)
from .job import Roll, Job
from .assign import Assigned, SetAssignment, assign_sets
from .machine import (
    Status, Machine, ProductionPlan, PassedOver, Fill, UnhungAssignments, fresh_beam_lbs,
    RUNNING_EFFICIENCY,
    effective_rate,
)
from .inventory import Inventory, InventoryView, build_inventory, worth_stocking
from .capacity import (
    ChangeoverCapacity, CapacityView, Resource, Period, Slot,
    capacity_from_dict, DEFAULT_RESOURCES,
)

__all__ = [
    'Activity', 'Knit', 'Waste', 'Doff', 'TapeOut', 'Hanging', 'Threading',
    'StyleChange', 'RunnerChange', 'PatternChange', 'Idle',
    'Roll', 'Job',
    'TAPE_OUT_SINGLE_DURATION', 'TAPE_OUT_BOTH_DURATION',
    'HANGING_SINGLE_DURATION', 'HANGING_BOTH_DURATION',
    'THREADING_SINGLE_DURATION', 'THREADING_BOTH_DURATION',
    'DOFF_DURATION',
    'STYLE_CHANGE_DURATION', 'RUNNER_CHANGE_DURATION', 'PATTERN_CHANGE_DURATION',
    'Status', 'Machine', 'ProductionPlan', 'PassedOver', 'Fill', 'UnhungAssignments', 'fresh_beam_lbs',
    'RUNNING_EFFICIENCY', 'effective_rate', 'rebind_sets',
    'Inventory', 'InventoryView', 'build_inventory', 'worth_stocking',
    'ChangeoverCapacity', 'CapacityView', 'Resource', 'Period', 'Slot',
    'capacity_from_dict', 'DEFAULT_RESOURCES',
    'read_machines', 'machines_from_list',
    'Assigned', 'SetAssignment', 'assign_sets',
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
    blacklist: Collection[str] = ...,
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
    blacklist: Collection[str] = ...,
) -> dict[str, Machine]:
    """`blacklist` (merge codes, `products.normalize_blacklist`) stamps the
    mounted and queued sets it names `blacklisted`: a mounted one makes its
    bar foreign, a queued one is passed over at the hang.
    An entry's optional `init_top_set` / `init_btm_set` is a
    `{set_no, merge, vendor}` object (or a bare set number); `beam_sets`
    (inventory export by set number, matched by set number + vendor) fills
    in what it leaves out. `assigned_sets` (records of set_no / merge /
    vendor / machine / bar, bar 1 the bottom) become each machine bar's
    queue of next-up sets."""
    ...
