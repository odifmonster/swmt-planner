from datetime import datetime
from pathlib import Path
from typing import Any

from .beamset import BeamSetDesc, BeamSet
from .greige import BeamConfig, Greige
from .variants import (
    Merge, BeamSetSpec, Variant, VariantMap, normalize_merge,
    read_greige_variants, load_master_styles,
    write_variant_map, read_variant_map, VariantMapFile, MasterVariants, Recipe,
    write_variant_masters, read_variant_masters,
)

__all__ = [
    'BeamSetDesc', 'BeamSet', 'BeamConfig', 'Greige',
    'read_greige_styles', 'greige_styles_from_list',
    'read_beam_sets', 'beam_sets_from_list',
    'Merge', 'BeamSetSpec', 'Variant', 'VariantMap', 'normalize_merge',
    'read_greige_variants', 'load_master_styles',
    'write_variant_map', 'read_variant_map', 'VariantMapFile', 'MasterVariants', 'Recipe',
    'write_variant_masters', 'read_variant_masters',
]


def read_greige_styles(path: str | Path) -> dict[str, Greige]: ...
def greige_styles_from_list(
    cfg: list[Any], source: str = ...,
) -> dict[str, Greige]: ...
def read_beam_sets(
    path: str | Path, variant_map: VariantMapFile, avail_date: datetime,
) -> dict[str, BeamSet]:
    """The plant's beam-set export as `{set_no: BeamSet}`. Each set carries
    its `vendor` and is available from its `received` timestamp;
    `avail_date` is the availability of a record without one."""
    ...
def beam_sets_from_list(
    cfg: list[Any], variant_map: VariantMapFile, avail_date: datetime,
    source: str = ...,
) -> dict[str, BeamSet]: ...