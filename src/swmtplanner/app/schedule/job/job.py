#!/usr/bin/env python

from swmtplanner.support import SwmtBase, HasID, Viewer

_CTR = 0

class Job[T](SwmtBase, HasID[str],
          read_only=('id','start','end','cycle_time','rawmat','moveable'),
          priv=('lots','view')):
    
    def __init__(self, lots, start, cycle_time, moveable, idx = None):
        if idx is None:
            globals()['_CTR'] += 1
            idx = globals()['_CTR']

        job_id = ''.join([str(l.id) for l in lots]) + f'@{idx}'

        SwmtBase.__init__(self, _id=job_id, _start=start, _end=start+cycle_time,
                          _cycle_time=cycle_time, _moveable=moveable,
                          _raw_mat=lots[0].rawmat, _lots=lots, _view=JobView(self))
        
    @property
    def prefix(self):
        return 'Job'
    
    @property
    def lots(self):
        return list(map(lambda l: l.view(), self._lots))
    
    @property
    def is_product(self):
        raise NotImplementedError()
    
    def activate(self):
        for lot in self._lots:
            lot.start = self.start

    def deactivate(self):
        for lot in self._lots:
            lot.start = None

    def view(self):
        return self._view

class JobView[T](Viewer[Job[T]], dunders=('hash','eq','repr'),
                 attrs=('prefix','id','start','end','cycle_time','rawmat',
                        'moveable','lots','is_product')):
    pass