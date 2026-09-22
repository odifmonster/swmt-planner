#!/usr/bin/env python

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, TYPE_CHECKING

from swmtplanner.products import BeamSet, BeamSetDesc
from .machine import Machine, fresh_beam_lbs

if TYPE_CHECKING:
    from swmtplanner.products import Greige, VariantMapFile
    from swmtplanner.support import WorkCal

__all__ = ['read_machines', 'machines_from_list']


def machines_from_list(
    cfg: list[Any],
    *,
    start_date: datetime,
    workcal: 'WorkCal',
    greige_by_id: dict[str, 'Greige'],
    variant_masters: Mapping[str, str] | None = None,
    variant_map: 'VariantMapFile | None' = None,
    beam_sets: Mapping[str, BeamSet] | None = None,
    assigned_sets: 'list[Any] | None' = None,
    source: str = '<machines list>',
) -> dict[str, Machine]:
    """Build a `{machine_id: Machine}` dict from an already-parsed list
    of machine records — the same shape a machines JSON file holds.

    Each entry's `init_item` names what the machine is set up for. It is
    resolved to a `Greige` in three steps: a master id in `greige_by_id`
    is used as is; otherwise a variant name in `variant_masters` (the
    variant -> master translation, see `products.read_variant_masters`)
    is mapped to its master and kept as the machine's `init_variant`;
    anything else is an unrecognised item and resolves to the `NONE`
    greige. The initial top and bottom bars hold physical `BeamSet`s
    with ids `<machine id>-top` / `-btm`, described by the resolved
    `Greige`'s `configuration` (a machine currently set up to run an
    item is by definition threaded with that item's beams), holding
    `init_top_lbs` / `init_btm_lbs` and available from `start_date`.
    The optional `init_roll_lbs` (default 0) is how many lbs remain to
    complete the roll on the machine at `start_date`; the planner always
    finishes that roll first.
    An entry may name the sets actually mounted, `init_top_set` /
    `init_btm_set` (optional): an object `{set_no, merge, vendor}` — the
    plant's report of what is on the bar, `merge` / `vendor` possibly null
    — or, in the older form, the bare set-number string. The set number
    becomes the bar's set id. Its merge and vendor come from the object
    when given; else from the export's record of that set (`beam_sets`,
    matched by set number and, when both name one, vendor — see
    `BeamSet.same_vendor`), which also supplies the plant's denier /
    luster / yarn type; else the merge is known only when a variant was
    named *and* a `variant_map` is given: that variant's recipe supplies
    the merge on each bar. The `variant_map` is also handed to every
    `Machine` so its knits carry variants. Sets named here are on the
    machines, not in stock — the caller keeps them out of the inventory
    (see the planner's `load_inputs`).

    `assigned_sets` is the plant's assigned-sets list — records of
    `set_no`, `merge`, `vendor`, `machine`, `bar` (bar 1 the bottom, any
    higher bar the top) for sets staged at a machine but not yet threaded.
    Each becomes the next set in that machine bar's **queue**, resolved
    through `beam_sets` for its data (same match rule), or built from the
    record — the record's merge and vendor, a fresh-beam weight, available
    from `start_date` — when the export lacks it. Machine ids are matched
    after normalising zero padding (`N01` -> `N1`); records for machines
    not in this list are ignored (they still leave the free stock via the
    export's `assigned` flag). `start_date` (plant local time, like every
    timestamp the planner handles) and `workcal` are plant-wide, applied
    uniformly to every machine.
    (Changeover durations are no longer per-machine — they are
    module-level constants — so the file no longer carries
    `style_change_time` / `family_change_time`; any such fields are
    ignored.)"""
    if not isinstance(cfg, list):
        raise TypeError(f'{source} must be a list of machine objects')
    variant_masters = variant_masters or {}
    queues = _bar_queues(assigned_sets or [])
    out: dict[str, Machine] = {}
    for entry in cfg:
        if not isinstance(entry, dict):
            raise TypeError(
                f'each entry in {source} must be an object; got {entry!r}'
            )
        item_name = str(entry['init_item'])
        init_variant = None
        if item_name in greige_by_id:
            init_item = greige_by_id[item_name]
        elif variant_masters.get(item_name) in greige_by_id:
            init_item = greige_by_id[variant_masters[item_name]]
            init_variant = item_name
        else:
            # Unknown item — or a variant whose master (per a stale
            # translation file) is not in the styles: the machine is
            # planned as NONE.
            init_item = greige_by_id['NONE']
        item_cfg = init_item.configuration
        top_merge, btm_merge = _initial_merges(
            init_item.id, init_variant, variant_map,
        )
        start = start_date + workcal.cal_shift
        machine_id = str(entry['id'])
        top_lbs = float(entry['init_top_lbs'])
        btm_lbs = float(entry['init_btm_lbs'])
        top_set = _set_ref(entry.get('init_top_set'), f'{source} {machine_id} init_top_set')
        btm_set = _set_ref(entry.get('init_btm_set'), f'{source} {machine_id} init_btm_set')
        machine = Machine(
            id=machine_id,
            init_item=init_item,
            start=start,
            init_top_beam=_initial_set(machine_id, 'top', item_cfg.top_beam,
                                       top_lbs, start, top_merge, top_set,
                                       beam_sets),
            init_top_lbs=top_lbs,
            init_btm_beam=_initial_set(machine_id, 'btm', item_cfg.btm_beam,
                                       btm_lbs, start, btm_merge, btm_set,
                                       beam_sets),
            init_btm_lbs=btm_lbs,
            workcal=workcal,
            is_new=bool(entry['is_new']),
            init_variant=init_variant,
            variant_map=variant_map,
            init_roll_lbs_remaining=float(entry.get('init_roll_lbs', 0.0)),
            init_top_queue=_queued_sets(queues.get((_norm_id(machine_id), 'top'), ()),
                                        item_cfg.top_beam, start, beam_sets),
            init_btm_queue=_queued_sets(queues.get((_norm_id(machine_id), 'btm'), ()),
                                        item_cfg.btm_beam, start, beam_sets),
        )
        out[machine.id] = machine
    return out


