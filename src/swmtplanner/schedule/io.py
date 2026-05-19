#!/usr/bin/env python

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TYPE_CHECKING

from swmtplanner.products import BeamSet
from .machine import Machine

if TYPE_CHECKING:
    from swmtplanner.products import Greige
    from swmtplanner.support import WorkCal

__all__ = ['read_machines', 'machines_from_list']


def machines_from_list(
    cfg: list[Any],
    *,
    start_date: datetime,
    workcal: 'WorkCal',
    greige_by_id: dict[str, 'Greige'],
    source: str = '<machines list>',
) -> dict[str, Machine]:
    """Build a `{machine_id: Machine}` dict from an already-parsed list
    of machine records — the same shape a machines JSON file holds.

    Each entry's `init_item` is resolved against `greige_by_id`; the
    initial top and bottom beam yarns are taken from the resolved
    `Greige`'s `configuration` (a machine currently set up to run an
    item is by definition threaded with that item's beams).
    `style_change_time` and `family_change_time` are decimal hours
    (e.g. `0.1` ⇒ 6 minutes) and become `timedelta`s here.
    `init_top_lbs` and `init_btm_lbs` are the dynamic state — how
    much yarn is left on each bar at `start_date`. `start_date` and
    `workcal` are plant-wide, applied uniformly to every machine."""
    if not isinstance(cfg, list):
        raise TypeError(f'{source} must be a list of machine objects')
    out: dict[str, Machine] = {}
    for entry in cfg:
        if not isinstance(entry, dict):
            raise TypeError(
                f'each entry in {source} must be an object; got {entry!r}'
            )
        init_item = greige_by_id[entry['init_item']]
        item_cfg = init_item.configuration
        machine = Machine(
            id=entry['id'],
            init_item=init_item,
            start=start_date,
            init_top_beam=BeamSet(item_cfg.top_beam),
            init_top_lbs=float(entry['init_top_lbs']),
            init_btm_beam=BeamSet(item_cfg.btm_beam),
            init_btm_lbs=float(entry['init_btm_lbs']),
            workcal=workcal,
            simple_change_duration=timedelta(
                hours=float(entry['style_change_time']),
            ),
            family_change_duration=timedelta(
                hours=float(entry['family_change_time']),
            ),
            is_new=bool(entry['is_new']),
        )
        out[machine.id] = machine
    return out


def read_machines(
    path: str | Path,
    *,
    start_date: datetime,
    workcal: 'WorkCal',
    greige_by_id: dict[str, 'Greige'],
) -> dict[str, Machine]:
    """Load machine records from a JSON file. Thin wrapper over
    `machines_from_list`. The file's shape: a top-level list of
    objects, one per machine — see `machines_from_list` for the
    per-entry fields."""
    with open(path) as f:
        cfg = json.load(f)
    return machines_from_list(
        cfg,
        start_date=start_date, workcal=workcal,
        greige_by_id=greige_by_id,
        source=f'machines file at {path!r}',
    )
