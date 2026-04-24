#!/usr/bin/env python

from collections import namedtuple

from swmtplanner.support import SwmtBase, HasID

_CTR = 0

_BeamUse = namedtuple('_BeamUse', ['item','mchn','bar','start','end'])

def _get_lbs_used(use: _BeamUse):
    hours = (use.end - use.start).total_seconds() / 3600
    pct = use.item.top_pct if use.bar == 'top' else use.item.btm_pct
    rate = use.item.get_rate_on(use.mchn) * pct
    return hours * rate

class BeamSet(SwmtBase, HasID[int],
              read_only=('id','name','denier'), priv=('init_lbs','usages')):
    
    def __init__(self, name, lbs):
        globals()['_CTR'] += 1
        SwmtBase.__init__(self, _id=globals()['_CTR'], _name=name,
                          _denier=int(name[:2]), _init_lbs=lbs, _usages=[])
    
    @property
    def prefix(self):
        return 'BeamSet'
    
    @property
    def lbs(self):
        return self._init_lbs - sum(map(_get_lbs_used, self._usages))
    
    def rem_lbs_by(self, date):
        rem = self._init_lbs
        for use in self._usages:
            if use.end >= date:
                new_use = _BeamUse(use.item, use.mchn, use.bar, use.start, date)
                return max(0, rem - _get_lbs_used(new_use))
            rem -= _get_lbs_used(use)
    
    def use(self, item, mchn, bar, start, end):
        for i, use in enumerate(self._usages):
            if use.start >= end:
                self._usages.insert(i, _BeamUse(item, mchn, bar, start, end))
                return
        self._usages.append(_BeamUse(item, mchn, bar, start, end))