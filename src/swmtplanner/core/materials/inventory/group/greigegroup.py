#!/usr/bin/env python

from .group import ValGroup
from ...rawmat import GreigeRoll


MIN_PORT_LBS = 300
MAX_PORT_LBS = 400
PORT_EVEN_TOL = 10
MAX_TRIM_LBS = 30


class GreigeGroup(ValGroup[GreigeRoll]):

    def __init__(self):
        super().__init__('sku')
        self._lots = {}

    @property
    def skus(self) -> set[str]:
        return set(self._map.keys())

    def add(self, mat: GreigeRoll) -> None:
        super().add(mat)
        self._lots.pop(mat.sku, None)

    def remove(self, id: str | int, val) -> None:
        super().remove(id, val)
        self._lots.pop(val, None)

    def prepare_dye_pool(self) -> None:
        for sku, rolls in self._map.items():
            if sku not in self._lots:
                self._lots[sku] = self._compute_lots(rolls)

    def _compute_lots(self, rolls) -> list[set[GreigeRoll]]:
        eligible = sorted(
            (r for r in rolls if MIN_PORT_LBS <= r.avg_port_wt <= MAX_PORT_LBS),
            key=lambda r: r.avg_port_wt,
        )
        lots = []
        current = []
        for roll in eligible:
            if current and roll.avg_port_wt - current[0].avg_port_wt > PORT_EVEN_TOL:
                lots.append(set(current))
                current = [roll]
            else:
                current.append(roll)
        if current:
            lots.append(set(current))
        return lots

    def dye_lots(self, style: str) -> list[set[GreigeRoll]]:
        if style not in self._lots:
            raise KeyError(
                f'no cached dye lots for {style!r}; call prepare_dye_pool() first'
            )
        return self._lots[style]

    def has_cached_lots(self, style: str) -> bool:
        return style in self._lots
