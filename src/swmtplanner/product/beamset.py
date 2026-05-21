#!/usr/bin/env python

import re

from .product import Product


_BEAMSET_SKU = re.compile(r'^(\d+)D (.+) (\d+)X(\d+)( S/L)?$')


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
