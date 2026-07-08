#!/usr/bin/env python

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from collections.abc import Iterator
    from .greigeroll import GreigeRoll


class DyeLot:

    def __init__(self, rolls: 'list[GreigeRoll]'):
        self._rolls = {}
        self._sku = None
        self._plant = None
        for roll in rolls:
            self.add(roll)

    @property
    def sku(self) -> 'str | None':
        return self._sku

    @property
    def plant(self) -> 'str | None':
        return self._plant

    @property
    def avail_date(self) -> 'datetime | None':
        if not self._rolls:
            return None
        return max(roll.avail_date for roll in self._rolls.values())

    @property
    def total_lbs(self) -> float:
        return sum(roll.qty for roll in self._rolls.values())

    @property
    def n_ports(self) -> int:
        return sum(roll.n_ports for roll in self._rolls.values())

    @property
    def avg_port_wt(self) -> float:
        n = self.n_ports
        return self.total_lbs / n if n else 0

    def add(self, roll: 'GreigeRoll') -> None:
        if not self._rolls:
            self._sku = roll.sku
            self._plant = roll.plant
        elif roll.sku != self._sku or roll.plant != self._plant:
            raise ValueError('all rolls in a dye lot must share a sku and a plant')
        self._rolls[roll.id] = roll

    def remove(self, id: str) -> 'GreigeRoll':
        roll = self._rolls.pop(id)
        if not self._rolls:
            self._sku = None
            self._plant = None
        return roll

    def __iter__(self) -> 'Iterator[GreigeRoll]':
        return iter(self._rolls.values())
