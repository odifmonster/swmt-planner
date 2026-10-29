#!/usr/bin/env python

from dataclasses import dataclass, field, InitVar

from ....support import HasID
from .beamconfig import BeamConfig


@dataclass(frozen=True, eq=False)
class Greige(HasID[str]):
    id: str
    gauge: int
    width: int
    rack_wt: float
    std_wt: float
    beam_cfgs: tuple[BeamConfig, ...]
    rates: InitVar[dict[str, float]]
    _rates: dict[str, float] = field(init=False, repr=False)

    def __post_init__(self, rates: dict[str, float]) -> None:
        object.__setattr__(self, '_rates', dict(rates))

    @property
    def pattern(self) -> list[tuple[str, ...]]:
        return [tuple(bar.stitch for bar in cfg.bars) for cfg in self.beam_cfgs]

    @property
    def beamsets(self) -> list[tuple[str, tuple[int, ...]]]:
        return [(cfg.beamset.id, tuple(bar.num for bar in cfg.bars))
                for cfg in self.beam_cfgs]

    def can_run_on_machine(self, mchn: str) -> bool:
        return mchn in self._rates

    def get_rate_on_machine(self, mchn: str) -> float:
        return self._rates[mchn]
