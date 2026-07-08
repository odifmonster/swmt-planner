#!/usr/bin/env python

from math import isclose
from typing import TYPE_CHECKING

from .rawmat import RawMat

if TYPE_CHECKING:
    from datetime import datetime
    from swmtplanner.core.product.greige import Greige


SMALL = 0
STANDARD = 1
LARGE = 2

DEFAULT_ROLL_WT = 700
SINGLE_PORT_MAX = 400
STD_SIZE_TOL = 25


class GreigeRoll(RawMat):

    def __init__(self, id: str, sku: str, avail_date: 'datetime', qty: float,
                 plant: str, variant: str, yarn_merge: int,
                 greige: 'Greige | None'):
        super().__init__(id, sku, avail_date, qty, 'lbs')
        self._plant = plant
        self._variant = variant
        self._yarn_merge = yarn_merge
        self._greige = greige

    @property
    def plant(self) -> str:
        return self._plant

    @property
    def variant(self) -> str:
        return self._variant

    @property
    def yarn_merge(self) -> int:
        return self._yarn_merge

    @property
    def greige(self) -> 'Greige | None':
        return self._greige

    @property
    def single_target(self) -> float:
        target = self._greige.tgt_wt if self._greige is not None else DEFAULT_ROLL_WT
        return target if target <= SINGLE_PORT_MAX else target / 2

    @property
    def n_ports(self) -> int:
        return max(1, round(self._qty / self.single_target))

    @property
    def avg_port_wt(self) -> float:
        return self._qty / self.n_ports

    @property
    def size(self) -> int:
        single_target = self.single_target
        avg = self.avg_port_wt
        if avg < single_target - STD_SIZE_TOL:
            return SMALL
        if avg <= single_target + STD_SIZE_TOL:
            return STANDARD
        return LARGE

    def split(self, lbs1: float, lbs2: float) -> 'tuple[GreigeRoll, GreigeRoll]':
        if not isclose(lbs1 + lbs2, self._qty):
            raise ValueError(
                f'split weights ({lbs1} + {lbs2}) must sum to the roll weight '
                f'({self._qty})'
            )
        first = GreigeRoll(self._id + 'A', self._sku, self._avail_date, lbs1,
                           self._plant, self._variant, self._yarn_merge,
                           self._greige)
        second = GreigeRoll(self._id + 'B', self._sku, self._avail_date, lbs2,
                            self._plant, self._variant, self._yarn_merge,
                            self._greige)
        return first, second

    def combine(self, roll: 'GreigeRoll') -> 'GreigeRoll':
        if roll.sku != self._sku or roll.plant != self._plant:
            raise ValueError('can only combine rolls with the same sku and plant')
        variant = (self._variant if self._variant == roll.variant
                   else self._variant + '/' + roll.variant)
        yarn_merge = (self._yarn_merge if self._yarn_merge == roll.yarn_merge
                      else -1)
        return GreigeRoll(self._id + '/' + roll.id, self._sku,
                          max(self._avail_date, roll.avail_date),
                          self._qty + roll.qty, self._plant, variant, yarn_merge,
                          self._greige)
