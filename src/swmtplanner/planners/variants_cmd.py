#!/usr/bin/env python

"""`plan variants` — build the planner's variant files from the plant's
greige-variant table.

Reads the master styles (`greige-styles.json`) and the variant table
(`greige-variants.tsv`), runs `products.variants.read_greige_variants`, and
writes next to them:

- `greige-variant-map.json` — per master, merge combination -> variant
  names (+ the merge-code table); read by the planner as `variant_map`;
- `greige-variant-masters.json` — variant name -> master; read by the
  planner as `variant_masters`;
- `greige-variants-report.txt` — the audit report (coverage, exclusions by
  reason, per-master beam-set combinations, split-lease check).

Re-run whenever the styles file or the variant table changes."""

from pathlib import Path
from typing import Annotated

import typer

from swmtplanner.products import (
    load_master_styles, read_greige_variants,
    write_variant_map, write_variant_masters,
)
from swmtplanner.products.variants import NOT_KNIT_IN_HOUSE, RL_TOLERANCE

__all__ = ['variants']

MAP_FILE = 'greige-variant-map.json'
MASTERS_FILE = 'greige-variant-masters.json'
REPORT_FILE = 'greige-variants-report.txt'

_InputDir = Annotated[Path, typer.Argument(
    exists=True, file_okay=False, dir_okay=True,
    help='Directory holding greige-styles.json and greige-variants.tsv; '
         'the outputs are written here unless --out-dir is given.',
)]
_Styles = Annotated[Path | None, typer.Option(
    '--styles', '-s', help='Override the master styles JSON path.',
)]
_Variants = Annotated[Path | None, typer.Option(
    '--variants', '-t', help='Override the variant table TSV path.',
)]
_OutDir = Annotated[Path | None, typer.Option(
    '--out-dir', '-o', file_okay=False, dir_okay=True,
    help='Where to write the two JSON files and the report.',
)]
_RlTol = Annotated[float, typer.Option(
    '--rl-tolerance',
    help='Summed bar-runlength distance beyond which a row is a sibling '
         'construction rather than a variant.',
)]
_Skip = Annotated[list[str] | None, typer.Option(
    '--skip-master',
    help='Master style not knit in-house (repeatable). Defaults to the '
         "module's NOT_KNIT_IN_HOUSE set.",
)]
_Quiet = Annotated[bool, typer.Option(
    '--quiet', '-q', help='Print only the coverage summary, not the report.',
)]


def variants(
    input_dir: _InputDir,
    styles: _Styles = None,
    variants: _Variants = None,
    out_dir: _OutDir = None,
    rl_tolerance: _RlTol = RL_TOLERANCE,
    skip_master: _Skip = None,
    quiet: _Quiet = False,
) -> None:
    """Build greige-variant-map.json / greige-variant-masters.json (and the
    audit report) from greige-styles.json + greige-variants.tsv."""
    styles_path = styles or input_dir / 'greige-styles.json'
    variants_path = variants or input_dir / 'greige-variants.tsv'
    out = out_dir or input_dir
    out.mkdir(parents=True, exist_ok=True)
    skip = set(skip_master) if skip_master else NOT_KNIT_IN_HOUSE

    typer.echo(f'Reading styles from {styles_path}')
    master_styles = load_master_styles(styles_path)
    typer.echo(f'Reading variants from {variants_path}')
    vm = read_greige_variants(
        variants_path, master_styles, skip_masters=skip, rl_tolerance=rl_tolerance,
    )

    write_variant_map(vm, out / MAP_FILE)
    write_variant_masters(vm, out / MASTERS_FILE)
    report = vm.report()
    (out / REPORT_FILE).write_text(report + '\n')

    n_recipes = sum(len(m['recipes']) for m in vm.master_map()['masters'].values())
    typer.echo(
        f'  {len(vm.variant_to_master)} variants mapped to '
        f'{len(set(vm.variant_to_master.values()))} masters '
        f'({n_recipes} recipes); {len(vm.excluded)} excluded'
    )
    if vm.masters_without_variants:
        typer.echo('  masters with no usable variants: '
                   + ', '.join(vm.masters_without_variants))
    typer.echo(f'Wrote {out / MAP_FILE}, {out / MASTERS_FILE}, {out / REPORT_FILE}')
    if not quiet:
        typer.echo('')
        typer.echo(report)
