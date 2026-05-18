#!/usr/bin/env python

import json
from pathlib import Path

from .holidays import load_holidays
from .workcal import WorkCal

__all__ = ['load_workcal']


def load_workcal(path: str | Path) -> WorkCal:
    """Load a `WorkCal` from a JSON file.

    Expected file shape:

        {
            "work_days": [0, 1, 2, 3, 4],
            "day_start": 8,
            "day_end": 17,
            "holidays": "holidays.json",
            "cal_shift": 0
        }

    `holidays` is a path to a holidays JSON file in the format
    `load_holidays` consumes. Relative paths are resolved against the
    directory containing the workcal file (so a workcal and its
    referenced holidays can sit next to each other in the same data
    folder). `cal_shift` is optional (defaults to 0)."""
    path = Path(path)
    with open(path) as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        raise TypeError(
            f'workcal file at {path!r} must contain a top-level object'
        )

    holidays_ref = cfg['holidays']
    holidays_path = Path(holidays_ref)
    if not holidays_path.is_absolute():
        holidays_path = path.parent / holidays_path
    holidays = load_holidays(str(holidays_path))

    return WorkCal(
        work_days=list(cfg['work_days']),
        day_start=int(cfg['day_start']),
        day_end=int(cfg['day_end']),
        holidays=holidays,
        cal_shift=int(cfg.get('cal_shift', 0)),
    )
