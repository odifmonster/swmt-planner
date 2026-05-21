#!/usr/bin/env python

from swmtplanner.support import HasID


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
