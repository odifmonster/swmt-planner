#!/usr/bin/env python

import json
from pathlib import Path
from typing import Any

from .holidays import holidays_from_list, load_holidays
from .workcal import WorkCal

__all__ = ['load_workcal', 'workcal_from_dict']


def workcal_from_dict(
    cfg: dict[str, Any],
    *,
    holidays_base_dir: str | Path | None = None,
    source: str = '<workcal dict>',
) -> WorkCal:
    """Build a `WorkCal` from an already-parsed dict.

    The dict's `holidays` field can be either:

    - A list of holiday objects (inline) — built directly via
      `holidays_from_list`.
    - A path string — opened via `load_holidays`. Relative paths are
      resolved against `holidays_base_dir` if provided; an absolute
      path resolves without needing one. Passing a relative path
      without a base directory is an error.

    Other fields: `work_days` (list of weekday ints, Mon=0), `day_start`
    / `day_end` (hour-of-day ints), `cal_shift` (optional, defaults to
    0). `source` is woven into error messages for context."""
    if not isinstance(cfg, dict):
        raise TypeError(f'{source} must be an object')

    holidays_ref = cfg['holidays']
    if isinstance(holidays_ref, list):
        holidays = holidays_from_list(
            holidays_ref, source=f"{source} ['holidays']",
        )
    elif isinstance(holidays_ref, str):
        holidays_path = Path(holidays_ref)
        if not holidays_path.is_absolute():
            if holidays_base_dir is None:
                raise ValueError(
                    f"{source} has a relative path string for "
                    f"'holidays' but no base directory to resolve it "
                    f'against'
                )
            holidays_path = Path(holidays_base_dir) / holidays_path
        holidays = load_holidays(str(holidays_path))
    else:
        raise TypeError(
            f"{source} ['holidays'] must be a list of holiday objects "
            f'or a path string'
        )

    return WorkCal(
        work_days=list(cfg['work_days']),
        day_start=int(cfg['day_start']),
        day_end=int(cfg['day_end']),
        holidays=holidays,
        cal_shift=int(cfg.get('cal_shift', 0)),
    )


def load_workcal(path: str | Path) -> WorkCal:
    """Load a `WorkCal` from a JSON file. Thin wrapper over
    `workcal_from_dict` — relative `holidays` paths inside the file
    are resolved against the file's own directory."""
    path = Path(path)
    with open(path) as f:
        cfg = json.load(f)
    return workcal_from_dict(
        cfg,
        holidays_base_dir=path.parent,
        source=f'workcal file at {path!r}',
    )
