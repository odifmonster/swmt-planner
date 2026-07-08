#!/usr/bin/env python

from typing import TYPE_CHECKING

from swmtplanner.support import mk_counter
from ..rawmat import GreigeRoll, STANDARD
from .inventory import Inventory
from .group import GreigeGroup, MAX_TRIM_LBS
from .condition import NotExactly

if TYPE_CHECKING:
    from datetime import datetime
    from swmtplanner.core.product.greige import Greige


PLANT_PREFIXES = {'Fairystone': 'FS', 'Whiteville': 'WV'}


class GreigeInv(Inventory[GreigeRoll]):

    def __init__(self):
        super().__init__(grouped=['size', 'plant', 'variant', 'yarn_merge'],
                         sorted=['qty', 'avail_date'])
        self._greige_group = GreigeGroup()
        self._groups['sku'] = self._greige_group
        self._counter = mk_counter()

    # -- dye-lot operations (delegated to the sku-keyed GreigeGroup) --

    def prepare_dye_pool(self) -> None:
        self._greige_group.prepare_dye_pool()

    def dye_lots(self, style: str) -> 'list[set[GreigeRoll]]':
        return self._greige_group.dye_lots(style)

    def has_cached_lots(self, style: str) -> bool:
        return self._greige_group.has_cached_lots(style)

    # -- roll transformation --

    def transform_rolls(self) -> None:
        for sku in list(self._greige_group.skus):
            self._combine_pass(sku, trim_allowed=False)
        for sku in list(self._greige_group.skus):
            self._combine_pass(sku, trim_allowed=True)

    def _combine_pass(self, sku: str, trim_allowed: bool) -> None:
        while self._try_one_combine(sku, trim_allowed):
            pass

    def _try_one_combine(self, sku: str, trim_allowed: bool) -> bool:
        rolls = self.select_where(sku=sku, size=NotExactly(STANDARD))
        for i in range(len(rolls)):
            for j in range(i + 1, len(rolls)):
                a, b = rolls[i], rolls[j]
                if a.plant != b.plant:
                    continue
                result = self._attempt(a, b, trim_allowed)
                if result is not None:
                    self.remove(a.id)
                    self.remove(b.id)
                    self.add(result)
                    return True
        return False

    def _attempt(self, a: GreigeRoll, b: GreigeRoll,
                 trim_allowed: bool) -> 'GreigeRoll | None':
        combined = a.combine(b)
        if combined.size == STANDARD:
            return combined
        if not trim_allowed:
            return None
        # combining overshoots; trim the larger roll to reach standard
        t_exact = combined.qty - combined.n_ports * combined.single_target
        if 0 < t_exact <= MAX_TRIM_LBS:
            trim = t_exact
        elif t_exact > MAX_TRIM_LBS:
            trim = MAX_TRIM_LBS
        else:
            return None
        larger, smaller = (a, b) if a.qty >= b.qty else (b, a)
        if trim >= larger.qty:
            return None
        kept, _waste = larger.split(larger.qty - trim, trim)
        result = kept.combine(smaller)
        return result if result.size == STANDARD else None

    # -- roll creation --

    def create_roll(self, sku: str, avail_date: 'datetime', qty: float,
                    plant: str, greige: 'Greige | None') -> GreigeRoll:
        id = f'{PLANT_PREFIXES[plant]}NEW-{self._counter()}'
        return GreigeRoll(id=id, sku=sku, avail_date=avail_date, qty=qty,
                          plant=plant, variant=sku, yarn_merge=-1, greige=greige)
