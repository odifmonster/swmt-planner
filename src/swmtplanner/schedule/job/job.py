#!/usr/bin/env python

from ...support import HasID

def _get_next_id():
    ctr = 0
    def func():
        nonlocal ctr
        ctr += 1
        return f'JOB{ctr:05}'
    return func

_NEXT_ID = _get_next_id()

class Job(HasID[str]):
    
    def __init__(self, item, start, end, lbs):
        self._id = _NEXT_ID()
        self._item = item
        self._start = start
        self._end = end
        self._lbs = lbs

    @property
    def id(self):
        return self._id
    
    @property
    def item(self):
        return self._item
    
    @property
    def start(self):
        return self._start
    
    @property
    def end(self):
        return self._end
    
    @property
    def lbs(self):
        return self._lbs