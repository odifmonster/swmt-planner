#!/usr/bin/env python

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...product import Fabric
from ..rawmat import GreigeRoll

if TYPE_CHECKING:
    from datetime import date


@dataclass(frozen=True)
class DyeLot:
    fabric: Fabric
    rolls: tuple[GreigeRoll, ...]

    @property
    def avail_date(self) -> 'date | None':
        dates = [r.avail_date for r in self.rolls if r.avail_date is not None]
        return max(dates) if dates else None
