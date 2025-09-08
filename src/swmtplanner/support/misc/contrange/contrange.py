#!/usr/bin/env python

from typing import NamedTuple
import datetime as dt

class ContRange[T](NamedTuple):
    minval: T
    maxval: T

    def contains(self, val, minincl = True, maxincl = True):
        if minincl:
            if hasattr(val, 'minval'):
                over_min = val.minval >= self.minval
            else:
                over_min = val >= self.minval
        else:
            if hasattr(val, 'minval'):
                over_min = val.minval > self.minval
            else:
                over_min = val > self.minval
        if maxincl:
            if hasattr(val, 'maxval'):
                under_max = val.maxval <= self.maxval
            else:
                under_max = val <= self.maxval
        else:
            if hasattr(val, 'maxval'):
                under_max = val.maxval < self.maxval
            else:
                under_max = val < self.maxval
        
        return over_min and under_max
    
    def overlaps(self, rng, minincl = True, maxincl = True):
        return self.contains(rng.minval, minincl=minincl, maxincl=maxincl) or \
            self.contains(rng.maxval, minincl=minincl, maxincl=maxincl)
    
    def is_above(self, val):
        return self.minval > val
    
    def is_below(self, val):
        return self.maxval < val
    
class FloatRange(ContRange[float]):

    def average(self):
        return (self.minval + self.maxval) / 2
    
class DateRange(ContRange[dt.datetime]):
    pass