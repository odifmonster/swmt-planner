#!/usr/bin/env python

from swmtplanner.support import Quantity
from swmtplanner.support.grouped import Grouped
from swmtplanner.swmttypes.products import FabricItem
from swmtplanner.swmttypes.demand import OrderKind, Order, OrderView

class FabOrder(Order[str, FabricItem]):

    def __init__(self, id, item, req, pnum, hard_qty, hard_date,
                 soft_qty, soft_date, safety_qty):
        super().__init__(id, item, req, pnum, hard_qty, hard_date,
                         soft_qty, soft_date, safety_qty)
        self._view = FabOrderView(self)

    @property
    def greige(self):
        return self.item.greige
    
    @property
    def color(self):
        return self.item.color
    
class FabOrderView(OrderView[str, FabricItem]):

    @property
    def greige(self):
        return self.item.greige
    
    @property
    def color(self):
        return self.item.color
    
class FabDemand(Grouped[str, int]):

    def __init__(self):
        super().__init__('greige','color','pnum','item','id')

    def get_matches(self, order: FabOrder):
        if order.greige not in self \
            or order.color not in self[order.greige, order.color]:
            return
        
        zero = Quantity(pcs=0, yds=0, lbs=0)

        for view in self[order.greige, order.color].itervalues():
            opt: FabOrderView = view
            if opt.remaining(OrderKind.SOFT).cumulative <= zero: continue
            if opt.item == order.item: continue

            comb_qty = order.remaining(OrderKind.SOFT).cumulative + \
                opt.remaining(OrderKind.SOFT).cumulative
            port_avg = order.greige.load_rng.average()
            est_ports = comb_qty.lbs / port_avg
            if est_ports > 8: continue
            yield opt