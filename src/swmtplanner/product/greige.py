#!/usr/bin/env python

from typing import TYPE_CHECKING

from .product import Product
from .beamset import BeamSet

if TYPE_CHECKING:
    from collections.abc import Mapping


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
