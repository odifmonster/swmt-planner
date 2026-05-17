from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Literal

from swmtplanner.support import HasID, WorkCal
from swmtplanner.products import Greige, BeamSet
from swmtplanner.schedule.activity import Activity

__all__ = ['Status', 'Machine', 'fresh_beam_lbs']


@dataclass(frozen=True)
class Status:
    as_of: datetime
    top_beam: BeamSet | None
    btm_beam: BeamSet | None
    top_lbs_remaining: float
    btm_lbs_remaining: float
    current_item: Greige
    is_idle: bool
    @property
    def current_family(self) -> str: ...
    def apply_activity(self, activity: Activity) -> Status: ...


def fresh_beam_lbs(beam: BeamSet) -> float: ...


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
        simple_change_duration: timedelta,
        family_change_duration: timedelta,
        is_new: bool = ...,
    ) -> None: ...
    @property
    def workcal(self) -> WorkCal: ...
    @property
    def is_new(self) -> bool: ...
    @property
    def initial_status(self) -> Status: ...
    @property
    def current_status(self) -> Status: ...
    @property
    def activities(self) -> tuple[Activity, ...]: ...
    @property
    def next_job_end(self) -> datetime: ...
    @property
    def next_runout(self) -> datetime: ...
    def producible_lbs_in_week(
        self, item: Greige, year: int, week: int,
        start: datetime | None = ...,
    ) -> float: ...
    def status_at(self, t: datetime) -> Status: ...
    def add_activities(self, activities: Iterable[Activity]) -> None: ...
    def plan_production(
        self,
        item: Greige,
        lbs: float,
        start_at: Literal['next_job_end', 'next_runout'],
        idle_for: timedelta = ...,
    ) -> list[Activity]: ...
