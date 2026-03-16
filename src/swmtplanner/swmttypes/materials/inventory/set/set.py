#!/usr/bin/env python

from swmtplanner.support import SwmtBase, HasID
from swmtplanner.swmttypes.materials.inventory import Alloc

class Set(SwmtBase, HasID[str],
          read_only=('id','beamset'),
          priv=('init_lbs','cur_lbs','allocs','temp_allocs','snapshot')):
    
    def __init__(self, bid, bset, lbs):
        SwmtBase.__init__(self, _id=bid, _beamset=bset, _init_lbs=lbs,
                          _cur_lbs=lbs, _allocs=set(), _temp_allocs={},
                          _snapshot=None)
    
    @property
    def snapshot(self):
        return self._snapshot
    @snapshot.setter
    def snapshot(self, new):
        if not (self._snapshot is None or new is None):
            raise RuntimeError('Cannot apply two snapshots at once')
        self._snapshot = new

    @property
    def lbs(self):
        if self.snapshot is None:
            return self._cur_lbs
        return self._cur_lbs - sum(a.qty for a in self._temp_allocs[self.snapshot])
    
    def _update_lbs(self):
        self._cur_lbs = self._init_lbs - sum(map(lambda a: a.qty, self._allocs))
    
    def allocate(self, lbs, snapshot = None):
        temp_lbs = self._cur_lbs
        if snapshot is not None:
            if snapshot not in self._temp_allocs:
                self._temp_allocs[snapshot] = set()
            temp_lbs -= sum(map(lambda a: a.qty, self._temp_allocs[snapshot]))
        if temp_lbs + 1 < lbs:
            raise ValueError(f'{lbs:.2f} lbs exceeds remaining quantity in beamset ({temp_lbs:.2f})')
        
        ret = Alloc(self.beamset, self.id, lbs)
        if snapshot is None:
            self._allocs.add(ret)
            self._update_lbs()
        else:
            self._temp_allocs[snapshot].add(ret)
    
    def deallocate(self, piece, snapshot = None):
        if snapshot is None:
            self._allocs.remove(piece)
            self._update_lbs()
        else:
            self._temp_allocs[snapshot].remove(piece)
    
    def apply_snap(self, snapshot = None):
        if snapshot and snapshot in self._temp_allocs:
            for x in self._temp_allocs[snapshot]:
                self._allocs.add(x)
            self._update_lbs()
        self._temp_allocs.clear()