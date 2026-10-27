from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Literal

from swmtplanner.support import HasID
from swmtplanner.products import Greige, BeamSet

__all__ = [
    'Activity', 'Knit', 'Waste', 'Doff', 'TapeOut', 'Unhang', 'Hanging', 'Threading',
    'StyleChange', 'RunnerChange', 'PatternChange', 'Idle',
    'TAPE_OUT_SINGLE_DURATION', 'TAPE_OUT_BOTH_DURATION',
    'HANGING_SINGLE_DURATION', 'HANGING_BOTH_DURATION',
    'THREADING_SINGLE_DURATION', 'THREADING_BOTH_DURATION',
    'DOFF_DURATION',
    'STYLE_CHANGE_DURATION', 'RUNNER_CHANGE_DURATION', 'PATTERN_CHANGE_DURATION',
    'BEAM_FLOOR_LBS', 'MAX_BEAM_WASTE_LBS', 'rebind_sets',
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
    variant: str | None = ...
    """The plant variant the two bars' merges identify under `item` (the
    recipe's comma-separated names), or None when unknown."""
    top_beam: BeamSet | None = ...
    """The set on each bar while this knit ran; None when the bar held nothing."""
    btm_beam: BeamSet | None = ...


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
    """The set removed from top, as returned to inventory (remaining lbs,
    avail_date = this activity's end); None if top untouched."""
    btm_beam: BeamSet | None = ...


@dataclass(frozen=True)
class Unhang(Activity):
    """A hung, never-threaded set taken off again: zero duration, no ration
    unit, no job; the set(s) removed return to inventory with their lbs."""
    bars: Literal['top', 'btm', 'both']
    top_beam: BeamSet | None = ...
    btm_beam: BeamSet | None = ...


@dataclass(frozen=True)
class Hanging(Activity):
    bars: Literal['top', 'btm', 'both']
    top_beam: BeamSet | None = ...
    """The set now on top — its `lbs` is what the bar holds; None if untouched."""
    btm_beam: BeamSet | None = ...
    passed_over: tuple[tuple[Literal['top', 'btm'], BeamSet], ...] = ...
    """Per bar, the plant-assigned sets this hang dropped from the bar's
    queue (blacklisted, too large); applying the hang removes them."""
    skipped: tuple[tuple[Literal['top', 'btm'], BeamSet], ...] = ...
    """Per bar, the queued sets this hang looked past because they did not
    fit its requirement; they stay queued for a later hang."""


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
    reason: str = ...
    """`'tape_out slot'` / `'pattern_change slot'` when the gap waited for
    the day's changeover ration; empty for a caller-supplied idle."""


def rebind_sets(activity: Activity, relabel: Callable[[BeamSet | None], BeamSet | None]) -> Activity:
    """`activity` with every beam set it references passed through
    `relabel` — same id, times and lbs; unchanged when nothing is
    relabelled (a `Hanging`'s `passed_over` is left alone)."""
    ...
