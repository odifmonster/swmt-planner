#!/usr/bin/env python

import json
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .rlsitem import RlsItem

if TYPE_CHECKING:
    from swmtplanner.products import Greige

__all__ = ['read_rls_items', 'rls_items_from_list']


def rls_items_from_list(
    cfg: list[Any],
    *,
    start_date: datetime,
    greige_by_id: dict[str, 'Greige'],
    source: str = '<demand list>',
) -> dict[str, RlsItem]:
    """Build a `{item_id: RlsItem}` dict from an already-parsed list of
    released-item demand records — the same shape a demand JSON file
    holds. Each entry's `item_id` is looked up in `greige_by_id` for
    the underlying `Greige`; item-side fields (yarn, tgt_wt, safety,
    machines) come from there. `start_date` is plant-wide and passed
    through to every `RlsItem` so week 0's `due_date` lands on it.
    `lead_time_days` becomes a `timedelta`. Demand for an item that is not
    in `greige_by_id` — a style the plant no longer knits in-house, which
    the demand pull still lists — is skipped with a warning rather than
    stopping the run."""
    if not isinstance(cfg, list):
        raise TypeError(f'{source} must be a list of demand objects')
    out: dict[str, RlsItem] = {}
    unknown: list[str] = []
    for entry in cfg:
        if not isinstance(entry, dict):
            raise TypeError(
                f'each entry in {source} must be an object; got {entry!r}'
            )
        item_id = entry['item_id']
        greige = greige_by_id.get(item_id)
        if greige is None:
            unknown.append(str(item_id))
            continue
        rls = RlsItem(
            item=greige,
            start_date=start_date,
            on_hand_lbs=float(entry['on_hand']),
            lead_time=timedelta(days=float(entry['lead_time_days'])),
            weekly_lbs_needed=[float(lbs) for lbs in entry['weekly_dmnd']],
        )
        out[item_id] = rls
    if unknown:
        warnings.warn(
            f'{source}: demand for item(s) not in the styles was skipped: '
            f'{", ".join(unknown)}', stacklevel=2,
        )
    return out


def read_rls_items(
    path: str | Path,
    *,
    start_date: datetime,
    greige_by_id: dict[str, 'Greige'],
) -> dict[str, RlsItem]:
    """Load released-item demand records from a JSON file. Thin wrapper
    over `rls_items_from_list`. The file's shape: a top-level list of
    objects, one per released item — see `rls_items_from_list` for
    the per-entry fields."""
    with open(path) as f:
        cfg = json.load(f)
    return rls_items_from_list(
        cfg,
        start_date=start_date, greige_by_id=greige_by_id,
        source=f'demand file at {path!r}',
    )
