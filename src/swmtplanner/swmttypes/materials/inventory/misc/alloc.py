#!/usr/bin/env python

from swmtplanner.support import SwmtBase, HasID

_CTR = 0

class Alloc(SwmtBase, HasID[int],
            read_only=('id','prod','mat_id','qty')):
    
    def __init__(self, prod, mat_id, qty):
        globals()['_CTR'] += 1
        SwmtBase.__init__(self, _id=globals()['_CTR'], _prod=prod,
                          _mat_id=mat_id, _qty=qty)
    
    @property
    def prefix(self):
        return 'Alloc'