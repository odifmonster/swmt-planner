#!/usr/bin/env python

from dataclasses import dataclass

from ....support import HasID
from .shade import Shade


@dataclass(frozen=True, eq=False)
class DyeFormula(HasID[int]):
    id: int
    name: str
    shade: Shade
