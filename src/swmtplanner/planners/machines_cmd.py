#!/usr/bin/env python

"""`plan machines` — build a machines file from the plant's runtime export.

The export (one object per machine) says how far along each machine is, in
the floor's units. Its current form covers the whole knit floor:

```
{"id": "N1", "is_new": true,
 "init_top_lbs": {"unit": "time", "val": "36:38"},   # per bar: what is left on
 "init_btm_lbs": {"unit": "lbs",  "val": 1390.5},    # the set, tagged by unit
 "racks_on_roll": 507.4}                             # racks already wound on the
                                                      # roll in progress
```

A bar's quantity is either `time` — `HH:MM` of running time left on the set,
excluding stops (the new line reports this) — or `lbs`, the yarn left on the
set in pounds, already computed by the legacy line's beam tracking; `0` lbs
on a bar means it is empty, waiting for its next set. The older form is
still accepted: `top-rem` / `btm-rem` (`HH:MM`), `racks-to-doff` (racks
*left* on the roll) and optional `item`, `top-set` / `btm-set`.

Neither form names the item or the mounted sets, so an export is merged
onto a **base** machines file (`--base`, defaulting to the output file when
it already exists), which supplies `init_item` and the mounted
`init_top_set` / `init_btm_set` — kept verbatim, so the plant's `{set_no,
merge, vendor}` objects survive a refresh. The result is the
**intersection**: a machine must be in both the export and the base, and
machines found in only one are dropped and reported. The export covers the
whole floor; a machine whose item's bars do not group into exactly two
merges — a 2-bar style with the same merge on both bars, or a 3-merge
construction — cannot be one of ours (every automotive style is a
single-bar set plus a split-lease pair) and is skipped and reported instead
of written, as is one whose item the table does not have at all (a machine
down for `OVERHAUL`). A machine running a variant the mapping excluded is still
written and flagged: the planner loads it as `NONE`.

The planner wants pounds, so each is converted with the variant table
(`variants.tsv`), the knit-machine master and the greige styles:

- racks per hour = rpm × 60 / 480 revolutions per rack (the machine's rpm
  from the master — its `wide` rpm for a style 200" or wider);
- lbs per rack = the variant's `rack_wt` / 100;
- a `time` bar's lbs = hours remaining × racks/hour × lbs/rack × that bar's
  share of the weight, where the bars of the variant row are grouped by
  merge and the group holding **bar 1 is the bottom**; a `lbs` bar is taken
  as is;
- lbs left on the roll = the master style's `tgt_wt` − racks_on_roll ×
  lbs/rack (never below 0 — a roll past its target is about to be doffed
  and counts as between rolls; a master with no `tgt_wt` on file uses the
  plant default of 740), or racks-to-doff × lbs/rack in the old form.

Machine ids are normalised (`02` -> `O2`); `is_new` comes from the record
when it carries it, else from the machine master's speed (2200 rpm lines
are the new machines). See `planners/infinite/DESIGN.md`, "CLI entry
point"."""

import csv
import json
import re
from pathlib import Path
from typing import Annotated, Any, Mapping

import typer

__all__ = ['machines', 'convert_runtime_export']

REVS_PER_RACK = 480
NEW_MACHINE_RPM = 2200          # the new line runs at 2200; legacy at 900

_Runtime = Annotated[Path, typer.Argument(
    exists=True, dir_okay=False, help='The runtime export JSON (see module doc).',
)]
_InputDir = Annotated[Path, typer.Argument(
    exists=True, file_okay=False,
    help='Directory holding variants.tsv, knit-machine-master.json, '
         'greige-styles.json and greige-variant-masters.json.',
)]
_Out = Annotated[Path | None, typer.Option(
    '--out', '-o', dir_okay=False,
    help='Output machines JSON. Defaults to <input-dir>/machines-new.json.',
)]
_Base = Annotated[Path | None, typer.Option(
    '--base', '-b', dir_okay=False, exists=True,
    help='Existing machines JSON supplying init_item and the mounted sets. '
         'Defaults to the output file if it exists. Only machines in both '
         'the export and the base are written.',
)]

_NULL = (None, '', 'NULL', 'None')
VARIANTS_TSV = 'variants.tsv'
DEFAULT_TGT_WT = 740.0          # roll weight for a variant that maps to no master


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
        if ends in _NULL or float(ends) <= 0:
            continue
        merge = row.get(f'bar{i}_merge', row.get(f'b{i}_merge'))
        groups.setdefault(merge, []).append(i)
    if len(groups) != 2:
        raise ValueError(f"variant {row['variant']!r} has {len(groups)} merges, need 2")
    btm = next(g for g in groups.values() if 1 in g)
    top = next(g for g in groups.values() if g is not btm)
    pct = lambda g: sum(float(row[f'bar{i}_pct']) for i in g)
    return pct(btm), pct(top)


