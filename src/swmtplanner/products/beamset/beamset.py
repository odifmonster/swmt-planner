#!/usr/bin/env python

from ...support import HasID

class BeamSet(HasID[str]):

    def __init__(self, id):
        self._id = id

        parts = id.split()
        if parts[-1] == 'S/L':
            self._split_lease = True
            parts = parts[:-1]
        else:
            self._split_lease = False

        self._denier = int(parts[0].removesuffix('D'))
        ends_str, spools_str = parts[-1].split('X')
        self._ends = int(ends_str)
        self._spools = int(spools_str)
        self._yarn_desc = ' '.join(parts[1:-1])

    @property
    def prefix(self):
        return 'BeamSet'

    @property
    def id(self):
        return self._id

    @property
    def denier(self) -> int:
        return self._denier

    @property
    def ends(self) -> int:
        return self._ends

    @property
    def spools(self) -> int:
        return self._spools

    @property
    def split_lease(self) -> bool:
        return self._split_lease

    @property
    def yarn_desc(self) -> str:
        return self._yarn_desc