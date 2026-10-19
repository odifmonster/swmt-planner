#!/usr/bin/env python

"""`plan styles` — generate the planner's greige-styles file.

The master list (`greige-master-styles.json`) is the authoritative list of
master styles; each is defined by its representative variant's row in the
variant table (`variants.tsv`, see `products/variants.py`). From those and
the knit-machine master (`knit-machine-master.json`) this builds one
greige-styles record per master:

- `gauge`, `width` and the two `beam_cfg` bars (planner beam-set label,
  weight share `pct`, `runlen`) from the representative;
- `rack_wt`: the **average** rack weight over all the master's variants;
- `pattern`: the pattern family — masters whose **sets** knit the same
  stitches share a letter: the single-bar (75D) set's stitch and the split
  (40D) set's two half-bar stitches in bar order, regardless of which bar
  carries which set (a style that flips top and bottom is the same
  pattern). Letters are handed out `A`, `B`, …
  in the order the master list first shows each pattern (`Z` stays the
  `NONE` placeholder's);
- `machine_rates`: for every machine that can run the style — its gauge
  matches, the machine is at least as **wide** as the style (the master's
  `width`, inches, against the style's), and a style with the 75-denier
  set on the **top** bar needs a `tall` machine — the **nominal** rate
  `rpm × 60 / 480 revs per rack × rack_wt / 100` lbs per running hour at
  the machine's one `rpm`. No efficiency
  factor is baked in any more: the planner applies `RUNNING_EFFICIENCY`
  (`schedule.machine`) itself;
- `safety` (and `tgt_wt`, when given) come from the master list's own
  records — `{"master", "variant", "safety": <lbs>, "tgt_wt": <lbs>}` — the
  safety target being maintained there; a value the list does not carry is
  taken from the previous styles file by id, and failing that from the
  defaults (740 lbs per roll, safety two rolls), which is reported.

The `NONE` placeholder record is carried over from the previous file (or
synthesised: every machine at rate 100) and written first."""

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from swmtplanner.products import load_master_list, read_greige_variants
from swmtplanner.products.variants import MasterSpec

__all__ = ['styles', 'build_styles']

MASTER_LIST = 'greige-master-styles.json'
VARIANTS_TSV = 'variants.tsv'
MACHINE_MASTER = 'knit-machine-master.json'
STYLES_FILE = 'greige-styles.json'

REVS_PER_RACK = 480
DEFAULT_TGT_WT = 740.0
DEFAULT_SAFETY_ROLLS = 2
NONE_PATTERN = 'Z'

_InputDir = Annotated[Path, typer.Argument(
    exists=True, file_okay=False, dir_okay=True,
    help=f'Directory holding {MASTER_LIST}, {VARIANTS_TSV} and {MACHINE_MASTER}.',
)]
_Out = Annotated[Path | None, typer.Option(
    '--out', '-o', dir_okay=False,
    help=f'Output styles JSON. Defaults to <input-dir>/{STYLES_FILE}.',
)]
_Prior = Annotated[Path | None, typer.Option(
    '--prior', '-p', dir_okay=False, exists=True,
    help='Previous styles JSON supplying tgt_wt / safety (and the NONE record). '
         'Defaults to the output file if it exists.',
)]


def _letters():
    """`A`, `B`, … then `AA`, `AB`, … — skipping the NONE placeholder's."""
    n = 0
    while True:
        s, k = '', n
        while True:
            s = chr(ord('A') + k % 26) + s
            k = k // 26 - 1
            if k < 0:
                break
        n += 1
        if s != NONE_PATTERN:
            yield s


def _can_run(spec: MasterSpec, machine: dict[str, Any]) -> bool:
    """Gauge equal, the machine at least as wide as the style (the master's
    `width`, inches), and a `tall` machine for a style with the 75D set on
    top."""
    attrs = set(machine.get('attrs', ()))
    if int(machine['gauge']) != spec.gauge:
        return False
    if float(machine['width']) < float(spec.width):
        return False
    if spec.heavy_on_top and 'tall' not in attrs:
        return False
    return True


def _rpm(machine: dict[str, Any]) -> float:
    """The machine's one running speed (the master's `rpm`)."""
    return float(machine['rpm'])


def _weight(rec: dict[str, Any], key: str) -> float | None:
    """A `tgt_wt` / `safety` value from a record, None when absent or null."""
    v = rec.get(key)
    return None if v in (None, '', 'NULL') else float(v)


def _none_record(prior: dict[str, dict] | None, machine_master: dict[str, Any]) -> dict:
    if prior and 'NONE' in prior:
        return prior['NONE']
    return {
        'id': 'NONE', 'gauge': 1, 'width': 1, 'rack_wt': 1000.0, 'tgt_wt': 1,
        'safety': 0, 'pattern': NONE_PATTERN,
        'beam_cfg': {'top': {'runlen': '50.00', 'beamset': '40D WHT 1X1 S/L', 'pct': 50},
                     'btm': {'runlen': '100.00', 'beamset': '75D WHT TX 1X1', 'pct': 50}},
        'machine_rates': [{'id': m, 'rate': 100.0} for m in machine_master],
    }


