#!/usr/bin/env python

from swmtplanner.support import SwmtBase, HasID

_CTR = 0

class RMAlloc[T](SwmtBase, HasID[int], read_only=('id','raw_mat_id','qty','avail_date')):

    def __init__(self, raw_mat_id, avail_date, qty):
        globals()['_CTR'] += 1
        SwmtBase.__init__(self, _id=globals()['_CTR'], _raw_mat_id=raw_mat_id,
                          _qty=qty, _avail_date=avail_date)
        
    def __str__(self):
        return f'{self.prefix}(source={self.raw_mat_id}, qty={str(self.qty)})'
        
    @property
    def prefix(self):
        return 'RMAlloc'