#!/usr/bin/env python

from swmtplanner.support import SwmtBase, Quantity
from .order import OrderKind, OrderQty, Order

class Req[T](SwmtBase, read_only=('item',), priv=('orders','lots')):

    def __init__(self, item):
        super().__init__(_item=item, _orders=[], _lots=[])

    @property
    def orders(self):
        return list(map(lambda o: o.view(), self._orders))
    
    @property
    def lots(self):
        return list(map(lambda l: l.view(), self._lots))
    
    def add_order(self, id, hard_qty, hard_date, soft_qty, soft_date, safety_qty):
        zero = Quantity(pcs=0, yds=0, lbs=0)
        hard_cum = zero
        soft_cum = zero
        safety_cum = zero

        if self._orders:
            prev_order: Order = self._orders[-1]
            hard_cum = prev_order._qty_map[OrderKind.HARD].cumulative
            soft_cum = prev_order._qty_map[OrderKind.SOFT].cumulative
            safety_cum = prev_order._qty_map[OrderKind.SAFETY].cumulative

        new_order = Order(id, self.item, self,
                          OrderQty(hard_qty, hard_qty+hard_cum), hard_date,
                          OrderQty(soft_qty, soft_qty+soft_cum), soft_date,
                          OrderQty(safety_qty, safety_qty+safety_cum))
        self._orders.append(new_order)
        return new_order

    def total_prod(self, by = None):
        total = Quantity(pcs=0, yds=0, lbs=0)

        for lot in self._lots:
            if lot.fin is None: continue
            if by is not None and lot.fin > by: continue
            total += lot.qty
        
        return total
    
    def assign(self, lot):
        if lot.product != self.item:
            raise ValueError(f'Cannot assign lot for {lot.product} to order for' + \
                             f' {self.item}')
        self._lots.append(lot)

    def unassign(self, lot):
        self._lots.remove(lot)