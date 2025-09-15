#!/usr/bin/env python

from typing import NamedTuple
from enum import Enum, auto
import datetime as dt

from swmtplanner.support import Quantity, SwmtBase, HasID, setter_like
from swmtplanner.support.grouped import Data, DataView
from swmtplanner.swmttypes.products import GreigeStyle
from swmtplanner.swmttypes.materials import Status

_CTR = 0

class KnitPlant(Enum):
    WVILLE = auto()
    INFINITE = auto()
    EITHER = auto()

class GrgRollSize(Enum):
    ONE_PORT = auto()
    TWO_PORT = auto()
    PARTIAL = auto()
    ODD = auto()

class GRollAlloc(SwmtBase, HasID[int],
                 read_only=('id','roll_id','status','avail_date','weight')):
    
    def __init__(self, roll_id, status, avail_date, weight):
        globals()['_CTR'] += 1
        SwmtBase.__init__(self, _id=globals()['_CTR'], _roll_id=roll_id,
                        _status=status, _avail_date=avail_date, _weight=weight)
        
    @property
    def prefix(self):
        return 'GRollAlloc'
    
class PortLoad(NamedTuple):
    rolls: tuple[GRollAlloc, ...]
    status: Status
    avail_date: dt.datetime
    weight: Quantity

class GrgRoll(Data[str], mut_in_group=False,
              read_only=('item','plant','status','received'),
              priv=('cur_wt','allocs','temp_allocs')):
    
    def __init__(self, id, item, plant, status, received, lbs):
        self.snapshot = None
        super().__init__('GrgRoll', id, GrgRollView(self), _item=item,
                         _plant=plant, _status=status, _received=received,
                         _cur_wt=Quantity(lbs=lbs), _allocs=set(),
                         _temp_allocs={})
        
    @property
    def weight(self) -> Quantity:
        if self.snapshot is None or self.snapshot not in self._temp_allocs:
            return self._cur_wt
        x = self._temp_allocs[self.snapshot]
        temp_used = sum(map(lambda a: a.weight, x), start=Quantity(lbs=0))
        return self._cur_wt - temp_used
    
    @property
    def size(self):
        grg: GreigeStyle = self.item
        lbs = self.weight.lbs

        if grg.load_rng.is_above(lbs):
            return GrgRollSize.PARTIAL
        if grg.load_rng.contains(lbs):
            return GrgRollSize.ONE_PORT
        
        if grg.roll_rng.minval > grg.load_rng.minval and grg.roll_rng.contains(lbs):
            return GrgRollSize.TWO_PORT
        
        return GrgRollSize.ODD
    
    @setter_like
    def allocate(self, lbs, snapshot = None):
        prev_snap = self.snapshot
        self.snapshot = snapshot
        max_lbs = self.weight.lbs
        self.snapshot = prev_snap

        if max_lbs + 1 < lbs:
            raise ValueError(f'{lbs:.2f} lbs exceeds remaining roll weight ' + \
                             f'({max_lbs:.2g} lbs)')
        
        ret = GRollAlloc(self.id, self.status, self.received, Quantity(lbs=lbs))
        if snapshot is None:
            self._cur_wt -= ret.weight
            self._allocs.add(ret)
        else:
            if snapshot not in self._temp_allocs:
                self._temp_allocs[snapshot] = set()
            self._temp_allocs[snapshot].add(ret)
        return ret
    
    @setter_like
    def deallocate(self, piece, snapshot = None):
        if snapshot is None:
            self._allocs.remove(piece)
            self._cur_wt += piece.weight
        else:
            self._temp_allocs[snapshot].remove(piece)

    @setter_like
    def apply_snap(self, snapshot = None):
        if snapshot and snapshot in self._temp_allocs:
            for piece in self._temp_allocs[snapshot]:
                self._allocs.add(piece)
                self._cur_wt -= piece.weight
        
        self._temp_allocs.clear()

class GrgRollView(DataView[str], attrs=('item','plant','status','received',
                                        'weight','size')):
    pass