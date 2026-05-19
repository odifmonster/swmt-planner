#!/usr/bin/env python

import json
from pathlib import Path
from typing import Any

from .greige import Greige

__all__ = ['read_greige_styles', 'greige_styles_from_list']


def greige_styles_from_list(
    cfg: list[Any], source: str = '<greige-styles list>',
) -> dict[str, Greige]:
    """Build a `{greige_id: Greige}` dict from an already-parsed list of
    greige-style records — the same shape a greige-styles JSON file
    holds. `machines` is converted from the JSON's list-of-objects
    form to the `{machine_id: rate}` dict that `Greige` expects.
    `source` is included in error messages so callers (e.g., a
    higher-level config loader) can point at the file or section."""
    if not isinstance(cfg, list):
        raise TypeError(f'{source} must be a list of greige objects')
    out: dict[str, Greige] = {}
    for entry in cfg:
        if not isinstance(entry, dict):
            raise TypeError(
                f'each entry in {source} must be an object; got {entry!r}'
            )
        machines = {
            m['id']: float(m['rate']) for m in entry['machines']
        }
        greige = Greige(
            id=entry['id'],
            family=entry['family'],
            tgt_wt=float(entry['tgt_wt']),
            top_beam=entry['top_beam'],
            top_pct=float(entry['top_pct']),
            btm_beam=entry['btm_beam'],
            btm_pct=float(entry['btm_pct']),
            safety=float(entry['safety']),
            machines=machines,
        )
        out[greige.id] = greige
    return out


def read_greige_styles(path: str | Path) -> dict[str, Greige]:
    """Load greige-style records from a JSON file. Thin wrapper over
    `greige_styles_from_list`. The file's shape: a top-level list of
    objects, one per greige — see `greige_styles_from_list` for the
    per-entry fields."""
    with open(path) as f:
        cfg = json.load(f)
    return greige_styles_from_list(
        cfg, source=f'greige-styles file at {path!r}',
    )
