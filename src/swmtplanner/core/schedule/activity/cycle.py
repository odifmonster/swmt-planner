#!/usr/bin/env python

from dataclasses import dataclass
from typing import TYPE_CHECKING

from swmtplanner.core.product.fabric import BLACK, SD_BLACK
from .activity import Activity

if TYPE_CHECKING:
    from swmtplanner.core.product.fabric import Color
    from swmtplanner.core.materials import DyeLot


STRIP_CYCLE_HRS = 7


def cycle_time_for_color(color: 'Color') -> float:
    if color.shade_rating == BLACK:
        return 10
    if color.shade_rating == SD_BLACK:
        return 6
    return 8


@dataclass(frozen=True, eq=False)
class DyeCycle(Activity):

    lots: 'tuple[DyeLot, ...]'

    def __post_init__(self):
        if not self.lots:
            raise ValueError('a dye cycle must have at least one lot')
        greiges, styles, colors = set(), set(), set()
        for lot in self.lots:
            if lot.greige is None or lot.fabric is None:
                raise ValueError(
                    'every lot in a dye cycle must have rolls and an '
                    'assigned fabric'
                )
            greiges.add(lot.greige)
            styles.add(lot.fabric.style)
            colors.add(lot.fabric.color)
        if len(greiges) > 1 or len(styles) > 1 or len(colors) > 1:
            raise ValueError(
                'all lots in a dye cycle must share a greige, style, and '
                'color'
            )

    @property
    def greige(self) -> str:
        return self.lots[0].greige

    @property
    def style(self) -> str:
        return self.lots[0].fabric.style

    @property
    def color(self) -> 'Color':
        return self.lots[0].fabric.color


@dataclass(frozen=True, eq=False)
class EmptyCycle(Activity):

    color: 'Color'


@dataclass(frozen=True, eq=False)
class StripCycle(Activity):
    pass
