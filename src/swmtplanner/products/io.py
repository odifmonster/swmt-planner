#!/usr/bin/env python

import json
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Collection, Iterable, Mapping

from swmtplanner.support import planning_mode

from .beamset import BeamSet, BeamSetDesc, parse_size
from .greige import Greige
from .variants import VariantMapFile, normalize_merge

__all__ = [
    'read_greige_styles', 'greige_styles_from_list',
    'read_beam_sets', 'beam_sets_from_list', 'beam_set_from_record',
]


def greige_styles_from_list(
    cfg: list[Any], source: str = '<greige-styles list>',
) -> dict[str, Greige]:
    """Build a `{greige_id: Greige}` dict from an already-parsed list of
    greige-style records — the same shape a greige-styles JSON file holds.

    Per-entry fields used:
      - `id`; `pattern` (the greige's **family**); `tgt_wt`; `safety`;
      - `beam_cfg` — `{'top': {...}, 'btm': {...}}`, each bar an object carrying
        a `beamset` (the beam name) and an integer `pct` (percent of the rack on
        that bar). `pct` is converted to the 0–1 fraction `Greige` expects
        (top/btm `pct` sum to 100, so the fractions sum to 1);
      - `machine_rates` — a list of `{'id', 'rate'}` objects, converted to the
        `{machine_id: rate}` dict `Greige` expects.
    Other descriptive fields (`gauge`, `width`, `rack_wt`, per-bar `runlen`) are
    not part of the planning model and are ignored. `source` is included in
    error messages so callers (e.g. a higher-level config loader) can point at
    the file or section."""
    if not isinstance(cfg, list):
        raise TypeError(f'{source} must be a list of greige objects')
    out: dict[str, Greige] = {}
    for entry in cfg:
        if not isinstance(entry, dict):
            raise TypeError(
                f'each entry in {source} must be an object; got {entry!r}'
            )
        top = entry['beam_cfg']['top']
        btm = entry['beam_cfg']['btm']
        machines = {
            m['id']: float(m['rate']) for m in entry['machine_rates']
        }
        greige = Greige(
            id=entry['id'],
            family=entry['pattern'],
            tgt_wt=float(entry['tgt_wt']),
            top_beam=top['beamset'],
            top_pct=float(top['pct']) / 100.0,
            btm_beam=btm['beamset'],
            btm_pct=float(btm['pct']) / 100.0,
            safety=float(entry['safety']),
            machines=machines,
        )
        out[greige.id] = greige
    return out


def read_greige_styles(path: str | Path) -> dict[str, Greige]:
    """Load greige-style records from a JSON file. Thin wrapper over
    `greige_styles_from_list`. The file's shape: a top-level list of objects,
    one per greige — see `greige_styles_from_list` for the per-entry fields
    (`id` / `pattern` / `tgt_wt` / `safety`, the nested `beam_cfg`, and
    `machine_rates`)."""
    with open(path) as f:
        cfg = json.load(f)
    return greige_styles_from_list(
        cfg, source=f'greige-styles file at {path!r}',
    )


@dataclass(frozen=True)
class Blacklist:
    """The run's blacklist (see "Blacklisted merges" in schedule/DESIGN.md):
    the merge codes, vendor names and set numbers flagged for quality, each
    normalised for comparison (`_key`: trimmed, upper-cased). A set is
    blacklisted when any of the three names it."""
    merges: frozenset[str] = frozenset()
    vendors: frozenset[str] = frozenset()
    sets: frozenset[str] = frozenset()

    def __len__(self) -> int:
        return len(self.merges) + len(self.vendors) + len(self.sets)

    def __bool__(self) -> bool:
        return len(self) > 0

    def covers(self, merge: str | None, vendor: str | None = None,
               set_no: str | None = None) -> bool:
        """Whether a set with this merge, vendor and set number is
        blacklisted; a missing value matches nothing."""
        return ((merge is not None and _key(merge) in self.merges)
                or (vendor is not None and _key(vendor) in self.vendors)
                or (set_no is not None and _key(set_no) in self.sets))


def _key(value: Any) -> str:
    return str(value).strip().upper()


def _keys(values: Iterable[Any] | None) -> frozenset[str]:
    return frozenset(k for k in (_key(v) for v in (values or ())) if k)


def normalize_blacklist(data: Iterable[Any] | Mapping[str, Any]) -> Blacklist:
    """The `Blacklist` a blacklist file or config value describes: a plain
    list is merge codes; a mapping holds any of `merges`, `vendors` and
    `sets` (lists). Every entry becomes a trimmed, upper-cased string;
    empty entries are dropped. Raises `TypeError` for any other shape or
    an unknown key."""
    if isinstance(data, Mapping):
        unknown = set(data) - {'merges', 'vendors', 'sets'}
        if unknown:
            raise TypeError(f'blacklist: unknown key(s) {sorted(unknown)}; '
                            f"expected 'merges', 'vendors', 'sets'")
        for k, v in data.items():
            if isinstance(v, (str, bytes)) or not isinstance(v, Iterable):
                raise TypeError(f'blacklist: {k!r} must be a list')
        return Blacklist(_keys(data.get('merges')), _keys(data.get('vendors')),
                         _keys(data.get('sets')))
    if isinstance(data, (str, bytes)) or not isinstance(data, Iterable):
        raise TypeError('blacklist must be a list of merge codes or an object '
                        "with 'merges', 'vendors' and/or 'sets'")
    return Blacklist(merges=_keys(data))


