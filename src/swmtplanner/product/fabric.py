#!/usr/bin/env python

import re
from typing import TYPE_CHECKING

from .product import Product

if TYPE_CHECKING:
    from collections.abc import Iterable


_FABRIC_SKU = re.compile(r'^FF (.+)-(\d{5})-([\d.]+)$')


class Fabric(Product):

    def __init__(
        self,
        sku: str,
        safety_tgt: float,
        greige_style: str,
        yld: float,
        color_shade: int,
        omits_port: bool,
        jets: 'Iterable[str]',
    ) -> None:
        m = _FABRIC_SKU.match(sku)
        if m is None:
            raise ValueError(f'invalid Fabric SKU: {sku!r}')
        super().__init__(sku, safety_tgt)
        self._style = m.group(1)
        self._dye_formula = m.group(2)
        self._width = float(m.group(3))
        self._greige_style = greige_style
        self._yld = yld
        self._color_shade = color_shade
        self._omits_port = omits_port
        self._jets = frozenset(jets)

    @property
    def style(self) -> str:
        return self._style

    @property
    def dye_formula(self) -> str:
        return self._dye_formula

    @property
    def width(self) -> float:
        return self._width

    @property
    def greige_style(self) -> str:
        return self._greige_style

    @property
    def yld(self) -> float:
        return self._yld

    @property
    def color_shade(self) -> int:
        return self._color_shade

    @property
    def omits_port(self) -> bool:
        return self._omits_port

    @property
    def jets(self) -> 'frozenset[str]':
        return self._jets

    def can_run_on_jet(self, jet_id: str) -> bool:
        return jet_id in self._jets
