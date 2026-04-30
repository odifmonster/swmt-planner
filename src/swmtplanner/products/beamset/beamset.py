#!/usr/bin/env python

from ...support import HasID

class BeamSet(HasID[str]):

    def __init__(self, id):
        self._id = id

    @property
    def prefix(self):
        return 'BeamSet'
    
    @property
    def id(self):
        return self._id