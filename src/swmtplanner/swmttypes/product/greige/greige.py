#!/usr/bin/env python

from swmtplanner.support import SwmtBase, HasID
from ..beamset import BeamSet

class Greige(SwmtBase, HasID[str],
             read_only=('id','family','roll_avg','gauge','top_set',
                        'top_pct','btm_set','btm_pct'),
             priv=('machines',)):
    
    def __init__(self, style, roll_avg, family = 'Z', gauge = 28,
                 top_set = None, top_pct = 0.5, btm_set = None, btm_pct = 0.5,
                 machines = []):
        if top_set is not None:
            top_set = BeamSet(top_set)
        if btm_set is not None:
            btm_set = BeamSet(btm_set)

        SwmtBase.__init__(self, _id=style, _roll_avg=roll_avg, _family=family,
                          _gauge=gauge, _top_set=top_set, _top_pct=top_pct,
                          _btm_set=btm_set, _btm_pct=btm_pct,
                          _machines={mid: rate for mid, rate in machines})
    
    def __str__(self):
        return f'{self.prefix}({self.id})'
    
    @property
    def prefix(self):
        return 'Greige'
    
    def can_run_on_mchn(self, mchn_id):
        return mchn_id in self._machines
    
    def get_rate_on_mchn(self, mchn_id):
        return self._machines[mchn_id]