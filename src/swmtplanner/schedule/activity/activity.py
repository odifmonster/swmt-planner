#!/usr/bin/env python

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, TYPE_CHECKING

from swmtplanner.support import HasID

if TYPE_CHECKING:
    from swmtplanner.products import Greige, BeamSet


# Module-level duration constants — a number of **work-hours** (float),
# constant across all machines, per the design doc's Constants section. They
# are passed straight to `WorkCal.offset_work_hours`, which takes hours, so
# they're kept as hours rather than timedeltas.
TAPE_OUT_SINGLE_DURATION: float = 2.0
TAPE_OUT_BOTH_DURATION: float = 3.0
# Mounting a fresh beam splits into a physical hang then a yarn threading;
# the two together replace the old single beam-load.
HANGING_SINGLE_DURATION: float = 1.0
HANGING_BOTH_DURATION: float = 1.5
THREADING_SINGLE_DURATION: float = 2.0
THREADING_BOTH_DURATION: float = 3.5
# Taking one completed roll off the machine.
DOFF_DURATION: float = 20 / 60           # 20 minutes
# Changeover durations, by type (selected by machine.is_new + pattern family;
# the activity class carries the semantic — there is no is_family_change flag).
STYLE_CHANGE_DURATION: float = 5 / 60    # 5 minutes
RUNNER_CHANGE_DURATION: float = 45 / 60  # 45 minutes
PATTERN_CHANGE_DURATION: float = 1.5

# Runout model — tunable, to be calibrated against real floor behavior. A beam
# is never knit to zero: BEAM_FLOOR_LBS is the residue that can't be drawn off,
# so usable yarn on a bar is `bar_lbs - BEAM_FLOOR_LBS`. The operator also
# won't knit through a near-empty beam: when a bar's usable falls below
# MAX_BEAM_WASTE_LBS it's swapped (residue discarded as Waste) before the next
# roll rather than knit down further. Defined here (the leaf module) so both
# status.py (the "removed" guard predicate) and machine.py (the planning
# gates) can import them without a circular dependency.
BEAM_FLOOR_LBS: float = 5.0
MAX_BEAM_WASTE_LBS: float = 100.0


def _make_id_counter():
    ctr = 0
    def _next():
        nonlocal ctr
        ctr += 1
        return ctr
    return _next


_KNIT_ID = _make_id_counter()
_WASTE_ID = _make_id_counter()
_DOFF_ID = _make_id_counter()
_TAPE_OUT_ID = _make_id_counter()
_HANGING_ID = _make_id_counter()
_THREADING_ID = _make_id_counter()
_STYLE_CHANGE_ID = _make_id_counter()
_RUNNER_CHANGE_ID = _make_id_counter()
_PATTERN_CHANGE_ID = _make_id_counter()
_IDLE_ID = _make_id_counter()


@dataclass(frozen=True)
class Activity(HasID[str]):
    """Abstract base for anything that occupies machine time. Each concrete
    activity has a deterministic start and end and a stable id used for
    referencing it on a machine's schedule."""
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Knit(Activity):
    """One uninterrupted run of knitting — the fabric wound between two
    consecutive interruptions (a doff, a beam swap, or the start/end of the
    run). A `Knit` covers at most one roll (`0 < lbs <= item.tgt_wt`): every
    roll ends in a `Doff`, and a beam swap can split a roll across two
    `Knit`s.

    `Knit` carries no per-roll detail — roll completions live on the `Job`
    record in `schedule/job`. The demand layer reads `Job.rolls`, never
    `Knit`s."""
    item: 'Greige'
    lbs: float
    _count: int = field(default_factory=_KNIT_ID, init=False)

    @property
    def id(self) -> str:
        return f'KNIT{self._count:08}'


@dataclass(frozen=True)
class Waste(Activity):
    """Usable yarn discarded from a beam the planner swaps early — removed
    unknit, not fabric the machine ran, so its duration is zero
    (`start == end`). Emitted when a bar's usable residue
    (`bar_lbs - BEAM_FLOOR_LBS`) falls below `MAX_BEAM_WASTE_LBS`: the
    operator won't knit through a near-empty beam, so the residue is
    dropped and a paired re-thread (`Hanging` + `Threading`) refills the bar.
    Applying it empties the named `bar` (beam -> None, lbs -> 0). Never
    reaches the demand layer; the cost layer charges it per-lb via the
    `waste_lbs` weight.

    `beam` is the yarn SKU being discarded (the beam that was on `bar`) —
    what gets wasted is yarn, not a greige item; carried for future
    beam-set inventory tracking."""
    beam: 'BeamSet'
    bar: Literal['top', 'btm']
    lbs: float
    _count: int = field(default_factory=_WASTE_ID, init=False)

    @property
    def id(self) -> str:
        return f'WASTE{self._count:08}'


