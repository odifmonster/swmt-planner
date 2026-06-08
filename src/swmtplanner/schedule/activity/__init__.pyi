from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from swmtplanner.support import HasID
from swmtplanner.products import Greige, BeamSet

__all__ = [
    'Activity', 'Knit', 'Waste', 'Doff', 'TapeOut', 'Hanging', 'Threading',
    'StyleChange', 'RunnerChange', 'PatternChange', 'Idle',
    'TAPE_OUT_SINGLE_DURATION', 'TAPE_OUT_BOTH_DURATION',
    'HANGING_SINGLE_DURATION', 'HANGING_BOTH_DURATION',
    'THREADING_SINGLE_DURATION', 'THREADING_BOTH_DURATION',
    'DOFF_DURATION',
    'STYLE_CHANGE_DURATION', 'RUNNER_CHANGE_DURATION', 'PATTERN_CHANGE_DURATION',
    'BEAM_FLOOR_LBS', 'MAX_BEAM_WASTE_LBS',
]


TAPE_OUT_SINGLE_DURATION: float
TAPE_OUT_BOTH_DURATION: float
HANGING_SINGLE_DURATION: float
HANGING_BOTH_DURATION: float
THREADING_SINGLE_DURATION: float
THREADING_BOTH_DURATION: float
DOFF_DURATION: float
STYLE_CHANGE_DURATION: float
RUNNER_CHANGE_DURATION: float
PATTERN_CHANGE_DURATION: float
BEAM_FLOOR_LBS: float
MAX_BEAM_WASTE_LBS: float


@dataclass(frozen=True)
class Activity(HasID[str]):
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Knit(Activity):
    item: Greige
    lbs: float


@dataclass(frozen=True)
class Waste(Activity):
    beam: BeamSet
    bar: Literal['top', 'btm']
    lbs: float


@dataclass(frozen=True)
class Doff(Activity):
    pass


@dataclass(frozen=True)
class TapeOut(Activity):
    bars: Literal['top', 'btm', 'both']
    top_beam: BeamSet | None = ...
    btm_beam: BeamSet | None = ...


@dataclass(frozen=True)
class Hanging(Activity):
    bars: Literal['top', 'btm', 'both']
    top_beam: BeamSet | None = ...
    top_lbs: float = ...
    btm_beam: BeamSet | None = ...
    btm_lbs: float = ...


@dataclass(frozen=True)
class Threading(Activity):
    bars: Literal['top', 'btm', 'both']


@dataclass(frozen=True)
class StyleChange(Activity):
    from_item: Greige
    to_item: Greige


@dataclass(frozen=True)
class RunnerChange(Activity):
    from_item: Greige
    to_item: Greige


@dataclass(frozen=True)
class PatternChange(Activity):
    from_item: Greige
    to_item: Greige


@dataclass(frozen=True)
class Idle(Activity):
    pass
