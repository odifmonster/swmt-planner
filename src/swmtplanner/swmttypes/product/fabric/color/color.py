#!/usr/bin/env python

from swmtplanner.support import SwmtBase, HasID
from .shade import Shade

class Color(SwmtBase, HasID[str], read_only=('name','shade','soil'),
            priv=('id',)):
    
    def __init__(self, formula, name, shade):
        match shade:
            case Shade.SOLUTION | Shade.LIGHT2 | Shade.LIGHT1:
                soil = 1
            case Shade.EMPTY | Shade.MEDIUM:
                soil = 3
            case Shade.BLACK:
                soil = 7
            case Shade.HEAVYSTRIP:
                soil = -63
            case Shade.STRIP:
                soil = -27
        SwmtBase.__init__(self, _id=formula, _name=name, _shade=shade,
                          _soil=soil)
    
    @property
    def prefix(self):
        return 'Color'
    
    @property
    def id(self):
        return f'{self._id:05}'
    
    def get_needed_strip(self, jss, max_clr):
        strip = None
        if self.shade in (Shade.LIGHT1, Shade.LIGHT2):
            if max_clr == Shade.BLACK:
                strip = 'HEAVYSTRIP'
            elif max_clr in (Shade.MEDIUM, Shade.SOLUTION):
                strip = 'STRIP'
        elif self.shade == Shade.MEDIUM:
            if max_clr == Shade.BLACK:
                strip = 'HEAVYSTRIP'
            elif max_clr == Shade.SOLUTION:
                strip = 'STRIP'
        
        if strip is None and jss >= 9:
            strip = 'STRIP'
        
        return strip