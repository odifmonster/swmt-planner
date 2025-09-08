#!/usr/bin/env python

from swmtplanner.support import SwmtBase, HasID, FloatRange

class GreigeStyle(SwmtBase, HasID[str], read_only=('id','load_rng','roll_rng')):

    def __init__(self, item, load_min, load_max, roll_min, roll_max):
        SwmtBase.__init__(self, _id=item,
                          _load_rng=FloatRange(load_min, load_max),
                          _roll_rng=FloatRange(roll_min, roll_max))
        
    def __str__(self):
        return f'{self.prefix}({self.id}, load_tgt={self.load_rng.average():.2f} lbs)'
        
    @property
    def prefix(self):
        return 'GreigeStyle'