#!/usr/bin/env python

"""`plan variants` — build the planner's variant files from the plant's
variant table and the master list.

Reads the master list (`greige-master-styles.json`: each master style with
its representative variant) and the variant table (`variants.tsv`), runs
`products.variants.read_greige_variants`, and writes next to them:

- `greige-variant-map.json` — per master, merge combination -> variant
  names (+ the merge-code table); read by the planner as `variant_map`;
- `greige-variant-masters.json` — variant name -> master; read by the
  planner as `variant_masters`;
- `greige-variants-report.txt` — the audit report (coverage, exclusions by
  reason, per-master beam sets and combinations, nearest-master notes for
  the rows that matched nothing, split-lease check).

When `greige-styles.json` is present its beam-set labels are cross-checked
against the representatives' and any difference is reported. Re-run
whenever the master list or the variant table changes."""

from pathlib import Path
from typing import Annotated

import typer

from swmtplanner.products import (
    load_master_list, load_master_styles, read_greige_variants,
    write_variant_map, write_variant_masters,
)

__all__ = ['variants']

MASTER_LIST = 'greige-master-styles.json'
VARIANTS_TSV = 'variants.tsv'
STYLES_FILE = 'greige-styles.json'
MAP_FILE = 'greige-variant-map.json'
MASTERS_FILE = 'greige-variant-masters.json'
REPORT_FILE = 'greige-variants-report.txt'

_InputDir = Annotated[Path, typer.Argument(
    exists=True, file_okay=False, dir_okay=True,
    help=f'Directory holding {MASTER_LIST} and {VARIANTS_TSV} (and optionally '
         f'{STYLES_FILE} for a label cross-check); the outputs are written '
         'here unless --out-dir is given.',
)]
_Masters = Annotated[Path | None, typer.Option(
    '--masters', '-m', help='Override the master list JSON path.',
)]
_Variants = Annotated[Path | None, typer.Option(
    '--variants', '-t', help='Override the variant table TSV path.',
)]
_Styles = Annotated[Path | None, typer.Option(
    '--styles', '-s', help='Override the greige-styles JSON path (cross-check only).',
)]
_OutDir = Annotated[Path | None, typer.Option(
    '--out-dir', '-o', file_okay=False, dir_okay=True,
    help='Where to write the two JSON files and the report.',
)]
_Quiet = Annotated[bool, typer.Option(
    '--quiet', '-q', help='Print only the coverage summary, not the report.',
)]


def variants(
    input_dir: _InputDir,
    masters: _Masters = None,
    variants: _Variants = None,
    styles: _Styles = None,
    out_dir: _OutDir = None,
    quiet: _Quiet = False,
) -> None:
    """Build greige-variant-map.json / greige-variant-masters.json (and the
    audit report) from the master list + variants.tsv."""
    masters_path = masters or input_dir / MASTER_LIST
    variants_path = variants or input_dir / VARIANTS_TSV
    styles_path = styles or input_dir / STYLES_FILE
    out = out_dir or input_dir
    out.mkdir(parents=True, exist_ok=True)

    typer.echo(f'Reading master list from {masters_path}')
    master_list = load_master_list(masters_path)
    style_records = None
    if styles_path.exists():
        typer.echo(f'Cross-checking labels against {styles_path}')
        style_records = load_master_styles(styles_path)
    typer.echo(f'Reading variants from {variants_path}')
    try:
        vm = read_greige_variants(variants_path, master_list, styles=style_records)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e

    write_variant_map(vm, out / MAP_FILE)
    write_variant_masters(vm, out / MASTERS_FILE)
    report = vm.report()
    (out / REPORT_FILE).write_text(report + '\n')

    n_recipes = sum(len(m['recipes']) for m in vm.master_map()['masters'].values())
    typer.echo(
        f'  {len(vm.variant_to_master)} variants mapped to '
        f'{len(set(vm.variant_to_master.values()))} of {len(master_list)} masters '
        f'({n_recipes} recipes); {len(vm.excluded)} excluded'
    )
    if vm.masters_without_variants:
        typer.echo('  masters with no usable variants: '
                   + ', '.join(vm.masters_without_variants))
    for why in vm.masters_skipped.values():
        typer.echo(f'  master skipped: {why}')
    if vm.label_mismatches:
        typer.echo(f'  {len(vm.label_mismatches)} master(s) whose beam-set labels '
                   'differ from the styles file (see the report)')
    typer.echo(f'Wrote {out / MAP_FILE}, {out / MASTERS_FILE}, {out / REPORT_FILE}')
    if not quiet:
        typer.echo('')
        typer.echo(report)