def build_styles(
    master_list: list[dict], vm, machine_master: dict[str, Any],
    prior: list[dict] | None = None,
) -> tuple[list[dict], list[str]]:
    """The greige-styles records (NONE first, then the masters in list order)
    and a list of notes (masters skipped, defaults applied)."""
    prior_by_id = {s['id']: s for s in (prior or [])}
    notes: list[str] = []
    letters = _letters()
    pattern_of: dict[tuple[str, ...], str] = {}
    out = [_none_record(prior_by_id, machine_master)]
    for rec in master_list:
        mid = str(rec['master'])
        spec = vm.master_specs.get(mid)
        if spec is None:
            notes.append(f'{mid}: skipped — {vm.masters_skipped.get(mid, "not defined")}')
            continue
        rack_wt = vm.rack_wt(mid)
        if rack_wt is None:
            notes.append(f'{mid}: skipped — no variant carries a rack weight')
            continue
        if spec.pattern_key not in pattern_of:
            pattern_of[spec.pattern_key] = next(letters)
        # Target and safety weights: the master list's own values first, then
        # the previous styles file, then the defaults.
        old = prior_by_id.get(mid) or {}
        tgt_wt = _weight(rec, 'tgt_wt') or _weight(old, 'tgt_wt')
        safety = _weight(rec, 'safety')
        if safety is None:
            safety = _weight(old, 'safety')
        missing = []
        if tgt_wt is None:
            tgt_wt = DEFAULT_TGT_WT
            missing.append(f'tgt_wt {tgt_wt:g}')
        if safety is None:
            safety = DEFAULT_TGT_WT * DEFAULT_SAFETY_ROLLS
            missing.append(f'safety {safety:g}')
        if missing:
            notes.append(f'{mid}: {", ".join(missing)} (defaults — not in the master '
                         'list or the previous styles file)')
        rates = []
        for m_id, machine in machine_master.items():
            if not _can_run(spec, machine):
                continue
            rate = _rpm(machine) * 60 / REVS_PER_RACK * rack_wt / 100
            rates.append({'id': m_id, 'rate': round(rate, 4)})
        if not rates:
            notes.append(f'{mid}: no machine can run it (gauge {spec.gauge}, '
                         f'{spec.width:g}" wide, '
                         f'{"75D on top" if spec.heavy_on_top else "75D on bottom"})')
        bar = lambda s: {'runlen': f'{s.runlen:.2f}', 'beamset': s.beamset,
                         'pct': round(s.pct, 2)}
        out.append({
            'id': mid, 'gauge': spec.gauge, 'width': spec.width,
            'rack_wt': round(rack_wt, 2), 'tgt_wt': tgt_wt, 'safety': safety,
            'pattern': pattern_of[spec.pattern_key],
            'beam_cfg': {'top': bar(spec.top), 'btm': bar(spec.btm)},
            'machine_rates': rates,
        })
    return out, notes


def styles(input_dir: _InputDir, out: _Out = None, prior: _Prior = None) -> None:
    """Generate greige-styles.json from the master list, variants.tsv and
    knit-machine-master.json (safety from the master list; tgt_wt from the
    list when given, else the previous file)."""
    path = out or input_dir / STYLES_FILE
    prior_path = prior or (path if path.exists() else None)
    prior_list = json.load(open(prior_path)) if prior_path else None
    master_list = load_master_list(input_dir / MASTER_LIST)
    machine_master = json.load(open(input_dir / MACHINE_MASTER))
    typer.echo(f'Reading variants from {input_dir / VARIANTS_TSV}')
    try:
        vm = read_greige_variants(input_dir / VARIANTS_TSV, master_list)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e
    records, notes = build_styles(master_list, vm, machine_master, prior_list)
    with open(path, 'w') as fh:
        json.dump(records, fh, indent=4)
        fh.write('\n')
    for r in records[1:]:
        n_var = sum(1 for v in vm.variants.values() if v.usable and v.master == r['id'])
        typer.echo(f"  {r['id']:11} pattern {r['pattern']:2} rack_wt {r['rack_wt']:6.2f} "
                   f"({n_var:3} variants)  {r['width']:3}\"  {len(r['machine_rates']):2} machine(s)  "
                   f"tgt {r['tgt_wt']:g} safety {r['safety']:g}")
    for n in notes:
        typer.echo(f'  note: {n}')
    if prior_path:
        typer.echo(f'values the master list lacks carried over from {prior_path}')
    typer.echo(f'Wrote {len(records) - 1} master(s) + NONE to {path}')
