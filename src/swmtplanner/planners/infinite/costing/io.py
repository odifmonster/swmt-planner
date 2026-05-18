#!/usr/bin/env python

import json
from dataclasses import fields
from pathlib import Path

from .costing import CostWeights

__all__ = ['load_weights']


def load_weights(path: str | Path) -> CostWeights:
    """Load a `CostWeights` from a JSON file.

    Expected file shape: a top-level object with one key per
    `CostWeights` field (Phase 1: `lateness`, `drainage`, `carrying`,
    `excess`, `tape_out_single`, `tape_out_both`, `family_change`,
    `idle_time`; Phase 2 will add `priority` and `level_loading`):

        {
            "lateness": 10.0,
            "drainage": 1.0,
            "carrying": 1.0,
            "excess": 5.0,
            "tape_out_single": 100.0,
            "tape_out_both": 150.0,
            "family_change": 50.0,
            "idle_time": 10.0
        }

    All `CostWeights` fields are required (no implicit defaults); the
    JSON must contain every key. Extra keys in the JSON raise
    `TypeError` so a typo doesn't silently get dropped."""
    with open(path) as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        raise TypeError(
            f'weights file at {path!r} must contain a top-level object'
        )

    expected = {f.name for f in fields(CostWeights)}
    got = set(cfg.keys())

    missing = expected - got
    if missing:
        raise TypeError(
            f'weights file at {path!r} is missing required keys: '
            f'{sorted(missing)}'
        )
    extra = got - expected
    if extra:
        raise TypeError(
            f'weights file at {path!r} has unknown keys: {sorted(extra)}'
        )

    return CostWeights(**{k: float(cfg[k]) for k in expected})
