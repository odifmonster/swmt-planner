#!/usr/bin/env python

from dataclasses import dataclass

from swmtplanner.support import HasID


EXTRA_LIGHT = 0
LIGHT = 1
MEDIUM = 2
BLACK = 3
SD_BLACK = 4

STRIP = 'STRIP'
EMPTY = 'EMPTY'


def _shade_tier(shade: int) -> int:
    if shade in (EXTRA_LIGHT, LIGHT):
        return 0
    if shade == MEDIUM:
        return 1
    return 2


@dataclass(frozen=True)
class Color:

    name: str
    number: int
    shade_rating: int

    def get_needed_strip(self, state) -> list[str]:
        prev, nxt = state.max_prev_shade, self.shade_rating
        activities: list[str] = []

        n_strips = 0
        if prev is not None and _shade_tier(nxt) < _shade_tier(prev):
            if prev == BLACK:
                n_strips = 1 if state.cycles_since_strip == 0 else 2
            else:
                n_strips = 1

        if state.cycles_since_strip >= 9:
            n_strips = max(n_strips, 1)

        activities += [STRIP] * n_strips

        if nxt == EXTRA_LIGHT:
            already_light = n_strips == 0 and prev in (EXTRA_LIGHT, LIGHT)
            if not already_light:
                activities.append(EMPTY)

        return activities


class Fabric(HasID[str]):

    def __init__(self, id: str, ply1_parts: tuple[str, ...], greige: str,
                 style: str, width: float, oz_sq_yd: float, yld_pct: float,
                 name: str, number: int, shade_rating: int,
                 jets: dict[str, tuple[float, float]]):
        self._id = id
        self._ply1_parts = tuple(ply1_parts)
        self._greige = greige
        self._style = style
        self._width = width
        self._color = Color(name=name, number=number, shade_rating=shade_rating)
        self._yds_per_lb = 36 * 16 / (oz_sq_yd * width) * yld_pct
        self._jets = dict(jets)

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

    def load_range_on_jet(self, jet: str) -> tuple[float, float]:
        if jet not in self._jets:
            raise ValueError(
                f'fabric {self._id!r} cannot run on jet {jet!r}'
            )
        return self._jets[jet]
