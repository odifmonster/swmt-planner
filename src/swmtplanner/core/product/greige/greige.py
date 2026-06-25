#!/usr/bin/env python

from dataclasses import dataclass

from swmtplanner.support import HasID


@dataclass(frozen=True)
class BeamConfig:

    beamset: str
    pct: float


class Greige(HasID[str]):

    def __init__(self, id: str, tgt_wt: float, safety: float, pattern: str,
                 top: BeamConfig, bottom: BeamConfig, alt_names: list[str]):
        self._id = id
        self._tgt_wt = tgt_wt
        self._safety = safety
        self._pattern = pattern
        self._top = top
        self._bottom = bottom
        self._alt_names = tuple(alt_names)

    @property
    def id(self) -> str:
        return self._id

    @property
    def tgt_wt(self) -> float:
        return self._tgt_wt

    @property
    def safety(self) -> float:
        return self._safety

    @property
    def pattern(self) -> str:
        return self._pattern

    @property
    def top(self) -> BeamConfig:
        return self._top

    @property
    def bottom(self) -> BeamConfig:
        return self._bottom

    @property
    def alt_names(self) -> tuple[str, ...]:
        return self._alt_names
