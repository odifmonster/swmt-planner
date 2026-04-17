#!/usr/bin/env python

from swmtplanner.support import SwmtBase, HasID

_CTR = 0

class BeamSet(SwmtBase, HasID[int],
              read_only=('id','name','denier'), priv=('init_lbs','used')):
    
    def __init__(self, name, lbs):
        globals()['_CTR'] += 1
        SwmtBase.__init__(self, _id=globals()['_CTR'], _name=name,
                          _denier=int(name[:2]), _init_lbs=lbs, _used=[])
    
    @property
    def prefix(self):
        return 'BeamSet'
    
    @property
    def lbs(self):
        return self._init_lbs - sum(map(lambda x: x[1], self._used))
    
    def rem_lbs_by(self, date):
        rem = self._init_lbs
        for usage, ts in self._used:
            if ts >= date: return rem
            rem -= usage
    
    def use(self, lbs, by):
        for i, pair in enumerate(self._used):
            cur_dt = pair[1]
            if cur_dt > by:
                self._used.insert(i, (lbs, by))