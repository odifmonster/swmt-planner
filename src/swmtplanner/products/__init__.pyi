from datetime import datetime
from pathlib import Path
from typing import Any, Collection, Iterable

from .beamset import BeamSetDesc, BeamSet
from .greige import BeamConfig, Greige
from .variants import (
    Merge, BeamSetSpec, Variant, VariantMap, normalize_merge,
    read_greige_variants, load_master_styles, load_master_list,
    write_variant_map, read_variant_map, VariantMapFile, MasterVariants, Recipe,
    write_variant_masters, read_variant_masters,
)

__all__ = [
    'BeamSetDesc', 'BeamSet', 'BeamConfig', 'Greige',
    'read_greige_styles', 'greige_styles_from_list',
    'read_beam_sets', 'beam_sets_from_list', 'beam_set_from_record',
    'normalize_blacklist', 'is_blacklisted',
    'Merge', 'BeamSetSpec', 'Variant', 'VariantMap', 'normalize_merge',
    'read_greige_variants', 'load_master_styles', 'load_master_list',
    'write_variant_map', 'read_variant_map', 'VariantMapFile', 'MasterVariants', 'Recipe',
    'write_variant_masters', 'read_variant_masters',
]


def read_greige_styles(path: str | Path) -> dict[str, Greige]: ...
def greige_styles_from_list(
    cfg: list[Any], source: str = ...,
) -> dict[str, Greige]: ...
def normalize_blacklist(codes: Iterable[Any]) -> frozenset[str]:
    """A blacklist of merge codes as compared against: trimmed, upper-cased,
    empties dropped."""
    ...
def is_blacklisted(merge: str | None, blacklist: Collection[str]) -> bool:
    """Whether `merge` is on a normalised blacklist; never for no merge."""
    ...
def read_beam_sets(
    path: str | Path, variant_map: VariantMapFile, avail_date: datetime,
    blacklist: Collection[str] = ...,
) -> dict[str, BeamSet]:
    """The plant's beam-set export as `{set_no: BeamSet}`. Each set carries
    its `vendor` and is available from its `received` timestamp;
    `avail_date` is the availability of a record without one. A set whose
    merge is on `blacklist` is stamped `blacklisted`."""
    ...
def beam_sets_from_list(
    cfg: list[Any], variant_map: VariantMapFile, avail_date: datetime,
    source: str = ..., blacklist: Collection[str] = ...,
) -> dict[str, BeamSet]: ...
def beam_set_from_record(
    entry: dict, variant_map: VariantMapFile, avail_date: datetime,
    source: str = ..., blacklist: Collection[str] = ...,
) -> BeamSet | None:
    """One export-shaped record as a `BeamSet` described by what the plant
    says is on it (the merge's yarn per the map, else normalised from denier
    / luster / type); `None` when the yarn normalises to nothing; stamped
    `blacklisted` when its merge is on `blacklist`."""
    ...