def is_blacklisted(merge: str | None, blacklist: 'Blacklist | Collection[str]',
                   vendor: str | None = None, set_no: str | None = None) -> bool:
    """Whether a set with this `merge` (and, when given, `vendor` and
    `set_no`) is on the blacklist (compared trimmed and case-insensitively).
    A plain collection of codes is taken as merge codes alone."""
    if not blacklist:
        return False
    if isinstance(blacklist, Blacklist):
        return blacklist.covers(merge, vendor, set_no)
    return merge is not None and _key(merge) in blacklist


def beam_sets_from_list(
    cfg: list[Any], variant_map: VariantMapFile, avail_date: datetime,
    source: str = '<beam-sets list>', blacklist: 'Blacklist | Collection[str]' = (),
) -> dict[str, BeamSet]:
    """Build a `{set_no: BeamSet}` dict from an already-parsed list of
    inventory records — the same shape a beam-sets JSON file holds.

    Per-entry fields: `set_no`, `merge`, `size` (the beams' `<diam> x
    <width>` in inches; optional), `vendor` (the yarn's supplier;
    optional), `received` (when the plant received the set,
    `YYYY-MM-DD HH:MM:SS[.fff]`; optional), `lbs`, `beams`, `ends`, `denier`,
    `luster`, `desc` (the plant's yarn type, e.g. `TEXT POLY`), and the
    optional `assigned` flag (default false) — a set reserved for a machine's
    bar, kept out of free stock and queued on that bar instead (see the
    machines loader's `assigned_sets`).

    Each set is labelled in the planner's vocabulary, `{yarn} {ends}X{beams}`
    with no `S/L`: when `variant_map` knows the merge, the yarn is the one the
    map recorded for it and the set is `known_merge`; otherwise the yarn is
    normalised from the record's denier / luster / type (see
    `variants.normalize_merge`). Non-polyester sets — anything the plant's
    styles can't use — are dropped. A set is available from its `received`
    timestamp (taken literally): a set received before the planner's start is
    on hand, one received after it enters stock when it arrived. A record
    with no `received` is available from `avail_date` (the planner's
    start). In planning mode (`support.planning_mode`) every set's lbs is
    replaced by `planning_mode.BEAM_LBS`. A set whose merge is on
    `blacklist` (from `normalize_blacklist`) is stamped `blacklisted`."""
    if not isinstance(cfg, list):
        raise TypeError(f'{source} must be a list of beam-set objects')
    out: dict[str, BeamSet] = {}
    for entry in cfg:
        if not isinstance(entry, dict):
            raise TypeError(
                f'each entry in {source} must be an object; got {entry!r}'
            )
        bs = beam_set_from_record(entry, variant_map, avail_date, source, blacklist)
        if bs is not None:
            out[bs.set_no] = bs
    return out


def beam_set_from_record(
    entry: dict, variant_map: VariantMapFile, avail_date: datetime,
    source: str = '<beam-set record>', blacklist: 'Blacklist | Collection[str]' = (),
) -> BeamSet | None:
    """One export-shaped record (`set_no`, `merge`, `vendor`, `received`,
    `lbs`, `beams`, `ends`, `denier`, `luster`, `desc`, `assigned`) as a
    `BeamSet` described by what the plant says is on it — the rule
    `beam_sets_from_list` applies to every entry, shared with the machines
    loader for assigned-set records the export lacks. `None` for a set no
    style of ours can use (its yarn normalises to nothing). Stamped
    `blacklisted` when its merge, vendor or set number is on `blacklist`."""
    merge = str(entry['merge'])
    info = variant_map.merges.get(merge)
    if info is not None:
        yarn = info.yarn_desc
    else:
        norm = normalize_merge(entry['denier'], entry['luster'], entry['desc'])
        if norm is None:
            return None
        yarn = norm.yarn_desc
    desc = BeamSetDesc(f"{yarn} {int(entry['ends'])}X{int(entry['beams'])}")
    return BeamSet(
        str(entry['set_no']), merge, planning_mode.beam_lbs(float(entry['lbs'])), desc,
        _received(entry.get('received'), avail_date, source),
        vendor=_opt_str(entry.get('vendor')),
        denier=int(entry['denier']), luster=str(entry['luster']),
        ytype=str(entry['desc']), known_merge=info is not None,
        assigned=bool(entry.get('assigned', False)),
        blacklisted=is_blacklisted(merge, blacklist, vendor=_opt_str(entry.get('vendor')),
                                   set_no=str(entry['set_no'])),
        size=parse_size(entry.get('size')),
    )


def _opt_str(value: Any) -> str | None:
    return None if value in (None, '', 'NULL') else str(value)


def _received(value: Any, default: datetime, source: str) -> datetime:
    """A record's `received` timestamp as a datetime, `default` when absent."""
    if value in (None, '', 'NULL'):
        return default
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value)).replace(tzinfo=None)
    except ValueError as e:
        raise ValueError(f'{source}: bad received timestamp {value!r}') from e


def read_beam_sets(
    path: str | Path, variant_map: VariantMapFile, avail_date: datetime,
    blacklist: 'Blacklist | Collection[str]' = (),
) -> dict[str, BeamSet]:
    """Load the beam-set inventory from a JSON file. Thin wrapper over
    `beam_sets_from_list`. The file's shape: a top-level list of objects, one
    per physical beam set — see `beam_sets_from_list` for the fields;
    `avail_date` is the availability of a record without `received`."""
    with open(path) as f:
        cfg = json.load(f)
    return beam_sets_from_list(
        cfg, variant_map, avail_date, source=f'beam-sets file at {path!r}',
        blacklist=blacklist,
    )
