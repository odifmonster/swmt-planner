#!/usr/bin/env python

from dataclasses import dataclass

from ..beamset import BeamSetDesc
from .barconfig import BarConfig


@dataclass(frozen=True)
class BeamConfig:
    beamset: BeamSetDesc
    bars: tuple[BarConfig, ...]

    def can_use(self, bsets: list[BeamSetDesc]) -> bool:
        if len(bsets) == 1:
            return bsets[0] == self.beamset
        if len(bsets) == len(self.bars):
            try:
                merged = BeamSetDesc.merge(*bsets)
            except ValueError:
                return False
            return merged == self.beamset
        return False
