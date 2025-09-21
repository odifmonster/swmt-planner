#!/usr/bin/env python

from functools import reduce
import datetime as dt

from swmtplanner.support import SwmtBase, Viewer, Quantity
from swmtplanner.swmttypes.products import GreigeStyle, FabricItem
from swmtplanner.swmttypes.materials import Status, Lot, LotView

_CTR = 0

def _reduce_status(prev: Status, cur: Status):
    if prev == Status.NEW or cur == Status.NEW:
        return Status.NEW
    if prev == Status.PLANNED or cur == Status.PLANNED:
        return Status.PLANNED
    return Status.ARRIVED

class DyeLot(SwmtBase, Lot[str, GreigeStyle, FabricItem],
             read_only=('id','rawmat','product','ports','status','received',
                        'cycle_time','fin_time'),
             priv=('start','view')):
    
    @classmethod
    def from_adaptive(cls, id, item, start, end):
        return cls(id, item.greige, item, [], Status.ARRIVED,
                   start, None, end - start, dt.timedelta(seconds=0))
    
    @classmethod
    def new_lot(cls, item, ports):
        globals()['_CTR'] += 1
        status = reduce(_reduce_status, map(lambda p: p.status, ports))
        received = max(map(lambda p: p.avail_date, ports))
        return cls(f'LOT{globals()['_CTR']:05}', item.greige, item, ports, status,
                   received, None, item.cycle_time, dt.timedelta(hours=16))
    
    @classmethod
    def new_strip(cls, strip):
        globals()['_CTR'] += 1
        return cls(f'{strip.id}{globals()['_CTR']:05}', strip.greige,
                   strip, [], Status.ARRIVED, dt.datetime.fromtimestamp(0),
                   None, strip.cycle_time, dt.timedelta(0))
    
    def __init__(self, id, rawmat, product, ports, status, received,
                 start, cycle_time, fin_time):
        SwmtBase.__init__(self, _id=id, _rawmat=rawmat, _product=product,
                          _ports=tuple(ports), _status=status, _received=received,
                          _start=start, _cycle_time=cycle_time, _fin_time=fin_time)
        
    @property
    def prefix(self):
        return 'DyeLot'

    @property
    def color(self):
        return self.product.color
    
    @property
    def shade(self):
        return self.product.color.shade
    
    @property
    def qty(self):
        total_lbs = sum(map(lambda p: p.weight.lbs, self.ports))
        return Quantity(yds=total_lbs*self.product.yld, lbs=total_lbs)
    
    @property
    def start(self):
        return self._start
    @start.setter
    def start(self, new):
        if new is not None and self._start is not None:
            raise AttributeError('Cannot activate more than one Job on the same DyeLot')
        self._start = new
        
        if new is None:
            set_date = dt.datetime.fromtimestamp(0)
        else:
            set_date = new

        for port in self.ports:
            for al in port.rolls:
                al._use_date = set_date

    @property
    def fin(self):
        if self._start is None:
            return None
        return self._start + self.cycle_time + self._fin_time
    
    def view(self):
        return self._view

class DyeLotView(Viewer[DyeLot], LotView[str, GreigeStyle, FabricItem],
                 dunders=('hash','eq','repr'),
                 attrs=('prefix','id','rawmat','product','color','shade',
                        'ports','status','received','cycle_time','fin_time',
                        'start','fin')):
    pass