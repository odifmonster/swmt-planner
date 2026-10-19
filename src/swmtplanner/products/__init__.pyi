from datetime import datetime
from pathlib import Path
from typing import Any, Collection, Iterable, Mapping

from .beamset import BeamSetDesc, BeamSet, LARGE_BEAM_DIAMETER, parse_size
from .greige import BeamConfig, Greige
from .variants import (
    Merge, BeamSetSpec, Variant, VariantMap, normalize_merge,
    read_greige_variants, load_master_styles, load_master_list,
    write_variant_map, read_variant_map, VariantMapFile, MasterVariants, Recipe,
    write_variant_masters, read_variant_masters,
)

__all__ = [
    'BeamSetDesc', 'BeamSet', 'LARGE_BEAM_DIAMETER', 'parse_size', 'BeamConfig', 'Greige',
    'read_greige_styles', 'greige_styles_from_list',
    'read_beam_sets', 'beam_sets_from_list', 'beam_set_from_record',
    'normalize_blacklist', 'is_blacklisted', 'Blacklist',
    'Merge', 'BeamSetSpec', 'Variant', 'VariantMap', 'normalize_merge',
    'read_greige_variants', 'load_master_styles', 'load_master_list',
    'write_variant_map', 'read_variant_map', 'VariantMapFile', 'MasterVariants', 'Recipe',
    'write_variant_masters', 'read_variant_masters',
]


def read_greige_styles(path: str | Path) -> dict[str, Greige]: ...
def greige_styles_from_list(
    cfg: list[Any], source: str = ...,
) -> dict[str, Greige]: ...
class Blacklist:
    """The run's blacklist: merge codes, vendor names and set numbers flagged
    for quality, each trimmed and upper-cased. A set is blacklisted when any
    of the three names it."""
    merges: frozenset[str]
    vendors: frozenset[str]
    sets: frozenset[str]
    def __init__(self, merges: frozenset[str] = ..., vendors: frozenset[str] = ...,
                 sets: frozenset[str] = ...) -> None: ...
    def __len__(self) -> int: ...
    def __bool__(self) -> bool: ...
    def covers(self, merge: str | None, vendor: str | None = ...,
               set_no: str | None = ...) -> bool: ...
def normalize_blacklist(data: Iterable[Any] | Mapping[str, Any]) -> Blacklist:
    """The `Blacklist` a file or config value describes: a list is merge
    codes; a mapping holds any of `merges`, `vendors`, `sets`. Entries are
    trimmed and upper-cased, empties dropped; `TypeError` for another shape."""
    ...
def is_blacklisted(merge: str | None, blacklist: Blacklist | Collection[str],
                   vendor: str | None = ..., set_no: str | None = ...) -> bool:
    """Whether a set with this merge (and vendor / set number, when given) is
    on the blacklist; a plain collection is merge codes alone."""
    ...
def read_beam_sets(
    path: str | Path, variant_map: VariantMapFile, avail_date: datetime,
    blacklist: Blacklist | Collection[str] = ...,
) -> dict[str, BeamSet]:
    """The plant's beam-set export as `{set_no: BeamSet}`. Each set carries
    its `vendor` and is available from its `received` timestamp;
    `avail_date` is the availability of a record without one. A set whose
    merge is on `blacklist` is stamped `blacklisted`."""
    ...
def beam_sets_from_list(
    cfg: list[Any], variant_map: VariantMapFile, avail_date: datetime,
    source: str = ..., blacklist: Blacklist | Collection[str] = ...,
) -> dict[str, BeamSet]: ...
def beam_set_from_record(
    entry: dict, variant_map: VariantMapFile, avail_date: datetime,
    source: str = ..., blacklist: Blacklist | Collection[str] = ...,
) -> BeamSet | None:
    """One export-shaped record as a `BeamSet` described by what the plant
    says is on it (the merge's yarn per the map, else normalised from denier
    / luster / type); `None` when the yarn normalises to nothing; stamped
    `blacklisted` when its merge is on `blacklist`."""
    ...