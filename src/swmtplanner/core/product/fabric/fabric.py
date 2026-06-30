#!/usr/bin/env python

from dataclasses import dataclass

from swmtplanner.support import HasID


EXTRA_LIGHT = 0
LIGHT = 1
MEDIUM = 2
BLACK = 3
SD_BLACK = 4


@dataclass(frozen=True)
class Color:

    name: str
    number: int
    shade_rating: int

    def get_needed_strip(self, jet_state):
        raise NotImplementedError(
            'get_needed_strip is not yet implemented; pending the JetState '
            'design (defined alongside the Jet class)'
        )


class Fabric(HasID[str]):

    def __init__(self, id: str, ply1_parts: tuple[str, ...], greige: str,
                 style: str, width: float, oz_sq_yd: float, yld_pct: float,
                 name: str, number: int, shade_rating: int, jets: list[str]):
        self._id = id
        self._ply1_parts = tuple(ply1_parts)
        self._greige = greige
        self._style = style
        self._width = width
        self._color = Color(name=name, number=number, shade_rating=shade_rating)
        self._yds_per_lb = 36 * 16 / (oz_sq_yd * width) * yld_pct
        self._jets = frozenset(jets)

    @property
    def id(self) -> str:
        return self._id

    @property
    def ply1_parts(self) -> tuple[str, ...]:
        return self._ply1_parts

    @property
    def greige(self) -> str:
        return self._greige

    @property
    def style(self) -> str:
        return self._style

    @property
    def width(self) -> float:
        return self._width

    @property
    def color(self) -> Color:
        return self._color

    @property
    def yds_per_lb(self) -> float:
        return self._yds_per_lb

    def can_run_on_jet(self, jet: str) -> bool:
        return jet in self._jets
