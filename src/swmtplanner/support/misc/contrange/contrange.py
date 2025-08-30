#!/usr/bin/env python

from typing import NamedTuple
import datetime as dt

class ContRange[T](NamedTuple):
    min: T
    max: T

    def contains(self, val, minincl = True, maxincl = True):
        if minincl:
            if hasattr(val, 'min'):
                over_min = val.min >= self.min
            else:
                over_min = val >= self.min
        else:
            if hasattr(val, 'min'):
                over_min = val.min > self.min
            else:
                over_min = val > self.min
        if maxincl:
            if hasattr(val, 'max'):
                under_max = val.max <= self.max
            else:
                under_max = val <= self.max
        else:
            if hasattr(val, 'max'):
                under_max = val.max < self.max
            else:
                under_max = val < self.max
        
        return over_min and under_max
    
    def overlaps(self, rng, minincl = True, maxincl = True):
        return self.contains(rng.min, minincl=minincl, maxincl=maxincl) or \
            self.contains(rng.max, minincl=minincl, maxincl=maxincl)
    
    def is_above(self, val):
        return self.min > val
    
    def is_below(self, val):
        return self.max < val
    
class FloatRange(ContRange[float]):

    def average(self):
        return (self.min + self.max) / 2
    
type DateRange = ContRange[dt.datetime]