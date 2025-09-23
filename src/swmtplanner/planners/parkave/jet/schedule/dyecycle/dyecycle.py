#!/usr/bin/env python

import datetime as dt

from swmtplanner.swmttypes.products import GreigeStyle, fabric
from swmtplanner.swmttypes.schedule import Job, JobView

class DyeCycle(Job[GreigeStyle]):
    
    def __init__(self, lots, start, moveable = True, idx = None):
        super().__init__(lots, start, lots[0].cycle_time, moveable, idx)

    @property
    def color(self):
        return self.lots[0].product.color
    
    @property
    def shade(self):
        return self.color.shade
    
    @property
    def is_product(self):
        is_strip = self.shade in (fabric.color.Shade.STRIP,
                                  fabric.color.Shade.HEAVYSTRIP)
        is_empty = self.shade == fabric.color.Shade.EMPTY and \
            self.id[:5] == 'EMPTY'
        return not (is_strip or is_empty)
    
    @property
    def min_date(self):
        if self.moveable:
            if not self.lots:
                return dt.datetime.fromtimestamp(0)
            return max(map(lambda l: l.received, self.lots))
        return self.start
    
    def copy_lots(self, start, cycle_time, moveable, idx = None):
        return DyeCycle(self._lots, start, moveable=moveable, idx=idx)
    
    def view(self):
        return DyeCycleView(self)

class DyeCycleView(JobView[GreigeStyle], attrs=('color','shade'),
                   funcs=('copy_lots',)):
    pass