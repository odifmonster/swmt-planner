#!/usr/bin/env python

"""Conventions shared by every `loadinputs` function: machine ids go out in
the planner's form (`B08` → `B8`), timestamps go out as ISO-8601 text with
the plant's UTC offset, and dataframe cells become plain JSON values
(`int` for counts, `float` for numbers, `None` for any null). Reports of
unusable rows go through this module's logger at WARNING.

See `planners/infinite/swmtio/DESIGN.md` ("Producing the planner's inputs").
"""

import logging
import math
import re
from datetime import datetime
from typing import Any

import pandas as pd

from ...schedule_json import PLANT_TZ

log = logging.getLogger('swmtplanner.swmtio.loadinputs')

_MACHINE_RE = re.compile(r'^([A-Za-z]+)0*(\d+)$')


def planner_machine_id(machine: Any) -> str:
    """The planner's form of a machine id: letters plus the number with no
    leading zero (`B08` → `B8`, `N1` → `N1`). Anything else raises
    `ValueError`."""
    text = str(machine).strip().upper()
    m = _MACHINE_RE.match(text)
    if m is None:
        raise ValueError(f'not a machine id: {machine!r}')
    return f'{m[1]}{int(m[2])}'


def is_null(value: Any) -> bool:
    """`True` for every null a dataframe cell can hold."""
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    return isinstance(value, float) and math.isnan(value)


def iso_plant(ts: Any) -> str | None:
    """A naive plant-local timestamp → ISO-8601 text with the plant's UTC
    offset (`2026-10-13T12:14:38-04:00`), to the second; a null → `None`."""
    if is_null(ts):
        return None
    if isinstance(ts, pd.Timestamp):
        ts = ts.to_pydatetime()
    if not isinstance(ts, datetime):
        raise TypeError(f'not a timestamp: {ts!r}')
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=PLANT_TZ)
    return ts.astimezone(PLANT_TZ).isoformat(timespec='seconds')


def from_iso_plant(text: str) -> datetime:
    """The inverse of `iso_plant`: ISO-8601 text with an offset → the naive
    plant-local time."""
    return datetime.fromisoformat(text).astimezone(PLANT_TZ).replace(tzinfo=None)


def to_plant_naive(value: Any) -> datetime | None:
    """A dataframe timestamp cell → naive `datetime` (`None` for a null)."""
    if is_null(value):
        return None
    return value.to_pydatetime() if isinstance(value, pd.Timestamp) else value


def as_int(value: Any) -> int | None:
    """A count cell → `int` (`None` for a null)."""
    return None if is_null(value) else int(value)


def as_float(value: Any) -> float | None:
    """A number cell → `float` (`None` for a null)."""
    return None if is_null(value) else float(value)


def as_str(value: Any) -> str | None:
    """A text cell → `str` (`None` for a null)."""
    return None if is_null(value) else str(value)
