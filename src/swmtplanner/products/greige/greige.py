#!/usr/bin/env python

from collections import namedtuple

from ...support import HasID

BeamConfig = namedtuple('BeamConfig', ['top_beam', 'top_pct', 'btm_beam', 'btm_pct'])

class Greige(HasID[str]):

    def __init__(self, id: str, family: str, tgt_wt: float, top_beam: str, top_pct: float,
                 btm_beam: str, btm_pct: float, machines: dict[str, float]):
        self._id = id
        self._family = family
        self._tgt_wt = tgt_wt
        self._configuration = BeamConfig(top_beam, top_pct, btm_beam, btm_pct)
        self._machines = dict(machines)

    @property
    def prefix(self):
        return 'Greige'

    @property
    def id(self):
        return self._id

    @property
    def family(self):
        return self._family

    @property
    def tgt_wt(self):
        return self._tgt_wt

    @property
    def configuration(self):
        return self._configuration

    def can_run_on_mchn(self, mchn: str) -> bool:
        return mchn in self._machines

    def get_rate_on_mchn(self, mchn: str) -> float:
        return self._machines[mchn]