@dataclass(frozen=True)
class Doff(Activity):
    """Taking one completed roll off the machine. Fieldless beyond
    `start`/`end` (mirrors `Idle`'s shape; a distinct class for readability).
    One `Doff` per completed roll; a roll is "ready to ship" when it comes
    off, so the invariant is `Doff.end == that roll's completion_time`."""
    _count: int = field(default_factory=_DOFF_ID, init=False)

    @property
    def id(self) -> str:
        return f'DOFF{self._count:08}'


@dataclass(frozen=True)
class TapeOut(Activity):
    """Forced removal of yarn from one or both bars before natural exhaustion.
    'both' is cheaper than two separate singles (shared setup) but more than
    one, since the floor can't fully parallelize the cuts. When one bar has
    already exhausted, the other is taped out as a single.

    `top_beam` / `btm_beam` record the yarn SKU(s) removed, per bar (`None`
    for a bar this tape-out doesn't touch). Taped-out yarn is preserved for
    re-use rather than discarded; the SKUs are carried for future beam-set
    inventory tracking."""
    bars: Literal['top', 'btm', 'both']
    top_beam: 'BeamSet | None' = None
    btm_beam: 'BeamSet | None' = None
    _count: int = field(default_factory=_TAPE_OUT_ID, init=False)

    @property
    def id(self) -> str:
        return f'TAPEOUT{self._count:08}'


@dataclass(frozen=True)
class Hanging(Activity):
    """Mounting a fresh beam set on the named bar(s) — this is what loads the
    physical set, so applying it sets each bar's `beam` and lbs (from the
    matching `*_beam` / `*_lbs`; the fields for an untouched bar are ignored)
    and leaves that bar **un-threaded**. It pairs with a `Threading`, which
    routes the yarn. `'both'` is cheaper than two singles (shared setup).
    Together, `Hanging` + `Threading` replace the old single `BeamLoad`."""
    bars: Literal['top', 'btm', 'both']
    top_beam: 'BeamSet | None' = None
    top_lbs: float = 0.0
    btm_beam: 'BeamSet | None' = None
    btm_lbs: float = 0.0
    _count: int = field(default_factory=_HANGING_ID, init=False)

    @property
    def id(self) -> str:
        return f'HANGING{self._count:08}'


@dataclass(frozen=True)
class Threading(Activity):
    """Routing the loaded yarn into the machine. Applying it flips the named
    bar(s) to threaded (`<bar>_threaded = True`) and changes nothing else —
    the beam and lbs were already loaded by the preceding `Hanging`. `'both'`
    is cheaper than two singles (shared setup)."""
    bars: Literal['top', 'btm', 'both']
    _count: int = field(default_factory=_THREADING_ID, init=False)

    @property
    def id(self) -> str:
        return f'THREADING{self._count:08}'


@dataclass(frozen=True)
class StyleChange(Activity):
    """Changeover on a **new** machine (`is_new`): one uniform reconfigure
    regardless of pattern family. The class carries the semantic — which
    changeover type is emitted is decided by the planner from `is_new` and the
    pattern-family comparison (see "Beam-swap decision" in DESIGN.md)."""
    from_item: 'Greige'
    to_item: 'Greige'
    _count: int = field(default_factory=_STYLE_CHANGE_ID, init=False)

    @property
    def id(self) -> str:
        return f'STYLECHANGE{self._count:08}'


@dataclass(frozen=True)
class RunnerChange(Activity):
    """Changeover on a **legacy** machine within the same pattern family —
    the lighter runner reconfigure."""
    from_item: 'Greige'
    to_item: 'Greige'
    _count: int = field(default_factory=_RUNNER_CHANGE_ID, init=False)

    @property
    def id(self) -> str:
        return f'RUNNERCHANGE{self._count:08}'


@dataclass(frozen=True)
class PatternChange(Activity):
    """Changeover on a **legacy** machine across pattern families — the
    heavier pattern-wheel rework."""
    from_item: 'Greige'
    to_item: 'Greige'
    _count: int = field(default_factory=_PATTERN_CHANGE_ID, init=False)

    @property
    def id(self) -> str:
        return f'PATTERNCHANGE{self._count:08}'


@dataclass(frozen=True)
class Idle(Activity):
    """Deliberate gap where the machine is committed to not running, used
    when staffing limits prevent continuous operation. Beam state and
    current_item are unchanged across the interval."""
    _count: int = field(default_factory=_IDLE_ID, init=False)

    @property
    def id(self) -> str:
        return f'IDLE{self._count:08}'
