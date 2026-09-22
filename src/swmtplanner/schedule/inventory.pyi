from typing import Iterable, Mapping, Sequence

from swmtplanner.products import BeamSet, BeamSetDesc

__all__ = ['Inventory', 'InventoryView', 'build_inventory', 'worth_stocking']

Inventory = dict[BeamSetDesc, list[BeamSet]]
InventoryView = Mapping[BeamSetDesc, Sequence[BeamSet]]


def worth_stocking(beam_set: BeamSet) -> bool:
    """Whether a set has enough usable yarn (`lbs - BEAM_FLOOR_LBS >=
    MAX_BEAM_WASTE_LBS`) to be hung at all."""
    ...


def build_inventory(beam_sets: Iterable[BeamSet]) -> Inventory:
    """Group physical sets by `desc.physical`, dropping any that is not
    `worth_stocking` or is `assigned` to a machine."""
    ...
