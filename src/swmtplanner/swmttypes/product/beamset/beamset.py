#!/usr/bin/env python

from swmtplanner.support import SwmtBase, HasID

class BeamSet(SwmtBase, HasID[str],
              read_only=('id','denier','kind','ends','beams','split')):
    
    def __init__(self, desc: str):
        comps = desc.split()
        split = comps[-1] == 's/l'
        if split: comps = comps[:-1]
        denier = comps[0][:-1]
        ends, beams = comps[-1].split('X')
        kind = ' '.join(comps[1:-1])

        SwmtBase.__init__(self, _id=desc, _denier=int(denier), _kind=kind,
                          _ends=int(ends), _beams=int(beams), _split=split)
    
    def __str__(self):
        return f'{self.prefix}({self.id})'
    
    @property
    def prefix(self):
        return 'BeamSet'