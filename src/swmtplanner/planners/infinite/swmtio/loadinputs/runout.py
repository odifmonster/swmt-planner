#!/usr/bin/env python

"""`compute_runout` — the set on every bar in use and the pounds left on
it, reconstructed from what has been knit off it since it was threaded.

For each machine in `last_tkt` and each bar with a set on it: the latest
threading naming the bar gives the set and its initial weight (split
evenly across the bars the ticket names). Off that come: the racks the
roll in progress at threading wound after run-out (its total minus the
racks at run-out), every roll doffed since in full, and the racks wound
so far on the roll in progress now (the racks file) — each converted to
pounds by the roll's style's rack weight and the bar's share. A bar with
no threading in the window falls back to the plant's own record: the set
from `last_tkt`, the pounds from `threaded`'s `rem_lbs`, else `0.0`; it
is reported either way.

See `planners/infinite/swmtio/DESIGN.md` ("compute_runout").
"""

from datetime import datetime
from typing import Any

import pandas as pd

from .common import (
    as_float, as_str, from_iso_plant, is_null, log, planner_machine_id,
    to_plant_naive,
)

BARS = (1, 2, 3, 4)


def parse_bars(text: Any) -> list[int]:
    """A threading ticket's `bars` (`1-2`) → `[1, 2]`."""
    return [int(p) for p in str(text).split('-') if p.strip()]


class _Styles:
    """`rack_wt` and per-bar `pct` lookups over the variants table; an
    unknown style raises `KeyError`."""

    def __init__(self, variants: pd.DataFrame):
        self._rows = {str(r.variant): r for r in variants.itertuples(index=False)
                      if not is_null(r.variant)}

    def _row(self, style: Any):
        try:
            return self._rows[str(style)]
        except KeyError:
            raise KeyError(f'style {style!r} is not in the variants table') from None

    def lbs_per_rack(self, style: Any) -> float:
        wt = as_float(self._row(style).rack_wt)
        return 0.0 if wt is None else wt / 100

    def bar_share(self, style: Any, bar: int) -> float:
        pct = as_float(getattr(self._row(style), f'bar{bar}_pct'))
        return 0.0 if pct is None else pct / 100


def _latest_threadings(threadings: pd.DataFrame) -> dict[tuple[str, int], Any]:
    """`(machine, bar) → the latest threading row naming that bar`."""
    latest: dict[tuple[str, int], Any] = {}
    for row in threadings.itertuples(index=False):
        if is_null(row.start_ts) or is_null(row.machine):
            continue
        machine = planner_machine_id(row.machine)
        for bar in parse_bars(row.bars):
            prev = latest.get((machine, bar))
            if prev is None or row.start_ts > prev.start_ts:
                latest[(machine, bar)] = row
    return latest


def _threaded_lbs(threaded: pd.DataFrame) -> dict[tuple[str, int], float]:
    """`(machine, bar) → rem_lbs` from the plant's threaded report."""
    out: dict[tuple[str, int], float] = {}
    for row in threaded.itertuples(index=False):
        lbs = as_float(row.rem_lbs)
        if is_null(row.machine) or is_null(row.bar) or lbs is None:
            continue
        out[(planner_machine_id(row.machine), int(row.bar))] = lbs
    return out


def racks_on_roll(racks: pd.DataFrame) -> dict[str, float]:
    """`machine → racks wound so far on its roll in progress` (the racks
    file), machines in the planner's form; rows with no count dropped."""
    out: dict[str, float] = {}
    for row in racks.itertuples(index=False):
        r = as_float(row.racks)
        if not is_null(row.machine) and r is not None:
            out[planner_machine_id(row.machine)] = r
    return out


def _consumed(rolls: list[dict[str, Any]], threaded_at: datetime, racks_at_ro: float,
              racks_now: float | None, now_style: Any, bar: int,
              styles: _Styles) -> float:
    """Pounds knit off `bar` since `threaded_at`: from the roll in progress
    then (its racks past run-out), every roll doffed after it, and the roll
    in progress now (`racks_now`, style `now_style`)."""
    lbs = 0.0
    later = [r for r in rolls if from_iso_plant(r['doff_ts']) > threaded_at]
    for i, roll in enumerate(later):
        total = as_float(roll['racks']) or 0.0
        if i == 0:
            # The roll in progress at threading. Racks at run-out beyond its
            # total mean they were counted on an earlier roll: the whole
            # roll came off the new set.
            racks = total - racks_at_ro if racks_at_ro <= total else total
        else:
            racks = total
        lbs += racks * styles.lbs_per_rack(roll['style']) * styles.bar_share(roll['style'], bar)
    if racks_now is not None and not is_null(now_style):
        lbs += racks_now * styles.lbs_per_rack(now_style) * styles.bar_share(now_style, bar)
    return lbs


def compute_runout(
    threadings: pd.DataFrame,
    doffed: dict[str, list[dict[str, Any]]],
    racks: pd.DataFrame,
    variants: pd.DataFrame,
    last_tkt: pd.DataFrame,
    threaded: pd.DataFrame,
) -> dict[str, dict[int, dict[str, Any]]]:
    """`{machine: {bar: {set_no, merge, vendor, lbs}}}` — see the module doc."""
    styles = _Styles(variants)
    latest = _latest_threadings(threadings)
    fallback = _threaded_lbs(threaded)
    on_roll = racks_on_roll(racks)

    out: dict[str, dict[int, dict[str, Any]]] = {}
    for tkt in last_tkt.itertuples(index=False):
        if is_null(tkt.machine):
            continue
        machine = planner_machine_id(tkt.machine)
        rolls = doffed.get(machine, [])
        bars: dict[int, dict[str, Any]] = {}
        for bar in BARS:
            if is_null(getattr(tkt, f'bar{bar}_set_no')):
                continue
            thr = latest.get((machine, bar))
            if thr is None:
                lbs = fallback.get((machine, bar))
                log.warning('runout: %s bar %d has no threading in the window; '
                            'using %s', machine, bar,
                            f'the threaded report ({lbs} lbs)' if lbs is not None else '0 lbs')
                bars[bar] = {
                    'set_no': as_str(getattr(tkt, f'bar{bar}_set_no')),
                    'merge': as_str(getattr(tkt, f'bar{bar}_merge')),
                    'vendor': as_str(getattr(tkt, f'bar{bar}_vendor')),
                    'lbs': 0.0 if lbs is None else lbs,
                }
                continue
            share = (as_float(thr.init_lbs) or 0.0) / len(parse_bars(thr.bars))
            used = _consumed(rolls, to_plant_naive(thr.start_ts),
                             as_float(thr.racks) or 0.0, on_roll.get(machine),
                             tkt.style, bar, styles)
            remaining = share - used
            if remaining < 0:
                log.warning('runout: %s bar %d set %s ran out (%.1f lbs over); 0 left',
                            machine, bar, thr.set_no, -remaining)
                remaining = 0.0
            bars[bar] = {
                'set_no': as_str(thr.set_no), 'merge': as_str(thr.merge),
                'vendor': as_str(thr.vendor), 'lbs': remaining,
            }
        out[machine] = bars
    return out
