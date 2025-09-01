#!/usr/bin/env python

from swmtplanner.support import SwmtBase, HasID, FloatRange

class GreigeStyle(SwmtBase, HasID[str], read_only=('id','load_rng','roll_rng')):

    def __init__(self, name, load_tgt):
        SwmtBase.__init__(self, _id=name,
                          _load_rng=FloatRange(load_tgt-20, load_tgt+20),
                          _roll_rng=FloatRange((load_tgt-20)*2, (load_tgt+20)*2))
        
    @property
    def prefix(self):
        return 'GreigeStyle'