from dataclasses import dataclass
from pathlib import Path
from typing import Any

from swmtplanner.planners.infinite.coordination import ScoringContext
from swmtplanner.planners.infinite.state import Move, State
from swmtplanner.debuglog import DebugLog

__all__ = [
    'CostWeights', 'Costing',
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
    style_change: float
    runner_change: float
    pattern_change: float
    idle_time: float
    waste_lbs: float
    priority: float
    level_loading: float
    old_machine: float


class Costing:
    def __init__(self, weights: CostWeights) -> None: ...
    @property
    def weights(self) -> CostWeights: ...
    def score(self, state: State) -> float: ...
    def score_after_move(
        self, state: State, move: Move, ctx: ScoringContext,
        debuglog: DebugLog | None = ...,
    ) -> float: ...


def load_weights(path: str | Path) -> CostWeights: ...
def weights_from_dict(
    cfg: dict[str, Any], source: str = ...,
) -> CostWeights: ...
