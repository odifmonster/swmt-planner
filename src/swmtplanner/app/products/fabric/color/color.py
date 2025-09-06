#!/usr/bin/env python

from swmtplanner.support import SwmtBase, HasID
from .shade import Shade

class Color(SwmtBase, HasID[str], read_only=('name','shade','soil'),
            priv=('id',)):
    
    def __init__(self, formula, name, shade):
        match shade:
            case Shade.SOLUTION | Shade.LIGHT:
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
    
    def get_needed_strip(self, soil, prev_clr):
        if self.shade == Shade.LIGHT and (soil >= 20 or prev_clr.shade == Shade.BLACK):
            if soil - 27 >= 10:
                return 'HEAVYSTRIP'
            return 'STRIP'
        if self.shade == Shade.MEDIUM and soil >= 35:
            if soil - 27 >= 25:
                return 'HEAVYSTRIP'
            return 'STRIP'
        return None