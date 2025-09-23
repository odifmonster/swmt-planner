#!/usr/bin/env python

import math, datetime as dt

from swmtplanner.support import Quantity
from swmtplanner.support.grouped import Grouped
from swmtplanner.swmttypes.products import FabricItem
from swmtplanner.swmttypes.demand import OrderKind, Order, OrderView, Req

class FabOrder(Order[str, FabricItem]):

    def __init__(self, id, item, req, pnum, hard_qty, hard_date,
                 soft_qty, soft_date, safety_qty):
        super().__init__(id, item, req, pnum, hard_qty, hard_date,
                         soft_qty, soft_date, safety_qty)
        self._view = FabOrderView(self)

    def _get_days_key(self, tdelta: dt.timedelta, days_map: dict[int, float]):
        days_keys = sorted(days_map.keys())
        tdays = tdelta.total_seconds() / (3600 * 24)
        for days in days_keys:
            if tdays < days:
                return days
        return -1

    @property
    def greige(self):
        return self.item.greige
    
    @property
    def color(self):
        return self.item.color
    
    def late_cost(self, kind: OrderKind):
        if kind == OrderKind.SAFETY:
            return 0
        
        table = self.late(kind)
        if not table:
            return 0
        
        if kind == OrderKind.HARD:
            bumps = {2: 1000, 3: 1500, 4: 2500, 8: 10000}
            scales = {2: .01, 3: .015, 4: .025, 8: .5, 9: 1}
        else:
            bumps = {2: 100, 3: 250, 4: 500, 5: 1000}
            scales = {2: .001, 3: .0025, 4: .005, 5: .01}
        
        last_delta = table[-1][0]
        max_late_days = last_delta.total_seconds() / (3600 * 24)
        bump_key = self._get_days_key(last_delta, bumps)
        if bump_key < 0:
            if kind == OrderKind.HARD:
                cost = 10000 * 2 ** (math.ceil(max_late_days) - 8)
            else:
                cost = bumps[5]
        else:
            cost = bumps[bump_key]
        
        for tdelta, qty in table:
            late_days = tdelta.total_seconds() / (3600 * 24)
            scale_key = self._get_days_key(tdelta, scales)
            if scale_key < 0:
                if kind == OrderKind.HARD:
                    scale = 1 * 2 ** (math.ceil(late_days) - 9)
                else:
                    scale = scales[5]
            else:
                scale = scales[scale_key]
            cost += qty.yds * scale
        
        return cost
    
class FabOrderView(OrderView[str, FabricItem], funcs=('late_cost',)):

    @property
    def greige(self):
        return self.item.greige
    
    @property
    def color(self):
        return self.item.color

class FabReq(Req[FabricItem]):

    def excess_inv(self, by_date: dt.datetime):
        tgt_idx, tgt_order = -1, None
        for i, oview in enumerate(self.orders):
            oview: FabOrderView
            if oview.soft_date >= by_date:
                tgt_idx = i
                tgt_order = oview
                break
        tgt_idx = len(self.orders) - 1
        tgt_order = self.orders[-1]

        init_qty = tgt_order.remaining(OrderKind.SAFETY, by=dt.datetime.fromtimestamp(1))
        init_yds = init_qty.cumulative.yds
        rem = tgt_order.remaining(OrderKind.SAFETY, by=tgt_order.soft_date)
        if rem.cumulative.yds > 0:
            return 0
        
        if tgt_idx == len(self.orders) - 1:
            return rem.cumulative.yds * 0.04
        
        end_date = None
        for oview in self.orders[tgt_idx+1:]:
            order_qty = oview.remaining(OrderKind.SAFETY, by=dt.datetime.fromtimestamp(1))
            if order_qty.cumulative.yds - init_yds >= rem.cumulative.yds:
                end_date = oview.soft_date
                break
        
        if end_date is None:
            return rem.cumulative.yds * 0.04
        nweeks = (end_date - by_date).total_seconds() / (3600 * 24 * 7)
        return rem.cumulative.yds * 0.01 * nweeks
    
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