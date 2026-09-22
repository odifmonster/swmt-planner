#!/usr/bin/env python

"""`plan machines` — build a machines file from the plant's runtime export.

The export (one object per machine) gives what the machine is running and
how far along it is, in the floor's units:

```
{"id": "N1", "item": "AUSR7980/7",          # plant variant on the machine
 "top-rem": "36:38", "btm-rem": "18:13",    # HH:MM of running time left on
                                             # each bar's set, excluding stops
 "racks-to-doff": 507.4,                    # racks left on the roll in progress
 "top-set": "W2-2620", "btm-set": "2-3750"} # set numbers mounted
```

`item` and the sets are optional: an export that carries only the runtime
numbers is merged onto a **base** machines file (`--base`, defaulting to the
output file when it already exists), which supplies `init_item` and the
mounted `init_top_set` / `init_btm_set` — kept verbatim, so the plant's
`{set_no, merge, vendor}` objects survive a refresh. Machines in the base
but missing from the export are kept unchanged and reported.

The planner wants pounds, so each is converted with the variant table
(`greige-variants.tsv`) and the knit-machine master:

- racks per hour = rpm × 60 / 480 revolutions per rack (the machine's rpm
  from the master — its `wide` rpm for a style 200" or wider);
- lbs per rack = the variant's `rack_wt` / 100;
- a bar's lbs = hours remaining × racks/hour × lbs/rack × that bar's share of
  the weight, where the bars of the variant row are grouped by merge and the
  group holding **bar 1 is the bottom**;
- lbs left on the roll = racks-to-doff × lbs/rack.

Machine ids are normalised (`02` -> `O2`); `is_new` is taken from the
machine master's speed (2200 rpm lines are the new machines). See
`planners/infinite/DESIGN.md`, "CLI entry point"."""

import csv
import json
import re
from pathlib import Path
from typing import Annotated, Any

import typer

__all__ = ['machines', 'convert_runtime_export']

REVS_PER_RACK = 480
NEW_MACHINE_RPM = 2200          # the new line runs at 2200; legacy at 900

_Runtime = Annotated[Path, typer.Argument(
    exists=True, dir_okay=False, help='The runtime export JSON (see module doc).',
)]
_InputDir = Annotated[Path, typer.Argument(
    exists=True, file_okay=False,
    help='Directory holding greige-variants.tsv and knit-machine-master.json.',
)]
_Out = Annotated[Path | None, typer.Option(
    '--out', '-o', dir_okay=False,
    help='Output machines JSON. Defaults to <input-dir>/machines-new.json.',
)]
_Base = Annotated[Path | None, typer.Option(
    '--base', '-b', dir_okay=False, exists=True,
    help='Existing machines JSON supplying init_item and the mounted sets '
         'when the export lacks them. Defaults to the output file if it exists.',
)]


def _hours(hhmm: str) -> float:
    h, m = str(hhmm).split(':')
    return int(h) + int(m) / 60


def _norm_id(machine_id: str) -> str:
    """`02` -> `O2` (a zero typed for the letter O), `N01` -> `N1`."""
    s = str(machine_id).strip().upper()
    if re.fullmatch(r'0\d+', s):
        s = 'O' + s[1:]
    m = re.fullmatch(r'([A-Z]+)0*(\d+)', s)
    return f'{m.group(1)}{int(m.group(2))}' if m else s


def _bar_shares(row: dict[str, str]) -> tuple[float, float]:
    """(bottom %, top %) of the weight: bars grouped by merge, the group
    holding bar 1 is the bottom set."""
    groups: dict[str, list[int]] = {}
    for i in (1, 2, 3, 4):
        ends = row.get(f'bar{i}_ends')
        if ends in (None, '', 'NULL') or float(ends) <= 0:
            continue
        groups.setdefault(row[f'b{i}_merge'], []).append(i)
    if len(groups) != 2:
        raise ValueError(f"variant {row['variant']!r} has {len(groups)} merges, need 2")
    btm = next(g for g in groups.values() if 1 in g)
    top = next(g for g in groups.values() if g is not btm)
    pct = lambda g: sum(float(row[f'bar{i}_pct']) for i in g)
    return pct(btm), pct(top)


