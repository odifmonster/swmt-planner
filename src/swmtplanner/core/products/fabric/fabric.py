#!/usr/bin/env python

from dataclasses import dataclass

from ....support import HasID
from ..greige import Greige
from .dyeformula import DyeFormula


@dataclass(frozen=True, eq=False)
class Fabric(HasID[str]):
    id: str
    greige_style: Greige
    master_style: str
    color: DyeFormula
    width: float
    yld: float
    jets: tuple[str, ...]

    def can_run_on_jet(self, j_id: str) -> bool:
        return j_id in self.jets