def _bar_lbs(e: dict[str, Any], mid: str, bar: str, share_pct: float,
             lbs_per_rack: float, rpm_of) -> float:
    """A bar's remaining lbs from the record: the tagged `init_<bar>_lbs`
    quantity (`lbs` as is; `time` converted), or the old `<bar>-rem` HH:MM."""
    tagged = e.get(f'init_{bar}_lbs')
    if isinstance(tagged, dict):
        unit, val = str(tagged.get('unit', '')).lower(), tagged.get('val')
        if unit == 'lbs':
            return float(val or 0)
        if unit == 'time':
            hours = _hours(val) if val not in _NULL else 0.0
        else:
            raise ValueError(f'machine {mid!r} {bar}: unknown unit {unit!r} (want lbs or time)')
    elif tagged is not None:
        return float(tagged)                    # a bare number: lbs
    else:
        rem = e.get(f'{bar}-rem')
        hours = _hours(rem) if rem not in _NULL else 0.0
    racks_per_hour = rpm_of() * 60 / REVS_PER_RACK
    return hours * racks_per_hour * lbs_per_rack * share_pct / 100


def convert_runtime_export(
    export: list[dict[str, Any]], variants: dict[str, dict[str, str]],
    machine_master: dict[str, dict[str, Any]],
    base: list[dict[str, Any]] | None = None,
    tgt_wts: Mapping[str, float] | None = None,
    skipped: list[tuple[str, str, str]] | None = None,
) -> list[dict[str, Any]]:
    """The machines-file entries for a runtime export (see module doc), in
    export order. `base` is an existing machines list supplying `init_item`
    and the mounted sets; only machines present in **both** lists are
    returned (an export row without a base entry has no item, a base entry
    without an export row has stale numbers). `tgt_wts` maps a variant name
    to its master style's target roll weight, needed to turn `racks_on_roll`
    (racks already wound) into lbs left on the roll. A machine whose item
    is not a two-set construction — its bars do not group into exactly two
    merges, e.g. a 2-bar style with the same merge on both bars, which is
    never one of ours — or whose item the variant table does not have at
    all (`OVERHAUL`, say) is left out and recorded in `skipped` as
    `(machine, item, why)`."""
    by_id = {_norm_id(b['id']): b for b in (base or [])}
    out = []
    for e in export:
        mid = _norm_id(e['id'])
        prior = by_id.get(mid)
        if prior is None:
            continue                                # export-only: dropped
        item = e.get('item') if e.get('item') not in _NULL else prior.get('init_item')
        if item is None:
            raise KeyError(f'machine {mid!r}: neither the export nor the base names its item')
        row = variants.get(str(item))
        if row is None:                             # no such variant: nothing to convert
            if skipped is not None:
                skipped.append((mid, str(item), 'not in the variant table'))
            continue
        spec = machine_master.get(mid)

        def rpm_of() -> float:
            if spec is None:
                raise KeyError(f'machine {mid!r} ({e["id"]!r}) is not in the machine master '
                               f'(needed to convert running time to lbs)')
            wide = int(row['width']) >= 200
            return spec['rpms'].get('wide', spec['rpms']['any']) if wide else spec['rpms']['any']

        lbs_per_rack = float(row['rack_wt']) / 100
        try:
            btm_pct, top_pct = _bar_shares(row)
        except ValueError as e:                     # not a two-set construction
            if skipped is not None:
                skipped.append((mid, str(item), str(e)))
            continue
        if 'is_new' in e:
            is_new = bool(e['is_new'])
        elif spec is not None:
            is_new = spec['rpms']['any'] >= NEW_MACHINE_RPM
        else:
            raise KeyError(f'machine {mid!r}: no is_new in the export and not in the machine master')

        # `init_roll_lbs` is the lbs already WOUND on the roll in progress
        # (the loader turns it into the lbs still to knit from the item's
        # target weight — see File I/O in schedule/DESIGN.md).
        if 'racks_on_roll' in e:                    # racks already wound
            roll_lbs = float(e['racks_on_roll'] or 0) * lbs_per_rack
        else:                                       # old form: racks left
            left = float(e.get('racks-to-doff', 0) or 0) * lbs_per_rack
            # A variant that maps to no master (the planner runs it as NONE)
            # has no roll weight of its own: use the plant default.
            tgt = (tgt_wts or {}).get(str(item), DEFAULT_TGT_WT)
            roll_lbs = max(tgt - left, 0.0) if left > 0 else 0.0

        entry: dict[str, Any] = {
            'id': mid,
            'is_new': is_new,
            'init_item': str(item),
            'init_top_lbs': round(_bar_lbs(e, mid, 'top', top_pct, lbs_per_rack, rpm_of), 2),
            'init_btm_lbs': round(_bar_lbs(e, mid, 'btm', btm_pct, lbs_per_rack, rpm_of), 2),
            'init_roll_lbs': round(roll_lbs, 2),
        }
        for key, src in (('init_top_set', 'top-set'), ('init_btm_set', 'btm-set')):
            if e.get(src) not in _NULL:
                entry[key] = str(e[src])
            elif prior.get(key) not in _NULL:
                entry[key] = prior[key]             # the base's object, verbatim
        out.append(entry)
    return out


