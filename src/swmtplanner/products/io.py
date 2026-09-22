#!/usr/bin/env python

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .beamset import BeamSet, BeamSetDesc
from .greige import Greige
from .variants import VariantMapFile, normalize_merge

__all__ = [
    'read_greige_styles', 'greige_styles_from_list',
    'read_beam_sets', 'beam_sets_from_list',
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


def beam_sets_from_list(
    cfg: list[Any], variant_map: VariantMapFile, avail_date: datetime,
    source: str = '<beam-sets list>',
) -> dict[str, BeamSet]:
    """Build a `{set_no: BeamSet}` dict from an already-parsed list of
    inventory records — the same shape a beam-sets JSON file holds.

    Per-entry fields: `set_no`, `merge`, `vendor` (the yarn's supplier;
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
    start)."""
    if not isinstance(cfg, list):
        raise TypeError(f'{source} must be a list of beam-set objects')
    out: dict[str, BeamSet] = {}
    for entry in cfg:
        if not isinstance(entry, dict):
            raise TypeError(
                f'each entry in {source} must be an object; got {entry!r}'
            )
        merge = str(entry['merge'])
        info = variant_map.merges.get(merge)
        if info is not None:
            yarn = info.yarn_desc
        else:
            norm = normalize_merge(entry['denier'], entry['luster'], entry['desc'])
            if norm is None:
                continue
            yarn = norm.yarn_desc
        desc = BeamSetDesc(f"{yarn} {int(entry['ends'])}X{int(entry['beams'])}")
        bs = BeamSet(
            str(entry['set_no']), merge, float(entry['lbs']), desc,
            _received(entry.get('received'), avail_date, source),
            vendor=_opt_str(entry.get('vendor')),
            denier=int(entry['denier']), luster=str(entry['luster']),
            ytype=str(entry['desc']), known_merge=info is not None,
            assigned=bool(entry.get('assigned', False)),
        )
        out[bs.set_no] = bs
    return out


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
) -> dict[str, BeamSet]:
    """Load the beam-set inventory from a JSON file. Thin wrapper over
    `beam_sets_from_list`. The file's shape: a top-level list of objects, one
    per physical beam set — see `beam_sets_from_list` for the fields;
    `avail_date` is the availability of a record without `received`."""
    with open(path) as f:
        cfg = json.load(f)
    return beam_sets_from_list(
        cfg, variant_map, avail_date, source=f'beam-sets file at {path!r}',
    )
