#!/usr/bin/env python

import json
from pathlib import Path

from .greige import Greige

__all__ = ['read_greige_styles']


def read_greige_styles(path: str | Path) -> dict[str, Greige]:
    """Load greige-style records from a JSON file and return them as a
    `{greige_id: Greige}` dict.

    Expected file shape: a top-level list of objects, one per greige:

        [
            {
                "id": "AUSR7805",
                "family": "C",
                "tgt_wt": 350.0,
                "top_beam": "70D WHT TX 1172X4",
                "top_pct": 0.29,
                "btm_beam": "40D WHT 1172X4 S/L",
                "btm_pct": 0.71,
                "safety": 2100.0,
                "machines": [
                    {"id": "N1", "rate": 51.28},
                    {"id": "N2", "rate": 51.28},
                    ...
                ]
            },
            ...
        ]

    `machines` is converted from a list of `{id, rate}` records to the
    `{machine_id: rate}` dict that `Greige` expects."""
    with open(path) as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        raise TypeError(
            f'greige-styles file at {path!r} must contain a top-level list'
        )

    out: dict[str, Greige] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise TypeError(
                f'each greige-styles entry must be an object; got {entry!r}'
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
