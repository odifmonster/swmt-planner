#!/usr/bin/env python

import json
from dataclasses import fields
from pathlib import Path
from typing import Any

from .costing import CostWeights

__all__ = ['load_weights', 'weights_from_dict']


def weights_from_dict(
    cfg: dict[str, Any], source: str = '<weights dict>',
) -> CostWeights:
    """Build a `CostWeights` from an already-parsed dict.

    `cfg` must contain every `CostWeights` field as a numeric key —
    Phase 1: `lateness`, `drainage`, `carrying`, `excess`,
    `tape_out_single`, `tape_out_both`, `family_change`, `idle_time`,
    `waste_lbs`; Phase 2 cross-cutting: `priority`, `level_loading`,
    `old_machine`.
    All fields are required (callers set 0 to opt out of a
    contribution). Extra keys raise `TypeError` so a typo isn't
    silently dropped.

    `source` is included in error messages so callers (e.g., a
    higher-level config loader) can point users at the file or section
    where the problem is."""
    if not isinstance(cfg, dict):
        raise TypeError(f'{source} must be an object')

    expected = {f.name for f in fields(CostWeights)}
    got = set(cfg.keys())

    missing = expected - got
    if missing:
        raise TypeError(
            f'{source} is missing required keys: {sorted(missing)}'
        )
    extra = got - expected
    if extra:
        raise TypeError(
            f'{source} has unknown keys: {sorted(extra)}'
        )

    return CostWeights(**{k: float(cfg[k]) for k in expected})


def load_weights(path: str | Path) -> CostWeights:
    """Load a `CostWeights` from a standalone JSON file. Thin wrapper
    over `weights_from_dict` for callers who want a file-based config
    rather than an inline `weights` object inside a larger config.

    Expected file shape: a top-level object with one key per
    `CostWeights` field. See `weights_from_dict` for the field list."""
    with open(path) as f:
        cfg = json.load(f)
    return weights_from_dict(cfg, source=f'weights file at {path!r}')
