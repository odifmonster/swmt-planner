from typing import NamedTuple

from swmtplanner.support import HasID

__all__ = ['BeamConfig', 'Greige']

class BeamConfig(NamedTuple):
    top_beam: str
    top_pct: float
    btm_beam: str
    btm_pct: float

class Greige(HasID[str]):
    def __init__(self, id: str, family: str, tgt_wt: float, top_beam: str, top_pct: float,
                 btm_beam: str, btm_pct: float, safety: float, machines: dict[str, float]) -> None: ...
    @property
    def family(self) -> str: ...
    @property
    def tgt_wt(self) -> float: ...
    @property
    def configuration(self) -> BeamConfig: ...
    @property
    def safety(self) -> float: ...
    def can_run_on_mchn(self, mchn: str) -> bool: ...
    def get_rate_on_mchn(self, mchn: str) -> float: ...