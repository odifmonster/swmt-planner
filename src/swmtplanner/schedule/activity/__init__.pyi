from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from swmtplanner.support import HasID
from swmtplanner.products import Greige, BeamSet

__all__ = [
    'Activity', 'Job', 'Waste', 'TapeOut', 'BeamLoad', 'StyleChange', 'Idle',
    'TAPE_OUT_SINGLE_DURATION', 'TAPE_OUT_BOTH_DURATION', 'BEAM_LOAD_DURATION',
]


TAPE_OUT_SINGLE_DURATION: timedelta
TAPE_OUT_BOTH_DURATION: timedelta
BEAM_LOAD_DURATION: timedelta


@dataclass(frozen=True)
class Activity(HasID[str]):
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Job(Activity):
    item: Greige
    lbs: float
    rolls: tuple[tuple[float, datetime], ...] = ...


@dataclass(frozen=True)
class Waste(Activity):
    item: Greige
    lbs: float


@dataclass(frozen=True)
class TapeOut(Activity):
    bars: Literal['top', 'btm', 'both']


@dataclass(frozen=True)
class BeamLoad(Activity):
    bar: Literal['top', 'btm']
    beam: BeamSet
    lbs: float


@dataclass(frozen=True)
class StyleChange(Activity):
    from_item: Greige
    to_item: Greige
    is_family_change: bool


@dataclass(frozen=True)
class Idle(Activity):
    pass
