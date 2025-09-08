#!/usr/bin/env python

from typing import NamedTuple
from enum import Enum, auto

from swmtplanner.support import Quantity
from swmtplanner.support.grouped import Data, DataView

class OrderKind(Enum):
    HARD = auto()
    SOFT = auto()
    SAFETY = auto()

class OrderQty(NamedTuple):
    normal: Quantity
    cumulative: Quantity

class Order[T, U](Data[T], mut_in_group=True,
                  read_only=('item','hard_date','soft_date'),
                  priv=('qty_map','req')):
    
    def __init__(self, id, item, req, hard_qty, hard_date, soft_qty, soft_date,
                 safety_qty):
        super().__init__('Order', id, OrderView[T, U](self), _item=item,
                         _hard_date=hard_date, _soft_date=soft_date, _req=req,
                         _qty_map={
                             OrderKind.HARD: hard_qty,
                             OrderKind.SOFT: soft_qty,
                             OrderKind.SAFETY: safety_qty
                         })
        
    def remaining(self, kind: OrderKind, by = None):
        qty: OrderQty = self._qty_map[kind]
        total_prod = self._req.total_prod(by=by)
        rem_cum = qty.cumulative - total_prod
        return OrderQty(min(qty.normal, rem_cum), rem_cum)
    
    def late(self, kind: OrderKind):
        if kind == OrderKind.SAFETY:
            raise ValueError('Safety stock replenishment orders have no due date')
        
        zero = Quantity(pcs=0, yds=0, lbs=0)
        
        due_date = self.hard_date if kind == OrderKind.HARD else self.soft_date
        total = self._req.total_prod(by=due_date)
        lots = sorted(self._req._lots,
                      lambda l: l.fin is not None and l.fin > due_date)
        
        table = []
        init_qty: OrderQty = self._qty_map[kind]
        if kind == OrderKind.SOFT:
            hard_late = max(zero, self.remaining(OrderKind.HARD,
                                                 by=self.soft_date).cumulative)
            init_qty = OrderQty(init_qty.normal, init_qty.cumulative - hard_late)

        for lot in lots:
            rem_cum = min(init_qty.cumulative - total, init_qty.normal)
            if rem_cum < zero: break
            
            if rem_cum < lot.qty:
                late_qty = max(rem_cum, zero)
            else:
                late_qty = lot.qty

            if late_qty > 0:
                table.append((lot.fin - due_date, late_qty))
                total += lot.qty
        
        return table
    
    def assign(self, lot):
        self._req.assign(lot)

    def unassign(self, lot):
        self._req.unassign(lot)
            
class OrderView[T, U](DataView[T], attrs=('item','hard_date','soft_date'),
                      funcs=('late','remaining')):
    pass