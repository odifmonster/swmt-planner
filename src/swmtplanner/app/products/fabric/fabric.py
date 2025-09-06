#!/usr/bin/env python

import datetime as dt

from swmtplanner.support import SwmtBase, HasID
from .color import Shade

class FabricItem(SwmtBase, HasID[str],
                 read_only=('id','master','greige','color','yld','cycle_time'),
                 priv=('jets',)):
    
    def __init__(self, item, master, greige, color, yld, jets):
        match color.shade:
            case Shade.HEAVYSTRIP:
                hrs = 14
            case Shade.STRIP:
                hrs = 7
            case Shade.EMPTY | Shade.LIGHT | Shade.MEDIUM:
                hrs = 8
            case Shade.SOLUTION:
                hrs = 6
            case Shade.BLACK:
                hrs = 10

        SwmtBase.__init__(self, _id=item, _master=master, _greige=greige,
                          _color=color, _yld=yld, _cycle_time=dt.timedelta(hours=hrs),
                          _jets=tuple(jets))
        
    def __str__(self):
        return f'{self.prefix}({self.master} - {self.greige.id} - {self.color.name})'
        
    @property
    def prefix(self):
        return 'FabricItem'
    
    def can_run_on_jet(self, jet_id):
        return jet_id in self.jets