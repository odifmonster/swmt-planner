from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

__all__ = [
    'Merge', 'RawYarn', 'BeamSetSpec', 'Variant', 'VariantMap', 'normalize_merge',
    'denier_class', 'read_greige_variants', 'load_master_styles', 'load_master_list',
    'write_variant_map', 'read_variant_map', 'VariantMapFile', 'MasterVariants',
    'Recipe', 'BarRecipe', 'MergeInfo', 'MasterSpec', 'MasterSetSpec',
    'write_variant_masters', 'read_variant_masters', 'RL_TOLERANCE',
]

RL_TOLERANCE: float
"""Per-bar runner-length tolerance (2) for a row matching no master exactly."""


@dataclass(frozen=True)
class MasterSetSpec:
    """One of a master's two beam sets as its representative defines it."""
    beamset: str
    ends: int
    n_beams: int
    split: bool
    runlen: float
    pct: float
    denier: int
    textured: bool
    yarn_desc: str
    bars: tuple[int, ...]


@dataclass(frozen=True)
class MasterSpec:
    """A master style as its representative defines it: construction, weight
    split, stitch patterns (the family key), width and gauge."""
    id: str
    representative: str
    number: str
    width: int
    gauge: int
    stitches: tuple[str, ...]
    """Bar 1..4 stitch patterns in bar order."""
    pattern_key: tuple
    """The pattern family: the single-bar set's stitch and the split set's
    half-bar stitches in bar order, independent of which bar carries which
    set."""
    top: MasterSetSpec
    btm: MasterSetSpec
    @property
    def wide(self) -> bool:
        """Over 200 inches: wide machines only, at their wide rpm."""
        ...
    @property
    def heavy_on_top(self) -> bool:
        """The 75-denier set on the top bar: tall machines only."""
        ...


def denier_class(denier: Any) -> int: ...
def is_polyester(ytype: str) -> bool: ...
def is_textured(ytype: str) -> bool: ...
def is_recycled(ytype: str) -> bool: ...
def color_of(luster: str, black_from_type: bool = ...) -> str: ...


@dataclass(frozen=True)
class Merge:
    denier: int
    color: str
    finish: tuple[str, ...]
    textured: bool
    @property
    def recycled(self) -> bool: ...
    @property
    def yarn_desc(self) -> str: ...


def normalize_merge(denier: Any, luster: str, ytype: str) -> Merge | None: ...


@dataclass(frozen=True)
class RawYarn:
    merge: str | None
    vendor: str | None
    denier: str
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
    master_reps: dict[str, str]
    label_mismatches: dict[str, tuple[str, str]]
    masters_skipped: dict[str, str]
    """Masters whose representative the two-set model cannot define, and why."""
    master_specs: dict[str, MasterSpec]
    def rack_wt(self, master: str) -> float | None:
        """Average `rack_wt` over the master's usable variants."""
        ...
    def master_map(self) -> dict: ...
    def to_dict(self) -> dict: ...
    def report(self) -> str: ...


def load_master_styles(path: str | Path) -> list[dict]:
    """The greige-styles JSON records (label cross-check only)."""
    ...
def load_master_list(path: str | Path) -> list[dict]:
    """The master list: `[{"master": id, "variant": representative}, …]`."""
    ...
def read_greige_variants(
    tsv_path: str | Path, masters: Iterable[Mapping[str, Any]], *,
    styles: Iterable[Mapping[str, Any]] | None = ...,
    rl_tolerance: float = ...,
) -> VariantMap:
    """Each master is defined by its representative variant's row; a row
    sharing its style number is its variant when every bar matches on ends,
    split lease, beam count and yarn (denier class, colour, cationic /
    recycled finish, textured), and on runlength exactly or — failing an
    exact match — within `rl_tolerance`, the nearest such master winning (a
    tie is excluded as ambiguous)."""
    ...


def write_variant_map(vm: VariantMap, path: str | Path) -> None: ...
def write_variant_masters(vm: VariantMap, path: str | Path) -> None: ...
def read_variant_masters(path: str | Path) -> dict[str, str]: ...


@dataclass(frozen=True)
class MergeInfo:
    merge: str
    denier: str
    vendor: str | None
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
    representative: str | None = ...
    def lookup(self, top_merge: str, btm_merge: str) -> tuple[Recipe, ...]: ...


@dataclass(frozen=True)
class VariantMapFile:
    merges: dict[str, MergeInfo]
    masters: dict[str, MasterVariants]
    def beamset(self, merge: str, ends: int, n_beams: int, split: bool) -> str | None: ...


def read_variant_map(path: str | Path) -> VariantMapFile: ...
