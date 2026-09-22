from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Literal, Mapping, Sequence

from swmtplanner.support import HasID, WorkCal
from swmtplanner.products import Greige, BeamSet, BeamSetDesc, VariantMapFile
from swmtplanner.schedule.activity import Activity
from swmtplanner.schedule.inventory import InventoryView
from swmtplanner.schedule.job import Job

__all__ = ['Status', 'Machine', 'ProductionPlan', 'fresh_beam_lbs']


@dataclass(frozen=True)
class ProductionPlan:
    activities: tuple[Activity, ...]
    jobs: tuple[Job, ...]
    beam_sets_taken: tuple[BeamSet, ...] = ...
    """Stock sets the plan hung (invented sets are not listed)."""
    beam_sets_returned: tuple[BeamSet, ...] = ...
    """Sets the plan taped out that are still worth stocking, with remaining
    lbs and the tape-out's end as `avail_date`."""
    replaced_job: Job | None = ...
    """The machine's last committed job recreated (same id) with this plan's
    changeover TapeOut appended; committing swaps it in."""


@dataclass(frozen=True)
class _BarState:
    beam: BeamSet | None
    lbs_remaining: float
    threaded: bool


@dataclass(frozen=True)
class Status:
    as_of: datetime
    _bars: dict[str, _BarState]
    current_item: Greige
    is_idle: bool
    roll_lbs_remaining: float = ...
    """Yarn still to knit on the roll in progress (0.0 between rolls). Only a
    machine's initial status ever carries a nonzero value."""
    @classmethod
    def create(
        cls, *, as_of: datetime, current_item: Greige, is_idle: bool,
        top_beam: BeamSet | None, top_lbs_remaining: float, top_threaded: bool,
        btm_beam: BeamSet | None, btm_lbs_remaining: float, btm_threaded: bool,
        roll_lbs_remaining: float = ...,
        top_queue: Sequence[BeamSet] = ..., btm_queue: Sequence[BeamSet] = ...,
    ) -> Status: ...
    def beam(self, bar: Literal['top', 'btm']) -> BeamSet | None: ...
    def lbs_remaining(self, bar: Literal['top', 'btm']) -> float: ...
    def threaded(self, bar: Literal['top', 'btm']) -> bool: ...
    def queue(self, bar: Literal['top', 'btm']) -> tuple[BeamSet, ...]:
        """Sets assigned to `bar` and not yet threaded, next up first. A
        Hanging of the front set pops it."""
        ...
    @property
    def current_family(self) -> str: ...
    def apply_activity(self, activity: Activity) -> Status: ...


def fresh_beam_lbs(beam: BeamSetDesc) -> float:
    """Yarn on a freshly loaded beam by denier convention — sizes the sets
    the planner invents when nothing suitable is in stock."""
    ...


class Machine(HasID[str]):
    def __init__(
        self,
        id: str,
        init_item: Greige,
        start: datetime,
        init_top_beam: BeamSet,
        init_top_lbs: float,
        init_btm_beam: BeamSet,
        init_btm_lbs: float,
        workcal: WorkCal,
        is_new: bool = ...,
        init_variant: str | None = ...,
        variant_map: VariantMapFile | None = ...,
        init_roll_lbs_remaining: float = ...,
        init_top_queue: Sequence[BeamSet] = ...,
        init_btm_queue: Sequence[BeamSet] = ...,
    ) -> None:
        """`init_roll_lbs_remaining`: lbs still to knit on the roll in progress
        at `start` (0 = between rolls); the planner always finishes it first.
        `init_*_queue`: sets the plant has assigned to that bar and not yet
        threaded — hung next, in order."""
        ...
    @property
    def workcal(self) -> WorkCal: ...
    @property
    def is_new(self) -> bool: ...
    @property
    def init_variant(self) -> str | None:
        """The plant's variant name for what the machine was running at
        `start`, when the machines file named one (else `None`)."""
        ...
    @property
    def initial_status(self) -> Status: ...
    @property
    def current_status(self) -> Status: ...
    @property
    def activities(self) -> tuple[Activity, ...]: ...
    @property
    def jobs(self) -> tuple[Job, ...]: ...
    @property
    def schedule_tail(self) -> datetime: ...
    @property
    def next_runout(self) -> datetime: ...
    @property
    def whole_rolls_before_runout(self) -> int:
        """Rolls doffed running the current item until `next_runout`: the roll
        in progress when the beams can finish it, plus the whole rolls that
        fit above the floor. 0 when the changeover is immediately due."""
        ...
    def producible_lbs_through(
        self, item: Greige, end: datetime,
        start: datetime | None = ...,
        inventory: InventoryView | None = ...,
    ) -> float: ...
    def producible_lbs_in_week(
        self, item: Greige, year: int, week: int,
        start: datetime | None = ...,
        inventory: InventoryView | None = ...,
    ) -> float: ...
    def status_at(self, t: datetime) -> Status: ...
    def add_activities(self, activities: Iterable[Activity]) -> None: ...
    def add_jobs(self, jobs: Iterable[Job]) -> None: ...
    def replace_last_job(self, job: Job) -> None:
        """Swap the last job for a recreated copy with the same id."""
        ...
    def commit_plan(self, plan: ProductionPlan) -> None:
        """add_activities + replace_last_job (if any) + add_jobs."""
        ...
    def plan_production(
        self,
        item: Greige,
        lbs: float,
        start_at: Literal['schedule_tail', 'next_runout'],
        idle_for: timedelta = ...,
        tgt_order: str | None = ...,
        inventory: InventoryView | None = ...,
        assign: Mapping[str, Sequence[str | None]] | None = ...,
    ) -> ProductionPlan:
        """Pure. `inventory` is read, never mutated: stock sets hung and sets
        taped out are reported as `beam_sets_taken` / `beam_sets_returned`.
        `assign` queues set numbers per bar ('top' / 'btm') for the plan's
        hangs, `None` leaving a hang to the normal choice; an unusable or
        unused assignment raises ValueError, as does one that would displace
        a plant-assigned set at the front of the bar's queue (locked in)."""
        ...
