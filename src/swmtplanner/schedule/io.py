#!/usr/bin/env python

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from swmtplanner.products import BeamSet
from .machine import Machine

if TYPE_CHECKING:
    from swmtplanner.products import Greige
    from swmtplanner.support import WorkCal

__all__ = ['read_machines']


def read_machines(
    path: str | Path,
    *,
    start_date: datetime,
    workcal: 'WorkCal',
    greige_by_id: dict[str, 'Greige'],
) -> dict[str, Machine]:
    """Load machine records from a JSON file and return them as a
    `{machine_id: Machine}` dict.

    Expected file shape: a top-level list of objects, one per machine:

        [
            {
                "id": "M1",
                "style_change_time": 0.1,
                "family_change_time": 0.1,
                "is_new": true,
                "init_item": "AUSR7805",
                "init_top_lbs": 2800.0,
                "init_btm_lbs": 1800.0
            },
            ...
        ]

    `style_change_time` and `family_change_time` are in decimal hours
    (e.g. `0.1` ⇒ 6 minutes) and are converted to `timedelta` here.
    `init_item` is resolved against `greige_by_id`; the initial top
    and bottom beam yarns are taken from the resolved `Greige`'s
    `configuration` (a machine currently set up to run an item is by
    definition threaded with that item's beams). `init_top_lbs` and
    `init_btm_lbs` are the dynamic state — how much yarn is left on
    each bar at `start_date`. `start_date` and `workcal` are plant-
    wide and applied uniformly to every machine."""
    with open(path) as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        raise TypeError(
            f'machines file at {path!r} must contain a top-level list'
        )

    out: dict[str, Machine] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise TypeError(
                f'each machine entry must be an object; got {entry!r}'
            )
        init_item = greige_by_id[entry['init_item']]
        cfg = init_item.configuration
        machine = Machine(
            id=entry['id'],
            init_item=init_item,
            start=start_date,
            init_top_beam=BeamSet(cfg.top_beam),
            init_top_lbs=float(entry['init_top_lbs']),
            init_btm_beam=BeamSet(cfg.btm_beam),
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
