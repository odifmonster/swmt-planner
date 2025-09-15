#!/usr/bin/env python

from swmtplanner.support import SwmtBase, HasID, Viewer

_CTR = 0

class Job[T](SwmtBase, HasID[str],
          read_only=('id','start','end','cycle_time','rawmat','moveable'),
          priv=('lots',)):
    
    def __init__(self, lots, start, cycle_time, moveable, idx = None):
        if idx is None:
            globals()['_CTR'] += 1
            idx = globals()['_CTR']

        job_id = ''.join([str(l.id) for l in lots]) + f'@{idx}'

        SwmtBase.__init__(self, _id=job_id, _start=start, _end=start+cycle_time,
                          _cycle_time=cycle_time, _moveable=moveable,
                          _raw_mat=lots[0].rawmat, _lots=lots)
        
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
        raise NotImplementedError()

class JobView[T](Viewer[Job[T]]):
    
    def __init_subclass__(cls, dunders = tuple(), attrs = tuple(), funcs = tuple(),
                          read_only = tuple(), priv = tuple()):
        super().__init_subclass__(dunders=('hash','eq','repr')+dunders,
                                  attrs=('prefix','id','start','end','cycle_time','rawmat',
                                         'moveable','lots','is_product')+attrs,
                                  funcs=funcs, read_only=read_only, priv=priv)