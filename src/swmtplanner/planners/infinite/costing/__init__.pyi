from dataclasses import dataclass
from pathlib import Path
from typing import Any

from swmtplanner.planners.infinite.coordination import ScoringContext
from swmtplanner.planners.infinite.state import Move, State

__all__ = [
    'CostWeights', 'CostBreakdown', 'Costing',
    'load_weights', 'weights_from_dict',
]


@dataclass
class CostWeights:
    lateness: float
    drainage: float
    carrying: float
    excess: float
    tape_out_single: float
    tape_out_both: float
    family_change: float
    idle_time: float
    priority: float
    level_loading: float
    old_machine: float


@dataclass(frozen=True)
class CostBreakdown:
    lateness: float
    drainage: float
    carrying: float
    excess: float
    tape_out_single: float
    tape_out_both: float
    family_change: float
    idle_time: float
    priority: float
    level_loading: float
    old_machine: float
    @property
    def total(self) -> float: ...


class Costing:
    def __init__(self, weights: CostWeights) -> None: ...
    @property
    def weights(self) -> CostWeights: ...
    def score(self, state: State) -> float: ...
    def score_after_move(
        self, state: State, move: Move, ctx: ScoringContext,
    ) -> float: ...
    def cost_breakdown_after_move(
        self, state: State, move: Move, ctx: ScoringContext,
    ) -> CostBreakdown: ...


def load_weights(path: str | Path) -> CostWeights: ...
def weights_from_dict(
    cfg: dict[str, Any], source: str = ...,
) -> CostWeights: ...
