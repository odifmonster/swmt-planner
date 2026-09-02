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
    greige-style records — the same shape a greige-styles JSON file holds.

    Per-entry fields used:
      - `id`; `pattern` (the greige's **family**); `tgt_wt`; `safety`;
      - `beam_cfg` — `{'top': {...}, 'btm': {...}}`, each bar an object carrying
        a `beamset` (the beam name) and an integer `pct` (percent of the rack on
        that bar). `pct` is converted to the 0–1 fraction `Greige` expects
        (top/btm `pct` sum to 100, so the fractions sum to 1);
      - `machine_rates` — a list of `{'id', 'rate'}` objects, converted to the
        `{machine_id: rate}` dict `Greige` expects.
    Other descriptive fields (`gauge`, `width`, `rack_wt`, per-bar `runlen`) are
    not part of the planning model and are ignored. `source` is included in
    error messages so callers (e.g. a higher-level config loader) can point at
    the file or section."""
    if not isinstance(cfg, list):
        raise TypeError(f'{source} must be a list of greige objects')
    out: dict[str, Greige] = {}
    for entry in cfg:
        if not isinstance(entry, dict):
            raise TypeError(
                f'each entry in {source} must be an object; got {entry!r}'
            )
        top = entry['beam_cfg']['top']
        btm = entry['beam_cfg']['btm']
        machines = {
            m['id']: float(m['rate']) for m in entry['machine_rates']
        }
        greige = Greige(
            id=entry['id'],
            family=entry['pattern'],
            tgt_wt=float(entry['tgt_wt']),
            top_beam=top['beamset'],
            top_pct=float(top['pct']) / 100.0,
            btm_beam=btm['beamset'],
            btm_pct=float(btm['pct']) / 100.0,
            safety=float(entry['safety']),
            machines=machines,
        )
        out[greige.id] = greige
    return out


def read_greige_styles(path: str | Path) -> dict[str, Greige]:
    """Load greige-style records from a JSON file. Thin wrapper over
    `greige_styles_from_list`. The file's shape: a top-level list of objects,
    one per greige — see `greige_styles_from_list` for the per-entry fields
    (`id` / `pattern` / `tgt_wt` / `safety`, the nested `beam_cfg`, and
    `machine_rates`)."""
    with open(path) as f:
        cfg = json.load(f)
    return greige_styles_from_list(
        cfg, source=f'greige-styles file at {path!r}',
    )