def _norm_id(machine_id: str) -> str:
    """`N01` -> `N1`, `K08` -> `K8`, `K10` -> `K10`: the plant zero-pads."""
    m = re.fullmatch(r'([A-Za-z]+)0*(\d+)', str(machine_id).strip())
    return f'{m.group(1).upper()}{int(m.group(2))}' if m else str(machine_id).strip()


def _bar_queues(records: list[Any]) -> dict[tuple[str, str], list[dict]]:
    """Assigned-set records grouped by (normalised machine id, bar name), in
    file order. Bar 1 is the bottom; any higher bar is the top — on a style
    whose split pair sits on bars 1 and 2 the top set is reported as bar 3,
    on one whose split pair is on bars 2 and 3 as bar 2."""
    out: dict[tuple[str, str], list[dict]] = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        try:
            n = int(rec.get('bar', 0))
        except (TypeError, ValueError):
            continue
        if n < 1:
            continue
        bar = 'btm' if n == 1 else 'top'
        out.setdefault((_norm_id(rec['machine']), bar), []).append(rec)
    return out


def _queued_sets(
    records: list[dict], label: str, start: datetime,
    beam_sets: Mapping[str, BeamSet] | None,
) -> list[BeamSet]:
    """The `BeamSet`s for a bar's assigned records: the export's set when
    the record matches one (set number and vendor; flagged assigned), else
    one built from the record — the bar's requirement as its description,
    the record's merge and vendor, a fresh-beam weight — since the plant put
    it at the machine for exactly that bar."""
    out: list[BeamSet] = []
    for rec in records:
        set_no = str(rec['set_no'])
        vendor = _opt_str(rec.get('vendor'))
        known = _export_set(beam_sets, set_no, vendor)
        if known is not None:
            out.append(known)
            continue
        desc = BeamSetDesc(label).physical
        merge = _opt_str(rec.get('merge'))
        out.append(BeamSet(set_no, merge, fresh_beam_lbs(desc), desc, start,
                           vendor=vendor, known_merge=merge is not None,
                           assigned=True))
    return out


