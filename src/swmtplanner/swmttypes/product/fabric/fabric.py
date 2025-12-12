#!/usr/bin/env python

import datetime as dt

from swmtplanner.support import SwmtBase, HasID
from .color import Shade

class Fabric(SwmtBase, HasID[str],
             read_only=('id','master','color','width','greige','yld',
                        'cycle_time'),
             priv=('jets',)):
    def __init__(self, master, clr, wd, grg, yld, jets):
        match clr.shade:
            case Shade.HEAVYSTRIP:
                hrs = 14
            case Shade.STRIP:
                hrs = 7
            case Shade.EMPTY | Shade.LIGHT1 | Shade.LIGHT2 | Shade.MEDIUM:
                hrs = 8
            case Shade.SOLUTION:
                hrs = 6
            case Shade.BLACK:
                hrs = 10
        
        if int(wd) == wd:
            wd_str = str(int(wd))
        else:
            wd_str = str(wd)
        
        SwmtBase.__init__(self, _id=f'FF {master}-{clr.id}-{wd_str}', _color=clr,
                          _width=wd, _greige=grg, _yld=yld,
                          _cycle_time=dt.timedelta(hours=hrs), _jets=tuple(jets))

    def __str__(self):
        return f'{self.prefix}({self.master} | {self.greige.id} | {self.color.name} | {self.width})'
    
    @property
    def prefix(self):
        return 'Fabric'
    
    def can_run_on_jet(self, jet_id):
        return jet_id in self._jets