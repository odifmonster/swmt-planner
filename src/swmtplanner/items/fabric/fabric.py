#!/usr/bin/env python

from swmtplanner.support import SwmtBase, HasID

class FabricStyle(SwmtBase, HasID[str],
                  read_only=('id','master','greige','color','yld'),
                  priv=('jets',)):
    
    def __init__(self, name, master, greige, color, yld, jets):
        SwmtBase.__init__(self, _id=name, _master=master, _greige=greige,
                          _color=color, _yld=yld, _jets=tuple(jets))
        
    @property
    def prefix(self):
        return 'FabricStyle'
    
    @property
    def shade(self):
        return self.color.shade
    
    def can_run_on_jet(self, jet_id):
        return jet_id in self._jets