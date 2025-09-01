#!/usr/bin/env python

import datetime as dt

from swmtplanner import excel
from swmtplanner.support import Quantity
from swmtplanner.support.grouped import Grouped
from swmtplanner.items import greige, GreigeStyle
from swmtplanner.materials import RawMat, RawMatView, ARRIVED

excel.init()
greige.translate.init()
greige.init()

class GreigeRoll(RawMat[str]):

    def __init__(self, id: str, item: GreigeStyle, lbs: float):
        super().__init__('GreigeRoll', id, GRollView(self), item,
                         ARRIVED, dt.datetime.fromtimestamp(0), Quantity(lbs=lbs))
        
    @property
    def size(self):
        lbs = self.qty.lbs
        if self.item.load_rng.is_above(lbs):
            return 'PARTIAL'
        if self.item.load_rng.contains(lbs):
            return 'HALF'
        if self.item.roll_rng.is_above(lbs):
            return 'SMALL'
        if self.item.roll_rng.contains(lbs):
            return 'NORMAL'
        return 'LARGE'

class GRollView(RawMatView[str], attrs=('size',)):

    def __init__(self, link: GreigeRoll):
        super().__init__(link)

class PAInv(Grouped[str, GreigeStyle]):

    def __init__(self):
        super().__init__('item', 'size', 'id')

def main():
    dirpath = '/Users/lamanwyner/Desktop/Shawmut Projects/Scheduling'
    info_df = excel.load_df('pa_inventory', dirpath)

    inv = PAInv()
    for i in info_df.index:
        roll_id = info_df.loc[i, 'Roll']

        inv_name = info_df.loc[i, 'Item']
        plan_name = greige.translate.translate_name(inv_name)
        if plan_name is None: continue

        grg = greige.get_style(plan_name)
        if grg is None: continue

        roll = GreigeRoll(roll_id, grg, info_df.loc[i, 'Pounds'])
        inv.add(roll)

    print(inv)

if __name__ == '__main__':
    main()