def _target_weights(input_dir: Path, variants: Mapping[str, Any]) -> dict[str, float]:
    """variant name -> its master style's `tgt_wt`, via the variant -> master
    translation and the greige styles (both optional files: missing ones
    just leave the map empty)."""
    styles_p = input_dir / 'greige-styles.json'
    masters_p = input_dir / 'greige-variant-masters.json'
    if not styles_p.exists():
        return {}
    styles = {s['id']: float(s['tgt_wt']) for s in json.load(open(styles_p))}
    masters = json.load(open(masters_p)) if masters_p.exists() else {}
    out = {}
    for v in variants:
        master = masters.get(v, v)
        if master in styles:
            out[v] = styles[master]
    return out


def machines(runtime: _Runtime, input_dir: _InputDir, out: _Out = None,
             base: _Base = None) -> None:
    """Convert the plant's runtime export (what is left on each bar, as
    running time or lbs; racks wound on the roll) into a planner machines
    JSON, merged onto an existing machines file for the item and mounted
    sets; only machines in both files are written."""
    variants = {r['variant']: r for r in csv.DictReader(
        open(input_dir / VARIANTS_TSV, encoding='utf-8-sig', newline=''),
        delimiter='\t')}
    master = json.load(open(input_dir / 'knit-machine-master.json'))
    export = json.load(open(runtime))
    if not isinstance(export, list):
        raise typer.BadParameter(f'{runtime}: the export must be a JSON list')
    path = out or input_dir / 'machines-new.json'
    base_path = base or (path if path.exists() else None)
    base_list = json.load(open(base_path)) if base_path else None
    skipped: list[tuple[str, str, str]] = []
    tgt_known = _target_weights(input_dir, variants)
    try:
        entries = convert_runtime_export(
            export, variants, master, base_list, tgt_known, skipped=skipped,
        )
    except (KeyError, ValueError) as e:
        raise typer.BadParameter(str(e)) from e
    with open(path, 'w') as fh:
        json.dump(entries, fh, indent=4)
        fh.write('\n')
    for m in entries:
        note = '' if m['init_item'] in tgt_known else '  (no master: plans as NONE)'
        typer.echo(f"  {m['id']:3} {m['init_item']:18} top {m['init_top_lbs']:8.1f} lbs  "
                   f"btm {m['init_btm_lbs']:8.1f} lbs  roll {m['init_roll_lbs']:6.1f} lbs wound{note}")
    unknown = [(m, i) for m, i, why in skipped if why == 'not in the variant table']
    two_set = [(m, i) for m, i, why in skipped if why != 'not in the variant table']
    if two_set:
        typer.echo(f'  skipped {len(two_set)} machine(s) whose style is not a two-set '
                   'construction (non-automotive): '
                   + ', '.join(f'{m} ({i})' for m, i in two_set))
    if unknown:
        typer.echo(f'  skipped {len(unknown)} machine(s) whose item is not in the variant '
                   'table: ' + ', '.join(f'{m} ({i})' for m, i in unknown))
    exported = {_norm_id(e['id']) for e in export}
    based = {_norm_id(b['id']) for b in (base_list or [])}
    if base_path:
        typer.echo(f'Merged onto {base_path}')
        only_export = sorted(exported - based)
        only_base = sorted(based - exported)
        if only_export:
            typer.echo(f'  dropped (in export only, no item): {", ".join(only_export)}')
        if only_base:
            typer.echo(f'  dropped (in base only, no runtime data): {", ".join(only_base)}')
    typer.echo(f'Wrote {len(entries)} machine(s) to {path}')
