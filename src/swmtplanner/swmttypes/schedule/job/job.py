#!/usr/bin/env python

from swmtplanner.support import SwmtBase, HasID
from swmtplanner.swmttypes.product import *

_CTR = 0

class Job(SwmtBase, HasID[str],
          read_only=('id','item','req','start','end','lbs_used_top',
                     'lbs_used_btm','lbs_prod'),
          priv=('stops',)):
    
    def __init__(self, item, start, end, lbs, stops, req=None):
        globals()['_CTR'] += 1
        SwmtBase.__init__(self, _id=f'JOB{globals()['_CTR']:05}', _item=item,
                          _req=req, _start=start, _end=end, _lbs_used_top=lbs * item.top_pct,
                          _lbs_used_btm=lbs * item.btm_pct, _lbs_prod=lbs, _stops=stops)
    
    @property
    def prefix(self):
        return 'Job'
    
    @property
    def stops(self):
        return tuple(self._stops)