#!/usr/bin/env python

from typing import NewType

from swmtplanner.support import Quantity, setter_like
from swmtplanner.support.grouped import Data, DataView
from .rmalloc import RMAlloc

Status = NewType('Status', str)
ARRIVED = Status('ARRIVED')
EN_ROUTE = Status('EN_ROUTE')

class RawMat[T](Data[T], mut_in_group=False):

    def __init_subclass__(cls, read_only = tuple(), priv = tuple()):
        super().__init_subclass__(mut_in_group=False,
                                  read_only=('item','status','receipt_date')+read_only,
                                  priv=('cur_qty','allocs','temp_allocs')+priv)
    
    def __init__(self, prefix, id, view, item, status, receipt_date, qty,
                 **kwargs):
        self.snapshot = None
        super().__init__(prefix, id, view, _item=item, _status=status,
                         _receipt_date=receipt_date, _cur_qty=qty, _allocs=set(),
                         _temp_allocs={}, **kwargs)
        
    @property
    def qty(self) -> Quantity:
        if self.snapshot is None or self.snapshot not in self._temp_allocs:
            return self._cur_qty
        return self._cur_qty - sum(map(lambda al: al.qty,
                                       self._temp_allocs[self.snapshot]))
    
    @setter_like
    def allocate(self, amount: Quantity, snapshot = None):
        add_qty = Quantity(yds=2.5, lbs=1)
        if snapshot is None:
            if self._cur_qty < amount + add_qty:
                raise ValueError(f'{str(amount)} exceeds remaining quantity of ' + \
                                 f'resource {repr(self)} ({str(self._cur_qty)})')
            self._cur_qty -= amount
            piece = RMAlloc[T](self, amount)
            self._allocs.add(piece)
        else:
            if snapshot not in self._temp_allocs:
                self._temp_allocs[snapshot] = set()
            prev_snap = self.snapshot
            self.snapshot = snapshot
            if self.qty < amount + add_qty:
                raise ValueError(f'{str(amount)} exceeds remaining quantity of ' + \
                                 f'resource {repr(self)} on {repr(snapshot)} ' + \
                                 f' ({str(self.qty)})')
            self.snapshot = prev_snap
            piece = RMAlloc[T](self, amount)
            self._temp_allocs[snapshot].add(piece)
        return piece

    @setter_like
    def deallocate(self, piece: RMAlloc[T], snapshot = None):
        if snapshot is None:
            self._allocs.remove(piece)
            self._cur_qty += piece.qty
        else:
            if snapshot not in self._temp_allocs:
                raise KeyError(f'No pieces of {repr(self)} allocated on ' + \
                               repr(snapshot))
            self._temp_allocs[snapshot].remove(piece)

class RawMatView[T](DataView[T]):
    
    def __init_subclass__(cls, dunders = tuple(), attrs = tuple(),
                          funcs = tuple(), read_only = tuple(), priv = tuple()):
        super().__init_subclass__(dunders=dunders,
                                  attrs=('item','status','receipt_date','qty')+attrs,
                                  funcs=funcs, read_only=read_only, priv=priv)