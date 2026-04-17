#!/usr/bin/env python

from swmtplanner.support import SwmtBase, HasID

class Greige(SwmtBase, HasID[str],
             read_only=('id','family','top_set','top_pct','btm_set','btm_pct',
                        'tgt_wt'),
             priv=('machines',)):
    
    def __init__(self, name, family, beam_config, tgt_wt, machines):
        top, btm = beam_config
        top_set, top_pct = top
        btm_set, btm_pct = btm
        SwmtBase.__init__(self, _id=name, _family=family, _top_set=top_set,
                          _top_pct=top_pct, _btm_set=btm_set, _btm_pct=btm_pct,
                          _tgt_wt=tgt_wt, _machines={x: y for x, y in machines})

    @property
    def prefix(self):
        return 'Greige'
    
    def can_run_on(self, mchn):
        return mchn in self._machines
    
    def get_rate_on(self, mchn):
        return self._machines[mchn]