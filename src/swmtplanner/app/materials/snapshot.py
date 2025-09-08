#!/usr/bin/env python

from swmtplanner.support import SwmtBase, HasID

_CTR = 0

class Snapshot(SwmtBase, HasID[int], read_only=('id',)):

    def __init__(self):
        SwmtBase.__init__(self, _id=globals()['_CTR'])
        globals()['_CTR'] += 1

    @property
    def prefix(self):
        return 'Snapshot'