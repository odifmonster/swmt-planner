from pathlib import Path

from .beamset import BeamSet
from .greige import BeamConfig, Greige

__all__ = ['BeamSet', 'BeamConfig', 'Greige', 'read_greige_styles']


def read_greige_styles(path: str | Path) -> dict[str, Greige]: ...