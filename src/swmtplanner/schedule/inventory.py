#!/usr/bin/env python

"""The planner's beam-set stock: physical sets grouped by the description
they satisfy. See "Beam-set inventory" in `schedule/DESIGN.md`."""

from typing import Iterable, Mapping, Sequence, TYPE_CHECKING

from swmtplanner.schedule.activity import BEAM_FLOOR_LBS, MAX_BEAM_WASTE_LBS

if TYPE_CHECKING:
    from swmtplanner.products import BeamSet, BeamSetDesc

__all__ = ['Inventory', 'InventoryView', 'build_inventory', 'worth_stocking']

# The mutable stock the planner commits against …
Inventory = dict['BeamSetDesc', list['BeamSet']]
# … and the read-only view `plan_production` accepts.
InventoryView = Mapping['BeamSetDesc', Sequence['BeamSet']]


def worth_stocking(beam_set: 'BeamSet') -> bool:
    """Whether a set has enough usable yarn (`lbs - BEAM_FLOOR_LBS`) to be
    hung at all: below `MAX_BEAM_WASTE_LBS` the max-waste gate would swap it
    straight back out, so it is not usable stock."""
    return beam_set.lbs - BEAM_FLOOR_LBS >= MAX_BEAM_WASTE_LBS


def build_inventory(beam_sets: Iterable['BeamSet']) -> Inventory:
    """Group physical sets by `desc.physical` — the key a style's beam-set
    requirement is looked up under — dropping any set that is not
    `worth_stocking` and any set `assigned` to a machine (reserved: it is
    queued on that machine's bar, not free stock). The sets keep the
    `avail_date` they were loaded with (the planner start for stock on
    hand)."""
    out: Inventory = {}
    for bs in beam_sets:
        if bs.assigned or not worth_stocking(bs):
            continue
        out.setdefault(bs.desc.physical, []).append(bs)
    return out
