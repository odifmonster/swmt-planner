#!/usr/bin/env python

"""`gen_inventory` — the beam-set inventory and the assigned sets.

The inventory is the `ACTIVE` table filtered (a set with a comment or no
`beams` is dropped), one record per set flagged `assigned` when it has an
assignment date. The assigned sets are every `ASSIGNED` row — each a place
in a bar's queue — with the floor's status note for that machine and bar
(`inventory` when the floor file has none), in queue order: machine, bar,
assignment time. A floor note naming two bars (`2/3`) applies to both.

See `planners/infinite/swmtio/DESIGN.md` ("gen_inventory").
"""

from typing import Any

import pandas as pd

from .common import as_float, as_int, as_str, is_null, iso_plant, planner_machine_id

DEFAULT_STATUS = 'inventory'


def _inventory_record(row: Any) -> dict[str, Any]:
    return {
        'set_no': as_str(row.set_no),
        'received': iso_plant(row.rcv_date),
        'assigned': not is_null(row.assign_date),
        'merge': as_str(row.merge),
        'vendor': as_str(row.vendor),
        'lbs': as_float(row.lbs),
        'beams': as_int(row.beams),
        'ends': as_int(row.ends),
        'denier': as_int(row.denier),
        'luster': as_str(row.luster),
        'desc': as_str(row.yarn_type),
        'size': as_str(row.beam_size),
    }


def _assigned_record(row: Any, status: str) -> dict[str, Any]:
    return {
        'set_no': as_str(row.set_no),
        'assigned': iso_plant(row.assn_ts),
        'merge': as_str(row.merge),
        'vendor': as_str(row.vendor),
        'lbs': as_float(row.lbs),
        'beams': as_int(row.beams),
        'ends': as_int(row.ends),
        'luster': as_str(row.luster),
        'desc': as_str(row.yarn_type),
        'machine': planner_machine_id(row.machine),
        'bar': as_int(row.bar),
        'status': status,
        'size': as_str(row.beam_size),
    }


def floor_status_map(floor_status: pd.DataFrame) -> dict[tuple[str, int], str]:
    """`(machine, bar) → status` from the floor file; a note whose `bar`
    names several bars (`2/3`) is entered under each. Machines are keyed
    in the planner's form."""
    out: dict[tuple[str, int], str] = {}
    for row in floor_status.itertuples(index=False):
        if is_null(row.machine) or is_null(row.bar) or is_null(row.status):
            continue
        machine = planner_machine_id(row.machine)
        for part in str(row.bar).split('/'):
            part = part.strip()
            if part:
                out[(machine, int(part))] = str(row.status)
    return out


def gen_inventory(
    active: pd.DataFrame,
    assigned: pd.DataFrame,
    floor_status: pd.DataFrame,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(the beam-set inventory, the assigned sets) — see the module doc."""
    keep = active['comments'].isna() & active['beams'].notna()
    inventory = [_inventory_record(r) for r in active[keep].itertuples(index=False)]

    statuses = floor_status_map(floor_status)
    queue = assigned.sort_values(['machine', 'bar', 'assn_ts'], kind='stable')
    assigned_sets = []
    for row in queue.itertuples(index=False):
        machine, bar = planner_machine_id(row.machine), as_int(row.bar)
        status = statuses.get((machine, bar), DEFAULT_STATUS)
        assigned_sets.append(_assigned_record(row, status))
    return inventory, assigned_sets
