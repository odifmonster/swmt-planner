from dataclasses import dataclass
from pathlib import Path

from swmtplanner.planners.infinite.state import Move, State

__all__ = ['CostWeights', 'Costing', 'load_weights']


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


class Costing:
    def __init__(self, weights: CostWeights) -> None: ...
    @property
    def weights(self) -> CostWeights: ...
    def score(self, state: State) -> float: ...
    def score_after_move(self, state: State, move: Move) -> float: ...


def load_weights(path: str | Path) -> CostWeights: ...
