from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

__all__ = [
    'Merge', 'RawYarn', 'BeamSetSpec', 'Variant', 'VariantMap', 'normalize_merge',
    'denier_class', 'read_greige_variants', 'load_master_styles',
    'write_variant_map', 'read_variant_map', 'VariantMapFile', 'MasterVariants',
    'Recipe', 'BarRecipe', 'MergeInfo',
    'write_variant_masters', 'read_variant_masters',
    'KNOWN_ENDS', 'OBSOLETE_ENDS', 'NOT_KNIT_IN_HOUSE', 'RL_TOLERANCE',
]

KNOWN_ENDS: frozenset[int]
OBSOLETE_ENDS: frozenset[int]
NOT_KNIT_IN_HOUSE: frozenset[str]
RL_TOLERANCE: float


def denier_class(denier: Any) -> int: ...
def is_polyester(ytype: str) -> bool: ...
def is_textured(ytype: str) -> bool: ...
def color_of(luster: str, black_from_type: bool = ...) -> str: ...


@dataclass(frozen=True)
class Merge:
    denier: int
    color: str
    finish: tuple[str, ...]
    textured: bool
    @property
    def yarn_desc(self) -> str: ...


def normalize_merge(denier: Any, luster: str, ytype: str) -> Merge | None: ...


@dataclass(frozen=True)
class RawYarn:
    merge: str | None
    denier: str
    flmnt: str
    luster: str
    ytype: str


@dataclass(frozen=True)
class BeamSetSpec:
    merge: Merge
    ends: int
    n_beams: int
    split: bool
    yarn: RawYarn | None = ...
    @property
    def desc(self) -> str: ...


@dataclass(frozen=True)
class Variant:
    name: str
    number: str
    master: str | None
    top: BeamSetSpec | None
    btm: BeamSetSpec | None
    rack_wt: float | None
    rl_distance: float | None
    split_bars: tuple[int, ...]
    split_is_top: bool | None
    issues: tuple[str, ...]
    @property
    def usable(self) -> bool: ...


@dataclass
class VariantMap:
    variants: dict[str, Variant]
    merges_to_beamsets: dict[Merge, frozenset[str]]
    combos_to_variants: dict[tuple[str, str], tuple[str, ...]]
    variant_to_master: dict[str, str]
    excluded: dict[str, tuple[str, ...]]
    masters_without_variants: tuple[str, ...]
    master_beamsets: dict[str, tuple[str, str]]
    def master_map(self) -> dict: ...
    def to_dict(self) -> dict: ...
    def report(self) -> str: ...


def load_master_styles(path: str | Path) -> list[dict]: ...
def read_greige_variants(
    tsv_path: str | Path, styles: Iterable[Mapping[str, Any]], *,
    skip_masters: Iterable[str] = ..., rl_tolerance: float = ...,
) -> VariantMap: ...


def write_variant_map(vm: VariantMap, path: str | Path) -> None: ...
def write_variant_masters(vm: VariantMap, path: str | Path) -> None: ...
def read_variant_masters(path: str | Path) -> dict[str, str]: ...


@dataclass(frozen=True)
class MergeInfo:
    merge: str
    denier: str
    flmnt: str
    luster: str
    ytype: str
    yarn_desc: str
    def beamset(self, ends: int, n_beams: int, split: bool) -> str: ...


@dataclass(frozen=True)
class BarRecipe:
    merge: str | None
    ends: int
    split: bool
    beamset: str


@dataclass(frozen=True)
class Recipe:
    master: str
    names: str
    n_beams: int
    top: BarRecipe
    btm: BarRecipe
    @property
    def key(self) -> tuple[str | None, str | None]: ...


@dataclass(frozen=True)
class MasterVariants:
    id: str
    top_beamset: str
    btm_beamset: str
    recipes: tuple[Recipe, ...]
    by_merges: dict[tuple[str | None, str | None], tuple[Recipe, ...]]
    def lookup(self, top_merge: str, btm_merge: str) -> tuple[Recipe, ...]: ...


@dataclass(frozen=True)
class VariantMapFile:
    merges: dict[str, MergeInfo]
    masters: dict[str, MasterVariants]
    def beamset(self, merge: str, ends: int, n_beams: int, split: bool) -> str | None: ...


def read_variant_map(path: str | Path) -> VariantMapFile: ...
