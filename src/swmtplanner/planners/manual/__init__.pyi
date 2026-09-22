from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

from swmtplanner.products import BeamSet
from swmtplanner.schedule import Inventory, Machine, ProductionPlan
from swmtplanner.planners.infinite.state import State

__all__ = ['Step', 'ManualSchedule']

StartAt = Literal['schedule_tail', 'next_runout']


@dataclass(frozen=True)
class Step:
    """One committed manual move (see DESIGN.md)."""
    machine: str
    item: str
    rolls: int
    at: StartAt = ...
    top: tuple[str | None, ...] = ...
    """Set numbers per hang in hang order; None leaves a hang to the machine's
    queue / stock (JSON null)."""
    btm: tuple[str | None, ...] = ...
    def to_json(self) -> dict[str, Any]: ...
    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> Step: ...


class ManualSchedule:
    """Build a schedule by hand on the planner's `State`: stage a move per
    machine with `rolls`, inspect the plans, `commit` or `discard` one or
    all, write schedule JSON."""
    def __init__(self, state: State) -> None: ...
    @classmethod
    def from_config(cls, config: str | Path, *, quiet: bool = ...) -> ManualSchedule: ...
    @property
    def state(self) -> State: ...
    @property
    def machines(self) -> Mapping[str, Machine]: ...
    @property
    def inventory(self) -> Inventory: ...
    @property
    def steps(self) -> tuple[Step, ...]: ...
    @property
    def staged(self) -> Mapping[str, ProductionPlan]:
        """Staged plans by machine, in staging order."""
        ...
    def pending(self) -> list[dict[str, Any]]:
        """Per machine: item, schedule_tail, next_runout, rolls_before_runout
        (`Machine.whole_rolls_before_runout`), roll_lbs_remaining, per-bar
        set + lbs + queue, and whether a plan is staged on it."""
        ...
    def stock(self, desc: str, at: datetime | None = ...) -> list[BeamSet]:
        """Stock fitting `desc`, available at `at`, not assigned by hand in a
        staged plan (another staging's automatic pick is still listed),
        oldest received first (then set number) — the warehouse's pull order."""
        ...
    def rolls(
        self, machine: str, item: str, n: int, at: StartAt = ...,
        top: Iterable[str | None] = ..., btm: Iterable[str | None] = ...,
    ) -> ProductionPlan:
        """Plan and stage `n` rolls of `item` on `machine` (replacing that
        machine's earlier staging; others stay), against the inventory less
        what other staged plans hang. A set named in `top` / `btm` is taken
        even if another staging picked it automatically — that staging is
        re-planned and its pick moves on; naming a set another staging
        assigned by hand raises, as does any bad assignment. Nothing is
        committed until `commit()`."""
        ...
    def runouts(self, machine: str | None = ...) -> list[dict[str, Any]]:
        """Hang points of one staged plan (in hang order) or of all
        (chronological across machines): machine, bar, at, desc, the set
        coming off (prev_set / prev_merge / prev_vendor), the set going on
        (auto, lbs, vendor) with its `source` (queued / assigned / stock /
        new), `assigned` (this step named it, even a queued set confirmed
        by name) and whether it is `locked`, its queue position, the stock
        options available then as `(set_no, lbs, merge, vendor)`, oldest
        received first like `stock()`, and `held_elsewhere` — which of those
        options another staging currently picks automatically."""
        ...
    def assignments(
        self, machine: str | None = ..., *, all_hangs: bool = ...,
    ) -> dict[str, list[str | None]]:
        """A staged machine's set numbers per bar in hang order: what the
        step assigned by hand (None for hangs left automatic), or with
        `all_hangs=True` the set every hang actually mounts."""
        ...
    def assign(
        self, top: Iterable[str | None] = ..., btm: Iterable[str | None] = ...,
        *, machine: str | None = ..., replace: bool = ...,
    ) -> ProductionPlan:
        """Re-stage one machine's staged step (the only one, or `machine`)
        with set numbers queued per bar (in `runouts()` order; None leaves a
        hang to the machine's queue / stock). Appends to the bar's existing
        assignments unless `replace=True`, which redefines each bar as
        exactly what is passed. Raises and keeps the previous staging on
        error."""
        ...
    def commit(self, machine: str | None = ...) -> list[Step]:
        """Commit one staged plan, or all in staging order; the steps committed."""
        ...
    def discard(self, machine: str | None = ...) -> None:
        """Drop one staged plan, or all."""
        ...
    def replay(self, steps: Iterable[Step]) -> None: ...
    def schedule_json(self) -> list[dict[str, Any]]: ...
    def write_json(self, path: str | Path) -> None: ...
    def save_steps(self, path: str | Path) -> None: ...
    @staticmethod
    def load_steps(path: str | Path) -> list[Step]: ...
