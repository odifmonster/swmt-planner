from datetime import tzinfo
from pathlib import Path
from typing import Any, Mapping

from swmtplanner.schedule import Machine
from .loop import PlanReport

__all__ = [
    'PLANT_TZ',
    'schedule_json', 'write_schedule_json',
    'machines_schedule_json', 'write_machines_schedule_json',
]

PLANT_TZ: tzinfo
"""The plant's local time zone (America/New_York) — what the planner's naive
datetimes mean. The JSON output converts them to UTC."""


def schedule_json(report: PlanReport, tz: tzinfo = ...) -> list[dict[str, Any]]:
    """One `{"id", "schedule": [...]}` object per machine: its jobs and
    orphaned activities in chronological order (see planners/infinite/DESIGN.md,
    "Schedule JSON"). Timestamps are written in UTC, `YYYY-MM-DD HH:MM:SS`,
    whole seconds; `tz` is the zone the planner's times are in."""
    ...


def machines_schedule_json(
    machines: Mapping[str, Machine], tz: tzinfo = ...,
) -> list[dict[str, Any]]:
    """The same objects straight from `Machine`s — for schedules built
    without a `PlanReport` (the manual scheduler)."""
    ...


def write_schedule_json(
    report: PlanReport, path: str | Path, tz: tzinfo = ...,
) -> None: ...
def write_machines_schedule_json(
    machines: Mapping[str, Machine], path: str | Path, tz: tzinfo = ...,
) -> None: ...
