#!/usr/bin/env python

"""`gen_machines` — the machines file: one record per machine on the
floor (the machine status's rows, in its order) saying what it is
running, its status, which sets are on its bottom and top bars with how
many pounds left, and how much is wound on the roll in progress.

The sets and their pounds come from `compute_runout`'s output; the
style, status and the sets' fallback identities from the machine status
(the plant's last ticket, reconciled); the bar grouping from `variants`
(bars carrying ends, grouped by merge, the group with bar 1 the bottom
set); the roll from the racks file × the status's `rack_wt` / 100. A
style that cannot be grouped falls back to bar 1 = bottom, bars 2–4 =
top, and is reported.

See `planners/infinite/swmtio/DESIGN.md` ("gen_machines").
"""

from typing import Any

import pandas as pd

from .common import as_float, as_str, is_null, log, planner_machine_id
from .runout import BARS, racks_on_roll

NEW_LINE = ('M', 'N', 'O', 'P')
FALLBACK_GROUPS = ((1,), (2, 3, 4))
DEFAULT_STATUS = 'running'


def is_new(machine: str) -> bool:
    """`True` for the new line: machines lettered `M`, `N`, `O` or `P`."""
    return machine[:1].upper() in NEW_LINE


def bar_groups(variants: pd.DataFrame, style: Any) -> tuple[tuple[int, ...], tuple[int, ...]] | None:
    """`(bottom bars, top bars)` for `style`: its bars carrying ends grouped
    by merge, the group holding bar 1 the bottom set. `None` when the
    style is not in `variants` or its bars do not form exactly two groups."""
    if is_null(style):
        return None
    rows = variants[variants['variant'].astype('string') == str(style)]
    if len(rows) == 0:
        return None
    row = next(rows.itertuples(index=False))
    groups: dict[str, list[int]] = {}
    for bar in BARS:
        ends = as_float(getattr(row, f'bar{bar}_ends'))
        if ends is None or ends <= 0:
            continue
        merge = as_str(getattr(row, f'bar{bar}_merge')) or ''
        groups.setdefault(merge, []).append(bar)
    if len(groups) != 2:
        return None
    btm = next((g for g in groups.values() if 1 in g), None)
    if btm is None:
        return None
    top = next(g for g in groups.values() if g is not btm)
    return tuple(btm), tuple(top)


def _set_identity(machine: str, bars: tuple[int, ...], bar_runout: dict[int, dict[str, Any]],
                  status: Any) -> dict[str, Any] | None:
    """`{set_no, merge, vendor}` of the set on `bars`, from the first bar
    that has one: its `runout` entry, else the status row's `bar<n>_*`
    columns (reported), else `None`."""
    for bar in bars:
        entry = bar_runout.get(bar)
        if entry is not None:
            return {'set_no': entry.get('set_no'), 'merge': entry.get('merge'),
                    'vendor': entry.get('vendor')}
    for bar in bars:
        set_no = as_str(getattr(status, f'bar{bar}_set_no'))
        if set_no is None:
            continue
        log.warning('machines: %s bar %d not in runout; set %s taken from the machine status',
                    machine, bar, set_no)
        return {'set_no': set_no, 'merge': as_str(getattr(status, f'bar{bar}_merge')),
                'vendor': as_str(getattr(status, f'bar{bar}_vendor'))}
    return None


def gen_machines(
    runout: dict[str, dict[int, dict[str, Any]]],
    machine_status: pd.DataFrame,
    racks: pd.DataFrame,
    variants: pd.DataFrame,
) -> list[dict[str, Any]]:
    """The machines file's records — see the module doc."""
    on_roll = racks_on_roll(racks)

    out: list[dict[str, Any]] = []
    for status in machine_status.itertuples(index=False):
        if is_null(status.machine):
            continue
        machine = planner_machine_id(status.machine)
        bar_runout = runout.get(machine, {})
        item = as_str(status.style)
        state = as_str(status.status) or DEFAULT_STATUS
        groups = bar_groups(variants, item)
        if groups is None:
            log.warning('machines: %s style %s does not group into two sets; '
                        'using bar 1 = bottom, bars 2-4 = top', machine, item)
            groups = FALLBACK_GROUPS
        btm, top = groups
        lbs = lambda bars: sum((as_float(bar_runout[b].get('lbs')) or 0.0
                                for b in bars if b in bar_runout), 0.0)
        racks_now = on_roll.get(machine)
        rack_wt = as_float(status.rack_wt)
        roll_lbs = (racks_now * rack_wt / 100
                    if racks_now is not None and rack_wt is not None else 0.0)
        out.append({
            'id': machine,
            'is_new': is_new(machine),
            'init_item': item,
            'status': state,
            'init_top_lbs': lbs(top),
            'init_btm_lbs': lbs(btm),
            'init_roll_lbs': roll_lbs,
            'init_btm_set': _set_identity(machine, btm, bar_runout, status),
            'init_top_set': _set_identity(machine, top, bar_runout, status),
        })
    return out
