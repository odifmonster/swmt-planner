from pathlib import Path
from typing import Any

from .beamset import BeamSet
from .greige import BeamConfig, Greige

__all__ = [
    'BeamSet', 'BeamConfig', 'Greige',
    'read_greige_styles', 'greige_styles_from_list',
]


def read_greige_styles(path: str | Path) -> dict[str, Greige]: ...
def greige_styles_from_list(
    cfg: list[Any], source: str = ...,
) -> dict[str, Greige]: ...