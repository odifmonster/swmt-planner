from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Iterable, Literal, Mapping, Sequence

from swmtplanner.support import HasID, WorkCal
from swmtplanner.products import Greige, BeamSet, BeamSetDesc, VariantMapFile
from swmtplanner.schedule.activity import Activity
from swmtplanner.schedule.inventory import InventoryView
from swmtplanner.schedule.capacity import ChangeoverCapacity, Slot
from swmtplanner.schedule.job import Job

__all__ = ['Status', 'Machine', 'ProductionPlan', 'PassedOver', 'Fill', 'UnhungAssignments', 'fresh_beam_lbs',
           'RUNNING_EFFICIENCY', 'effective_rate', 'MIN_STOCK_SET_LBS',
           'choose_stock']

RUNNING_EFFICIENCY: float
"""Share of running time a machine actually knits (0.765); every style rate
the model uses is scaled by it (planning mode substitutes its own, by
machine type)."""

MIN_STOCK_SET_LBS: float
"""A stock set lighter than this (500 lbs) is passed over for a hang while
any heavier set fits the bar."""


def effective_rate(nominal: float, mtype: str) -> float:
    """A style's nominal lbs/hour scaled by the running efficiency; `mtype`
    is `'new'` or `'old'` (planning mode has a factor per type)."""
    ...


def choose_stock(cands: list[BeamSet], prev: BeamSet | None) -> BeamSet:
    """The stock set to hang from `cands` for continuity with `prev`, the set
    coming off the bar: same merge first, then same vendor, then any (a tier
    is skipped when `prev` or its merge/vendor is unknown); oldest received
    first, then lowest set number; sets under `MIN_STOCK_SET_LBS` ignored
    unless they are all there is."""
    ...



@dataclass(frozen=True)
class PassedOver:
    """A plant-assigned set a hang dropped from a bar's queue because it did
    not fit the bar's requirement at the time, or is blacklisted."""
    bar: Literal['top', 'btm']
    beam_set: BeamSet
    wanted: BeamSetDesc
    at: datetime
    reason: str = ...
    """`'does not fit'` or `'blacklisted'`."""


class UnhungAssignments(ValueError):
    """`plan_production(assign=)` named sets the plan never got to hang;
    `leftover` is `{bar: [set numbers]}` of them."""
    leftover: dict[str, list[str]]
    def __init__(self, leftover: dict[str, list[str]]) -> None: ...


@dataclass(frozen=True)
class Fill:
    """What a plan's preamble may knit instead of idling while it waits for
    a changeover-ration slot: whole `rolls` of the machine's current item,
    raised against `tgt_order` ("Filling a slot wait" in DESIGN.md)."""
    rolls: int
    tgt_order: str | None = ...


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
    capacity_taken: tuple[Slot, ...] = ...
    """The changeover-ration slots the plan's tape-outs and pattern changes
    occupy; committing books them."""
    queue_passed_over: tuple[PassedOver, ...] = ...
    """Queued sets a hang in this plan passed over; committing keeps them on
    the machine (`Machine.queue_passed_over`)."""


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
    def drop_queued(self, bar: Literal['top', 'btm']) -> Status:
        """This status without `bar`'s front queued set (a pass-over); pure.
        Raises ValueError on an empty queue."""
        ...
    def rebind_sets(self, relabel: Callable[[BeamSet | None], BeamSet | None]) -> Status:
        """This status with each bar's set passed through `relabel`; lbs,
        threading and queues untouched. Pure."""
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
        at `start` (0 = between rolls); the planner always finishes it first —
        taken as 0 when either bar is foreign (its set does not fit
        `init_item`; the plant reported the machine mid-change).
        `init_*_queue`: sets the plant has assigned to that bar and not yet
        threaded — hung next, in order, when they fit."""
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
    def queue_passed_over(self) -> tuple[PassedOver, ...]:
        """Every queued set a committed plan passed over, in commit order."""
        ...
    def rebind_sets(self, mapping: Mapping[str, BeamSet]) -> None:
        """Relabel every set whose id is in `mapping` (a placeholder) throughout
        the committed schedule — activities, jobs, rolls, statuses — with the
        mapped set's identity under the plan's pounds."""
        ...
    @property
    def schedule_tail(self) -> datetime: ...
    @property
    def next_runout(self) -> datetime: ...
    def run_until(
        self, t: datetime, inventory: InventoryView | None = ...,
    ) -> ProductionPlan | None:
        """A plan keeping the machine on its current item up to `t` (the roll
        in progress plus every whole roll starting before `t`), or an `Idle`
        to `t` when it has nothing to run; None when `t` is not after the
        schedule tail. Not committed."""
        ...
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
        capacity: ChangeoverCapacity | None = ...,
        fill: Fill | None = ...,
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
        """add_activities + replace_last_job (if any) + add_jobs, keeping
        `plan.queue_passed_over`."""
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
        capacity: ChangeoverCapacity | None = ...,
        prior_job: str | None = ...,
        fill: Fill | None = ...,
    ) -> ProductionPlan:
        """Pure. `capacity` (the changeover ration) takes one `change` unit
        when the preamble changes the machine at all and places each TapeOut
        and old-machine PatternChange at the next allowed slot, emitting an
        `Idle(reason=...)` while the machine waits; the slots are reported as
        `capacity_taken`. `fill` lets a wait be spent knitting whole rolls of
        the current item (up to `fill.rolls`, each started before the slot),
        which join the current item's job marked `fill`.
        `inventory` is read, never mutated: stock sets hung and sets
        taped out are reported as `beam_sets_taken` / `beam_sets_returned`.
        `assign` queues set numbers per bar ('top' / 'btm') for the plan's
        hangs, `None` leaving a hang to the normal choice; an unusable or
        unused assignment raises ValueError, as does one that would displace
        a plant-assigned set at the front of the bar's queue (locked in).
        `tgt_order` and `prior_job` are stamped on the new item's Job."""
        ...
