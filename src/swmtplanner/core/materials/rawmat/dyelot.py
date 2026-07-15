#!/usr/bin/env python

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from collections.abc import Iterator
    from .greigeroll import GreigeRoll
    from ...product.fabric import Fabric


class DyeLot:

    def __init__(self, rolls: 'list[GreigeRoll]'):
        self._rolls = {}
        self._greige = None
        self._plant = None
        self._fabric = None
        for roll in rolls:
            self.add(roll)

    @property
    def greige(self) -> 'str | None':
        return self._greige

    @property
    def plant(self) -> 'str | None':
        return self._plant

    @property
    def fabric(self) -> 'Fabric | None':
        return self._fabric

    @fabric.setter
    def fabric(self, fabric: 'Fabric | None') -> None:
        if (fabric is not None and self._greige is not None
                and fabric.greige != self._greige):
            raise ValueError("fabric does not use this lot's greige")
        self._fabric = fabric

    @property
    def avail_date(self) -> 'datetime | None':
        if not self._rolls:
            return None
        return max(roll.avail_date for roll in self._rolls.values())

    @property
    def total_lbs(self) -> float:
        return sum(roll.qty for roll in self._rolls.values())

    @property
    def total_yds(self) -> 'float | None':
        if self._fabric is None:
            return None
        return self.total_lbs * self._fabric.yds_per_lb

    @property
    def n_ports(self) -> int:
        return sum(roll.n_ports for roll in self._rolls.values())

    @property
    def avg_port_wt(self) -> float:
        n = self.n_ports
        return self.total_lbs / n if n else 0

    def add(self, roll: 'GreigeRoll') -> None:
        if not self._rolls:
            if self._fabric is not None and roll.sku != self._fabric.greige:
                raise ValueError('roll greige does not match the assigned fabric')
            self._greige = roll.sku
            self._plant = roll.plant
        elif roll.sku != self._greige or roll.plant != self._plant:
            raise ValueError(
                'all rolls in a dye lot must share a greige and a plant')
        self._rolls[roll.id] = roll

    def remove(self, id: str) -> 'GreigeRoll':
        roll = self._rolls.pop(id)
        if not self._rolls:
            self._greige = None
            self._plant = None
        return roll

    def __iter__(self) -> 'Iterator[GreigeRoll]':
        return iter(self._rolls.values())
