#!/usr/bin/env python

import re
from typing import TYPE_CHECKING

from swmtplanner.support import HasID

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


_BEAMSET_SKU = re.compile(r'^(\d+)D (.+) (\d+)X(\d+)( S/L)?$')
_FABRIC_SKU = re.compile(r'^FF (.+)-(\d{5})-([\d.]+)$')


class Product(HasID[str]):

    def __init__(self, sku: str, safety_tgt: float) -> None:
        self._sku = sku
        self._safety_tgt = safety_tgt

    @property
    def id(self) -> str:
        return self._sku

    @property
    def safety_tgt(self) -> float:
        return self._safety_tgt


class BeamSet(Product):

    def __init__(self, sku: str, safety_tgt: float) -> None:
        m = _BEAMSET_SKU.match(sku)
        if m is None:
            raise ValueError(f'invalid BeamSet SKU: {sku!r}')
        super().__init__(sku, safety_tgt)
        self._denier = int(m.group(1))
        self._yarn_desc = m.group(2)
        self._end_count = int(m.group(3))
        self._beam_count = int(m.group(4))
        self._is_split = m.group(5) is not None

    @property
    def denier(self) -> int:
        return self._denier

    @property
    def yarn_desc(self) -> str:
        return self._yarn_desc

    @property
    def end_count(self) -> int:
        return self._end_count

    @property
    def beam_count(self) -> int:
        return self._beam_count

    @property
    def is_split(self) -> bool:
        return self._is_split


class Greige(Product):

    def __init__(
        self,
        sku: str,
        safety_tgt: float,
        family: str,
        gauge: int,
        top_bar: BeamSet,
        top_bar_pct: float,
        bottom_bar: BeamSet,
        bottom_bar_pct: float,
        port_load_tgt: float,
        standard_size: int,
        machine_rates: 'Mapping[str, float]',
    ) -> None:
        super().__init__(sku, safety_tgt)
        self._family = family
        self._gauge = gauge
        self._top_bar = top_bar
        self._top_bar_pct = top_bar_pct
        self._bottom_bar = bottom_bar
        self._bottom_bar_pct = bottom_bar_pct
        self._port_load_tgt = port_load_tgt
        self._standard_size = standard_size
        self._machine_rates = dict(machine_rates)

    @property
    def family(self) -> str:
        return self._family

    @property
    def gauge(self) -> int:
        return self._gauge

    @property
    def top_bar(self) -> BeamSet:
        return self._top_bar

    @property
    def top_bar_pct(self) -> float:
        return self._top_bar_pct

    @property
    def bottom_bar(self) -> BeamSet:
        return self._bottom_bar

    @property
    def bottom_bar_pct(self) -> float:
        return self._bottom_bar_pct

    @property
    def port_load_tgt(self) -> float:
        return self._port_load_tgt

    @property
    def standard_size(self) -> int:
        return self._standard_size

    def can_run_on_machine(self, mchn_id: str) -> bool:
        return mchn_id in self._machine_rates

    def rate_on_machine(self, mchn_id: str) -> float:
        return self._machine_rates[mchn_id]


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
