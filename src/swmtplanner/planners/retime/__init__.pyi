from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from swmtplanner.planners.infinite.loop import PlanReport

__all__ = [
    'Ticket', 'PriorJob', 'Position', 'HangRecord', 'RetimeResult',
    'read_tickets', 'prior_jobs', 'locate', 'retime',
]


@dataclass(frozen=True)
class Ticket:
    """One doffed roll: ticket, machine (normalised id), scan time (plant
    local), the plant's style name and the master it resolves to (None when
    it resolves to nothing)."""
    ticket: str
    machine: str
    time: datetime
    style: str
    item: str | None


@dataclass
class PriorJob:
    """A prior-plan job: item, order (`tgt_order`), roll count, start, and
    the set numbers its hangs mounted per bar in hang order (None for an
    invented `NEW…` set)."""
    job_id: str
    item: str
    order: str | None
    rolls: int
    start: datetime
    top: tuple[str | None, ...] = ...
    btm: tuple[str | None, ...] = ...
    due_date: datetime | None = ...
    """The target order's due date when the JSON carries one."""


@dataclass
class Position:
    """Where a machine stands against its prior plan (see "Where each
    machine is" in DESIGN.md) and the jobs left to replay."""
    machine: str
    status_item: str
    tickets: int = ...
    after_status: int = ...
    consumed: int = ...
    run_up_rolls: int = ...
    extra: list[str] = ...
    extra_in_progress: bool = ...
    early: list[str] = ...
    """Rolls dropped because the floor changed to the next job early."""
    wrong_style: str | None = ...
    finished: bool = ...
    in_progress_order: str | None = ...
    remaining: list[PriorJob] = ...
    @property
    def replayable(self) -> bool: ...


@dataclass(frozen=True)
class HangRecord:
    """One hang of the retimed plan: the bar's requirement, the set hung and
    its source (`queued` / `stock` / `new`), the plan's pounds and the real
    set's, the shortfall against what the plan draws before the bar's next
    hang, and the prior plan's set at this hang (`no_prior` when the prior
    job had fewer hangs on the bar)."""
    machine: str
    bar: str
    at: datetime
    desc: str
    hung: str
    source: str
    plan_lbs: float
    set_lbs: float | None
    short_by: float
    prior: str | None
    no_prior: bool = ...
    note: str = ...
    """With `keep_sets`, why the prior set was not kept; in a later round,
    why an assigned set was dropped from this hang."""
    rolls: int = ...
    """The whole rolls the schedule doffs from the set on this bar (a roll
    straddling a swap counts for the set it finishes on)."""


@dataclass
class RetimeResult:
    report: PlanReport
    start_date: datetime
    positions: dict[str, Position]
    steps: list[tuple[str, str, int, str | None]]
    hangs: list[HangRecord]
    """Every hang of the retimed plan in time order."""
    failures: list[str]
    tickets_ignored: int
    not_in_plan: list[str]
    rounds: int = ...
    """How many replay-and-assign rounds the re-timing took."""
    withheld: list[str] = ...
    """Sets a round assigned that the next round could not hang, kept out of
    the later rounds' pool."""


MAX_ROUNDS: int


def read_tickets(path: str | Path, machines: Iterable[str],
                 variant_masters: Mapping[str, str] | None,
                 greige_ids: Iterable[str]) -> tuple[dict[str, list[Ticket]], int]:
    """Tickets by machine in time order, for the machines named; others are
    dropped and counted. Raises ValueError on a malformed file."""
    ...


def prior_jobs(plan: list[dict], machines: Iterable[str]) -> dict[str, list[PriorJob]]:
    """The prior plan's jobs per machine, chronological."""
    ...


def locate(machine: str, jobs: list[PriorJob], tickets: list[Ticket],
           prior_start: datetime, status_at: datetime, status_item: str,
           run_up_rolls: int, roll_in_progress: bool) -> Position:
    """Walk the tickets, then the load's run-up rolls, against the prior
    plan's rolls."""
    ...


def retime(config: str | Path, prior_plan: str | Path, tickets: str | Path,
           *, keep_sets: bool = ..., echo: Callable[[str], Any] = ...) -> RetimeResult:
    """Load the config, locate every machine, replay what is left through
    the manual planner (placeholders everywhere, or with `keep_sets` the
    prior plan's sets where still usable), fill the placeholders from the
    remaining inventory in runout order, and repeat — each round replaying
    with the sets the last one assigned, at their real pounds — until a
    round assigns nothing (at most `MAX_ROUNDS`); then build the
    `PlanReport`."""
    ...
