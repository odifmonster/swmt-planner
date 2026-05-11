#!/usr/bin/env python

from datetime import date, datetime, timedelta
from typing import Literal
from bisect import bisect_right
from collections import namedtuple

from swmtplanner.support import HasID, WorkCal
from swmtplanner.products import BeamSet, Greige
from swmtplanner.schedule import Job

Decision = namedtuple('Decision', ['mchn_id', 'dt'])

class Machine(HasID[str]):

    def __init__(self, id: str, init_item: Greige, start_date: datetime, workcal: WorkCal) -> None:
        self._id = id
        self._jobs: list[Job] = [Job(init_item, start_date, start_date, 0)]
        self._workcal = workcal

    @property
    def id(self):
        return self._id

    @property
    def prefix(self):
        return 'Machine'

    @property
    def schedule(self) -> tuple[Job, ...]:
        return tuple(self._jobs[1:])

    @property
    def workcal(self) -> WorkCal:
        return self._workcal

    @property
    def next_job_end(self) -> datetime:
        return self._jobs[-1].end

    def get_bar_status(self, bar: Literal['top', 'btm'], on_dt: datetime | None = None) -> BeamSet:
        if on_dt is None:
            on_dt = self._jobs[-1].end
        idx = bisect_right(self._jobs, on_dt, key=lambda j: j.start) - 1
        if idx < 0:
            idx = 0
        cfg = self._jobs[idx].item.configuration
        if bar == 'top':
            return BeamSet(cfg.top_beam)
        if bar == 'btm':
            return BeamSet(cfg.btm_beam)
        raise ValueError(f"bar must be 'top' or 'btm', got {bar!r}")

    def avail_hours_in_week(self, year: int, week: int) -> float:
        monday = date.fromisocalendar(year, week, 1)
        week_start = datetime(monday.year, monday.month, monday.day)
        week_end = week_start + timedelta(days=7)
        start = max(self._jobs[-1].end, week_start)
        return self._workcal.get_work_hours_between(start, week_end)

    def predict_job_end(self, item: Greige, lbs: float) -> datetime:
        rate = item.get_rate_on_mchn(self._id)
        hours = lbs / rate
        return self._workcal.offset_work_hours(self._jobs[-1].end, hours)

    def add_job(self, item: Greige, lbs: float) -> Job:
        start = self._jobs[-1].end
        end = self.predict_job_end(item, lbs)
        job = Job(item, start, end, lbs)
        self._jobs.append(job)
        return job
    
    def next_decisions(self):
        return [Decision(mchn_id=self.id, dt=self.next_job_end)]