def _export_set(
    beam_sets: Mapping[str, BeamSet] | None, set_no: str | None,
    vendor: str | None,
) -> BeamSet | None:
    """The export's record of set `set_no`, if it has one that can be the
    set a record with `vendor` describes (`BeamSet.same_vendor`). Set
    numbers are the vendors' own numbering, so a vendor disagreement means
    the record is about a set the export does not hold."""
    if not beam_sets or not set_no:
        return None
    known = beam_sets.get(set_no)
    if known is None or not known.same_vendor(vendor):
        return None
    return known


def _set_ref(value: Any, where: str) -> tuple[str | None, str | None, str | None]:
    """A machines-file `init_*_set` as `(set_no, merge, vendor)`: an object
    `{set_no, merge, vendor}` (the latter two optional / null), a bare
    set-number string, or nothing at all -> `(None, None, None)`."""
    if isinstance(value, dict):
        set_no = _opt_str(value.get('set_no'))
        if set_no is None:
            raise ValueError(f'{where}: a mounted-set object needs a set_no')
        return set_no, _opt_str(value.get('merge')), _opt_str(value.get('vendor'))
    if value in (None, '', 'NULL'):
        return None, None, None
    if isinstance(value, (str, int)):
        return str(value), None, None
    raise TypeError(f'{where}: expected a set number or {{set_no, merge, vendor}}, got {value!r}')


def _initial_merges(
    master: str, variant: str | None, variant_map: 'VariantMapFile | None',
) -> tuple[str | None, str | None]:
    """The (top, btm) merges on a machine's initial bars: from the named
    variant's recipe under `master` when both are known, else `(None, None)`."""
    if variant is None or variant_map is None:
        return None, None
    mv = variant_map.masters.get(master)
    if mv is None:
        return None, None
    for recipe in mv.recipes:
        if variant in recipe.names.split(', '):
            return recipe.top.merge, recipe.btm.merge
    return None, None


def _opt_str(value: Any) -> str | None:
    return None if value in (None, '', 'NULL') else str(value)


def _initial_set(
    machine_id: str, bar: str, label: str, lbs: float, start: datetime,
    recipe_merge: str | None,
    ref: tuple[str | None, str | None, str | None],
    beam_sets: Mapping[str, BeamSet] | None,
) -> BeamSet:
    """The physical set on a machine's `bar` at `start`. `ref` is the
    machines file's `(set_no, merge, vendor)` (see `_set_ref`). The set's id
    is that set number when given, else `<machine>-<bar>`; its description
    is the physical form of the style's beam-set `label`; its merge and
    vendor come from `ref` when it names them, else from the export's
    record of the set (matched by set number and vendor), else — merge only
    — from `recipe_merge` (the named variant's recipe)."""
    set_no, merge, vendor = ref
    known = _export_set(beam_sets, set_no, vendor)
    if known is not None:
        merge = merge if merge is not None else known.merge
        vendor = vendor if vendor is not None else known.vendor
    if merge is None:
        merge = recipe_merge
    return BeamSet(set_no or f'{machine_id}-{bar}', merge, lbs,
                   BeamSetDesc(label).physical, start,
                   vendor=vendor,
                   denier=known.denier if known else None,
                   luster=known.luster if known else '',
                   ytype=known.ytype if known else '',
                   known_merge=merge is not None)


def read_machines(
    path: str | Path,
    *,
    start_date: datetime,
    workcal: 'WorkCal',
    greige_by_id: dict[str, 'Greige'],
    variant_masters: Mapping[str, str] | None = None,
    variant_map: 'VariantMapFile | None' = None,
    beam_sets: Mapping[str, BeamSet] | None = None,
    assigned_sets: 'list[Any] | None' = None,
) -> dict[str, Machine]:
    """Load machine records from a JSON file. Thin wrapper over
    `machines_from_list`. The file's shape: a top-level list of
    objects, one per machine — see `machines_from_list` for the
    per-entry fields and how `init_item` is resolved."""
    with open(path) as f:
        cfg = json.load(f)
    return machines_from_list(
        cfg,
        start_date=start_date, workcal=workcal,
        greige_by_id=greige_by_id, variant_masters=variant_masters,
        variant_map=variant_map, beam_sets=beam_sets,
        assigned_sets=assigned_sets,
        source=f'machines file at {path!r}',
    )
