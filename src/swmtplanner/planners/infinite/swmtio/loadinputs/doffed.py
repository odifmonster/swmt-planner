#!/usr/bin/env python

"""`gen_doffed` — every roll doffed since the query date, per machine, in
doff order: the retimer's `doffed-rolls.json`.

`doffed` (the `DOFFED` table) is built from the scans — each piece ticket's
scan is its roll's start, the next scan on the machine its end — and misses
rolls on dummy tickets, which cannot be scanned. `tkts_since` (the
`TKTS_SINCE` table) comes from the tickets table and has them, once the
shipping warehouse has processed them. A `tkts_since` roll the scans do
not have, whose span lands inside a scanned roll's, is spliced in after it:
the scanned roll ends where the spliced one starts, and the scanned roll's
successor starts where it ends. One that falls after a machine's last
scanned roll is appended the same way (closing that roll's open end); one
on a machine with no scanned rolls starts the machine's list. One that
lands before the first scanned roll, or straddles two, is reported and
left out. A roll is doffed at its `end_ts`; a roll still open after the
splice is on the machine and is not written.

See `planners/infinite/swmtio/DESIGN.md` ("gen_doffed").
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from .common import as_float, as_str, is_null, iso_plant, log, planner_machine_id


@dataclass
class Roll:
    """A roll on a machine's timeline (times naive plant-local; `end` is
    `None` while the roll is still on the machine)."""
    machine: str
    ticket: str
    style: str | None
    racks: float | None
    rack_wt: float | None
    start: datetime
    end: datetime | None

    @property
    def lbs(self) -> float | None:
        if self.racks is None or self.rack_wt is None:
            return None
        return self.racks * self.rack_wt / 100

    def record(self) -> dict[str, Any]:
        return {
            'ticket_no': self.ticket,
            'style': self.style,
            'racks': self.racks,
            'lbs': self.lbs,
            'doff_ts': iso_plant(self.end),
        }


def _ts(value: Any) -> datetime | None:
    if is_null(value):
        return None
    return value.to_pydatetime() if isinstance(value, pd.Timestamp) else value


def _roll(row: Any) -> Roll:
    return Roll(
        machine=planner_machine_id(row.machine),
        ticket=str(row.ticket), style=as_str(row.style),
        racks=as_float(row.racks), rack_wt=as_float(row.rack_wt),
        start=_ts(row.start_ts), end=_ts(row.end_ts),
    )


def _timelines(doffed: pd.DataFrame) -> dict[str, list[Roll]]:
    """Each machine's scanned rolls, in start order."""
    out: dict[str, list[Roll]] = {}
    for row in doffed.itertuples(index=False):
        if is_null(row.start_ts):
            continue
        roll = _roll(row)
        out.setdefault(roll.machine, []).append(roll)
    for rolls in out.values():
        rolls.sort(key=lambda r: r.start)
    return out


def _host_index(spans: list[tuple[datetime, datetime | None]], roll: Roll) -> int | None:
    """The scanned roll whose (original) span contains `roll`: it starts no
    earlier than the host and ends no later — or the host is the open
    last roll, which anything after it follows. `None` when no span does
    (before the first roll, straddling two, or an open roll inside a
    closed span)."""
    for i, (start, end) in enumerate(spans):
        if roll.start < start:
            continue
        if end is None:
            return i
        if roll.end is not None and roll.end <= end:
            return i
    return None


def _splice(rolls: list[Roll], extras: list[Roll]) -> list[Roll]:
    """Splice the machine's skipped rolls (`extras`, in start order) into
    its scanned `rolls`, each group after the scanned roll whose original
    span holds it: that roll ends where the group's first starts, its
    successor starts where the group's last ends, and the group sits in
    between. A machine with no scanned rolls takes the skipped rolls as
    its list. Returns the rolls that fit nowhere."""
    if not rolls:
        rolls.extend(extras)
        return []
    spans = [(r.start, r.end) for r in rolls]
    groups: dict[int, list[Roll]] = {}
    unplaced: list[Roll] = []
    for roll in extras:
        i = _host_index(spans, roll)
        if i is None:
            unplaced.append(roll)
        else:
            groups.setdefault(i, []).append(roll)
    for i in sorted(groups, reverse=True):          # back to front: indices stay valid
        group = groups[i]
        rolls[i].end = group[0].start
        if i + 1 < len(rolls):
            rolls[i + 1].start = group[-1].end
        rolls[i + 1:i + 1] = group
    return unplaced


def gen_doffed(doffed: pd.DataFrame, tkts_since: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    """`{machine: [roll record, ...]}` — see the module doc."""
    timelines = _timelines(doffed)
    scanned = {str(t) for t in doffed['ticket'] if not is_null(t)}

    extras: dict[str, list[Roll]] = {}
    for row in tkts_since.itertuples(index=False):
        if is_null(row.start_ts) or str(row.ticket) in scanned:
            continue
        roll = _roll(row)
        extras.setdefault(roll.machine, []).append(roll)
    for machine, rolls in extras.items():
        rolls.sort(key=lambda r: r.start)
        for roll in _splice(timelines.setdefault(machine, []), rolls):
            log.warning('doffed: %s ticket %s (%s – %s) fits no scanned roll; left out',
                        machine, roll.ticket, roll.start, roll.end)

    out: dict[str, list[dict[str, Any]]] = {}
    for machine in sorted(timelines):
        rolls = sorted(timelines[machine], key=lambda r: r.start)
        records = []
        for roll in rolls:
            if roll.end is None:
                continue
            if roll.lbs is None:
                log.warning('doffed: %s ticket %s has no racks / rack weight; lbs unknown',
                            machine, roll.ticket)
            records.append(roll.record())
        if records:
            out[machine] = records
    return out
