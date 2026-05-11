from datetime import datetime
from typing import Literal, NamedTuple

from swmtplanner.support import HasID, WorkCal
from swmtplanner.products import BeamSet, Greige
from swmtplanner.schedule import Job

__all__ = ['Decision', 'Machine']

class Decision(NamedTuple):
    mchn_id: str
    dt: datetime

class Machine(HasID[str]):
    def __init__(self, id: str, init_item: Greige, start_date: datetime, workcal: WorkCal) -> None: ...
    @property
    def schedule(self) -> tuple[Job, ...]: ...
    @property
    def workcal(self) -> WorkCal: ...
    @property
    def next_job_end(self) -> datetime: ...
    def get_bar_status(self, bar: Literal['top', 'btm'], on_dt: datetime | None = None) -> BeamSet:
        """Returns the beam set that will be on the given bar on the given date, or the
        beam set that will be there after the end of the current schedule if no date is
        provided."""
        ...
    def avail_hours_in_week(self, year: int, week: int) -> float:
        """Get the remaining available working hours in the given week."""
        ...
    def predict_job_end(self, item: Greige, lbs: float) -> datetime:
        """Predict when a job to produce some number of lbs of the given item will end if
        it runs after the end of the current schedule."""
        ...
    def add_job(self, item: Greige, lbs: float) -> Job:
        """Add a job for a greige style and a number of lbs to the end of the schedule."""
        ...
    def next_decisions(self) -> list[Decision]:
        """Get the next "decision points" for this machine."""
        ...