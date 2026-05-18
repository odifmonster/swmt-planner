#!/usr/bin/env python

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal, TYPE_CHECKING

from swmtplanner.support import HasID

if TYPE_CHECKING:
    from swmtplanner.products import Greige, BeamSet


# Module-level duration constants — constant across all machines, per the
# design doc.
TAPE_OUT_SINGLE_DURATION: timedelta = timedelta(hours=4)
TAPE_OUT_BOTH_DURATION: timedelta = timedelta(hours=6)
BEAM_LOAD_DURATION: timedelta = timedelta(hours=2)


def _make_id_counter():
    ctr = 0
    def _next():
        nonlocal ctr
        ctr += 1
        return ctr
    return _next


_JOB_ID = _make_id_counter()
_WASTE_ID = _make_id_counter()
_TAPE_OUT_ID = _make_id_counter()
_BEAM_LOAD_ID = _make_id_counter()
_STYLE_CHANGE_ID = _make_id_counter()
_IDLE_ID = _make_id_counter()


@dataclass(frozen=True)
class Activity(HasID[str]):
    """Abstract base for anything that occupies machine time. Each concrete
    activity has a deterministic start and end and a stable id used for
    referencing it on a machine's schedule."""
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Job(Activity):
    """Productive activity. The plant ships only whole rolls
    (~`item.tgt_wt` lbs each) or half rolls (~`item.tgt_wt / 2`),
    within tolerance — so `Job.lbs` is normally `N * tgt_wt` (N
    whole rolls) or `N * tgt_wt + tgt_wt / 2` (N whole + a half-roll
    from a beam runout). The half-roll rule lives in `_split_roll`
    in `schedule/machine/machine.py`. Yarn that doesn't fit those
    sizes — over-half scraps or sub-half tails at a runout — is
    emitted as a separate `Waste` activity, never folded into
    `Job.lbs`.

    `rolls` is the per-roll delivery schedule: a tuple of
    `(lbs, completion_time)` pairs, one per physical roll coming off
    the machine, in chronological order. Each entry is either a whole
    roll (`tgt_wt` ± tolerance) or a half-roll (`tgt_wt / 2` ±
    tolerance); their lbs sum to exactly `Job.lbs`. The demand layer
    reads `rolls` rather than treating the whole `Job.lbs` as
    delivered at `Job.end`, since the dyeing plant is on the same
    campus and rolls ship as they come off — lateness is per-roll,
    not per-Job.

    Defaults to `()` so hand-constructed `Job`s in tests continue to
    work; the demand views treat an empty `rolls` as a single chunk
    at `Job.end` (the pre-`rolls` behavior)."""
    item: 'Greige'
    lbs: float
    rolls: tuple[tuple[float, datetime], ...] = ()
    _count: int = field(default_factory=_JOB_ID, init=False)

    @property
    def id(self) -> str:
        return f'JOB{self._count:05}'


@dataclass(frozen=True)
class Waste(Activity):
    """Sub-half-roll partial fabric produced when a beam exhausts
    mid-roll. Time and lbs are real (the machine ran) but the fabric
    is too small to keep and is discarded; never reaches the demand
    layer. Partials at or above `tgt_wt / 2` are emitted as `Job`
    activities instead — see `Job` and `_split_roll`."""
    item: 'Greige'
    lbs: float
    _count: int = field(default_factory=_WASTE_ID, init=False)

    @property
    def id(self) -> str:
        return f'WASTE{self._count:05}'


@dataclass(frozen=True)
class TapeOut(Activity):
    """Forced removal of yarn from one or both bars before natural exhaustion.
    'both' is more expensive than two sequential singles because the floor
    cannot parallelize the cuts. When one bar has already exhausted, the
    other is taped out as a single."""
    bars: Literal['top', 'btm', 'both']
    _count: int = field(default_factory=_TAPE_OUT_ID, init=False)

    @property
    def id(self) -> str:
        return f'TAPEOUT{self._count:05}'


@dataclass(frozen=True)
class BeamLoad(Activity):
    """Mounting a fresh beam onto one bar. `lbs` is the yarn quantity on the
    freshly loaded beam — needed so the machine's `Status` can be updated
    when the activity completes. Duration is constant across machines.
    Always per-bar; loading both bars is two separate BeamLoad activities."""
    bar: Literal['top', 'btm']
    beam: 'BeamSet'
    lbs: float
    _count: int = field(default_factory=_BEAM_LOAD_ID, init=False)

    @property
    def id(self) -> str:
        return f'BEAMLOAD{self._count:05}'


@dataclass(frozen=True)
class StyleChange(Activity):
    """Reconfiguring the machine from one greige style to another. Emitted
    on every item transition, even when beams are shared. is_family_change
    distinguishes the simple (within-family) case from the family-change
    case, which takes longer for pattern-wheel / programming reasons."""
    from_item: 'Greige'
    to_item: 'Greige'
    is_family_change: bool
    _count: int = field(default_factory=_STYLE_CHANGE_ID, init=False)

    @property
    def id(self) -> str:
        return f'STYLECHANGE{self._count:05}'


@dataclass(frozen=True)
class Idle(Activity):
    """Deliberate gap where the machine is committed to not running, used
    when staffing limits prevent continuous operation. Beam state and
    current_item are unchanged across the interval."""
    _count: int = field(default_factory=_IDLE_ID, init=False)

    @property
    def id(self) -> str:
        return f'IDLE{self._count:05}'
