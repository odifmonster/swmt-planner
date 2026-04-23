#!/usr/bin/env python

from swmtplanner.support import SwmtBase

_RO_PROPS = ('item','rolls','lbs','year','week','prty','job')
_P_PROPS = ('tracker',)

class Req(SwmtBase, read_only=_RO_PROPS, priv=_P_PROPS):
    
    def __init_subclass__(cls, read_only=tuple(), priv=tuple()):
        super().__init_subclass__(read_only=_RO_PROPS+read_only, priv=priv+_P_PROPS)
    
    def __init__(self, item, rolls, year, week, prty, tracker, **kwargs):
        super().__init__(_item=item, _rolls=rolls, _lbs=rolls * item.tgt_wt,
                         _year=year, _week=week, _prty=prty, _job=None, _tracker=tracker,
                         **kwargs)
    
    def assign(self, job):
        if self.job is not None:
            raise RuntimeError('This requirement already has a job assigned.')
        self._job = job
        self._tracker._assign_job(job)

    def get_inv_position(self, by_date):
        return self._tracker.net_position_by(by_date)