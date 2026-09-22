#!/usr/bin/env python

"""The schedule as JSON — the operator-facing hand-off of a plan.

One object per machine: `{"id", "schedule": [...]}`. The schedule is the
machine's committed jobs plus every activity that belongs to no job
(`Idle`, `Waste`, a first tape-out with no prior job), in chronological
order; each entry carries `kind` (`"job"` or the activity class name) and
`id`. A job lists its rolls (derived id `<job id>-R<n>`, item, the distinct
variants its knits carry, lbs, completion time, knit ids) and its activities.
Activities carry their dataclass fields; a `Greige` reduces to its id and a
`BeamSet` to `set_no` / `merge` / `vendor` / `desc` / `lbs`.

Datetimes are written the way the plant's systems store them: **UTC**,
`YYYY-MM-DD HH:MM:SS`, whole seconds. The planner's own clock is the plant's
local time (`PLANT_TZ`, America/New_York), so every timestamp is converted
on the way out — daylight saving included — and its microseconds dropped.
See "Schedule JSON" in `planners/infinite/DESIGN.md`."""

import json
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from typing import Any, Mapping, TYPE_CHECKING
from zoneinfo import ZoneInfo

from swmtplanner.schedule import (
    Knit, Waste, Doff, TapeOut, Hanging, Threading,
    StyleChange, RunnerChange, PatternChange, Idle,
)

if TYPE_CHECKING:
    from swmtplanner.products import BeamSet
    from swmtplanner.schedule import Activity, Job, Machine
    from .loop import PlanReport

__all__ = [
    'PLANT_TZ',
    'schedule_json', 'write_schedule_json',
    'machines_schedule_json', 'write_machines_schedule_json',
]

# The plant's local time zone — what the planner's naive datetimes mean.
PLANT_TZ: tzinfo = ZoneInfo('America/New_York')


def _dt(t: datetime, tz: tzinfo) -> str:
    """`t` (a naive planner time in `tz`) as the plant system's UTC timestamp,
    `YYYY-MM-DD HH:MM:SS`, microseconds truncated. An already-aware datetime
    is converted as is."""
    if t.tzinfo is None:
        t = t.replace(tzinfo=tz)
    return t.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def _beam_set(bs: 'BeamSet | None') -> dict | None:
    if bs is None:
        return None
    return {'set_no': bs.set_no, 'merge': bs.merge, 'vendor': bs.vendor,
            'desc': bs.desc.id, 'lbs': bs.lbs}


def _activity(a: 'Activity', tz: tzinfo) -> dict[str, Any]:
    """An activity's JSON object: `kind`, `id`, `start`, `end`, then the
    type's own fields with greiges and beam sets reduced."""
    out: dict[str, Any] = {
        'kind': type(a).__name__, 'id': a.id,
        'start': _dt(a.start, tz), 'end': _dt(a.end, tz),
    }
    if isinstance(a, Knit):
        out.update(item=a.item.id, lbs=a.lbs, variant=a.variant)
    elif isinstance(a, Waste):
        out.update(beam=_beam_set(a.beam), bar=a.bar, lbs=a.lbs)
    elif isinstance(a, (TapeOut, Hanging)):
        out.update(bars=a.bars, top_beam=_beam_set(a.top_beam),
                   btm_beam=_beam_set(a.btm_beam))
    elif isinstance(a, Threading):
        out.update(bars=a.bars)
    elif isinstance(a, (StyleChange, RunnerChange, PatternChange)):
        out.update(from_item=a.from_item.id, to_item=a.to_item.id)
    elif not isinstance(a, (Doff, Idle)):
        raise TypeError(f'unknown activity type: {type(a).__name__}')
    return out


def _job(job: 'Job', tz: tzinfo) -> dict[str, Any]:
    acts = job.activities
    rolls = []
    for n, roll in enumerate(job.rolls, start=1):
        variants: list[str] = []
        for k in roll.knits:
            if k.variant is not None and k.variant not in variants:
                variants.append(k.variant)
        rolls.append({
            'id': f'{job.id}-R{n}', 'item': job.item.id, 'variants': variants,
            'lbs': roll.lbs, 'completion_time': _dt(roll.completion_time, tz),
            'knits': [k.id for k in roll.knits],
        })
    return {
        'kind': 'job', 'id': job.id, 'item': job.item.id,
        'tgt_order': job.tgt_order,
        'start': _dt(acts[0].start, tz) if acts else None,
        'end': _dt(acts[-1].end, tz) if acts else None,
        'total_lbs': job.total_lbs,
        'rolls': rolls,
        'activities': [_activity(a, tz) for a in acts],
    }


def _machine(machine_id: str, activities: 'tuple[Activity, ...]',
             jobs: 'tuple[Job, ...]', tz: tzinfo) -> dict[str, Any]:
    """A machine's schedule: jobs (placed at their first activity's start)
    interleaved with the activities no job claims, chronologically."""
    claimed = {a.id for j in jobs for a in j.activities}
    entries: list[tuple[datetime, int, dict]] = []
    for j in jobs:
        anchor = j.activities[0].start if j.activities else (
            j.rolls[0].completion_time if j.rolls else datetime.min)
        entries.append((anchor, 0, _job(j, tz)))
    for a in activities:
        if a.id not in claimed:
            entries.append((a.start, 1, _activity(a, tz)))
    entries.sort(key=lambda e: (e[0], e[1]))
    return {'id': machine_id, 'schedule': [e[2] for e in entries]}


def schedule_json(report: 'PlanReport', tz: tzinfo = PLANT_TZ) -> list[dict[str, Any]]:
    """The report's per-machine schedules as JSON-ready objects, machines in
    the report's order. `tz` is what the planner's naive times mean; the
    output is UTC."""
    return [
        _machine(m_id, acts, report.jobs_by_machine.get(m_id, ()), tz)
        for m_id, acts in report.schedules.items()
    ]


def machines_schedule_json(machines: 'Mapping[str, Machine]',
                           tz: tzinfo = PLANT_TZ) -> list[dict[str, Any]]:
    """The same objects straight from `Machine`s (their `activities` and
    `jobs`) — for schedules built without a `PlanReport`, e.g. the manual
    scheduler."""
    return [_machine(m_id, m.activities, m.jobs, tz) for m_id, m in machines.items()]


def write_schedule_json(report: 'PlanReport', path: 'str | Path',
                        tz: tzinfo = PLANT_TZ) -> None:
    _dump(schedule_json(report, tz), path)


def write_machines_schedule_json(machines: 'Mapping[str, Machine]',
                                 path: 'str | Path', tz: tzinfo = PLANT_TZ) -> None:
    _dump(machines_schedule_json(machines, tz), path)


def _dump(data: list[dict[str, Any]], path: 'str | Path') -> None:
    with open(path, 'w') as fh:
        json.dump(data, fh, indent=2)
        fh.write('\n')
