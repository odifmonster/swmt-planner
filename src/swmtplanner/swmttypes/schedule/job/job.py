#!/usr/bin/env python

from swmtplanner.support import SwmtBase, HasID
from swmtplanner.swmttypes.product import *

_CTR = 0

class Job(SwmtBase, HasID[str],
          read_only=('id','item','req','start','end','lbs_used_top',
                     'lbs_used_btm','lbs_prod','changes','run_outs')):
    
    def __init__(self, item, req, start, end, lbs, changes, run_outs):
        globals()['_CTR'] += 1
        SwmtBase.__init__(self, _id=f'JOB{globals()['_CTR']:05}', _item=item,
                          _req=req, _start=start, _end=end, _lbs_used_top=lbs * item.top_pct,
                          _lbs_used_btm=lbs * item.btm_pct, _changes=tuple(changes),
                          _run_outs=tuple(run_outs))
    
    @property
    def prefix(self):
        return 'Job'