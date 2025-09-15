#!/usr/bin/env python

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
        return self.shade not in (fabric.color.Shade.STRIP, fabric.color.Shade.HEAVYSTRIP)
    
    def view(self):
        return DyeCycleView(self)

class DyeCycleView(JobView[GreigeStyle], attrs=('color','shade')):
    pass