def convert_runtime_export(
    export: list[dict[str, Any]], variants: dict[str, dict[str, str]],
    machine_master: dict[str, dict[str, Any]],
    base: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """The machines-file entries for a runtime export (see module doc).
    `base` is an existing machines list: it supplies `init_item` and the
    mounted sets for an export row that lacks them, and its machines that
    the export does not mention are passed through unchanged (in the base's
    order, after the exported ones)."""
    by_id = {_norm_id(b['id']): b for b in (base or [])}
    out = []
    seen: set[str] = set()
    for e in export:
        mid = _norm_id(e['id'])
        seen.add(mid)
        prior = by_id.get(mid, {})
        spec = machine_master.get(mid)
        if spec is None:
            raise KeyError(f'machine {mid!r} ({e["id"]!r}) is not in the machine master')
        item = e.get('item') if e.get('item') not in (None, '', 'NULL') else prior.get('init_item')
        if item is None:
            raise KeyError(f'machine {mid!r}: the export names no item and no base entry supplies one')
        row = variants.get(str(item))
        if row is None:
            raise KeyError(f"item {item!r} on {mid} is not in the variant table")
        wide = int(row['width']) >= 200
        rpm = spec['rpms'].get('wide', spec['rpms']['any']) if wide else spec['rpms']['any']
        racks_per_hour = rpm * 60 / REVS_PER_RACK
        lbs_per_rack = float(row['rack_wt']) / 100
        btm_pct, top_pct = _bar_shares(row)
        entry: dict[str, Any] = {
            'id': mid,
            'is_new': spec['rpms']['any'] >= NEW_MACHINE_RPM,
            'init_item': str(item),
            'init_top_lbs': round(_hours(e['top-rem']) * racks_per_hour * lbs_per_rack * top_pct / 100, 2),
            'init_btm_lbs': round(_hours(e['btm-rem']) * racks_per_hour * lbs_per_rack * btm_pct / 100, 2),
            'init_roll_lbs': round(float(e.get('racks-to-doff', 0) or 0) * lbs_per_rack, 2),
        }
        for key, src in (('init_top_set', 'top-set'), ('init_btm_set', 'btm-set')):
            if e.get(src) not in (None, '', 'NULL'):
                entry[key] = str(e[src])
            elif prior.get(key) not in (None, '', 'NULL'):
                entry[key] = prior[key]          # the base's object, verbatim
        out.append(entry)
    out.extend(b for mid, b in by_id.items() if mid not in seen)
    return out


def machines(runtime: _Runtime, input_dir: _InputDir, out: _Out = None,
             base: _Base = None) -> None:
    """Convert the plant's runtime export (remaining run time per bar, racks to
    doff, and — when present — the item and mounted set numbers) into a
    planner machines JSON, merging onto an existing machines file for the
    item and sets the export leaves out."""
    variants = {r['variant']: r for r in csv.DictReader(
        open(input_dir / 'greige-variants.tsv', encoding='utf-8-sig', newline=''),
        delimiter='\t')}
    master = json.load(open(input_dir / 'knit-machine-master.json'))
    export = json.load(open(runtime))
    if not isinstance(export, list):
        raise typer.BadParameter(f'{runtime}: the export must be a JSON list')
    path = out or input_dir / 'machines-new.json'
    base_path = base or (path if path.exists() else None)
    base_list = json.load(open(base_path)) if base_path else None
    try:
        entries = convert_runtime_export(export, variants, master, base_list)
    except (KeyError, ValueError) as e:
        raise typer.BadParameter(str(e)) from e
    exported = {_norm_id(e['id']) for e in export}
    with open(path, 'w') as fh:
        json.dump(entries, fh, indent=4)
        fh.write('\n')
    for m in entries:
        note = '' if m['id'] in exported else '  (not in export: unchanged)'
        typer.echo(f"  {m['id']:3} {m['init_item']:18} top {m['init_top_lbs']:8.1f} lbs  "
                   f"btm {m['init_btm_lbs']:8.1f} lbs  roll {m['init_roll_lbs']:6.1f} lbs{note}")
    if base_path:
        typer.echo(f'Merged onto {base_path}')
    typer.echo(f'Wrote {len(entries)} machine(s) to {path}')
