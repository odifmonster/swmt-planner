#!/usr/bin/env python

from collections import namedtuple
from datetime import datetime

from swmtplanner.support import SwmtBase

_RO_PROPS = ('item','rolls','lbs','year','week','prty')
_P_PROPS = ('tracker','production')

Production = namedtuple('Production', ['job','rolls'])

class Req(SwmtBase, read_only=_RO_PROPS, priv=_P_PROPS):
    
    def __init_subclass__(cls, read_only=tuple(), priv=tuple()):
        super().__init_subclass__(read_only=_RO_PROPS+read_only, priv=priv+_P_PROPS)
    
    def __init__(self, item, rolls, year, week, prty, tracker, **kwargs):
        super().__init__(_item=item, _rolls=rolls, _lbs=rolls * item.tgt_wt,
                         _year=year, _week=week, _prty=prty, _tracker=tracker,
                         _production=[], **kwargs)
    
    def assign(self, job):
        self._tracker._assign_job(job)
    
    def add_production(self, prod):
        for i, p in enumerate(self._production):
            if p.job.start > prod.job.start:
                self._production.insert(i, prod)
                return
        self._production.append(prod)
    
    def remaining_rolls(self, by: datetime | None = None) -> int:
        if by is None:
            applied = sum(p.rolls for p in self._production)
        else:
            applied = sum(p.rolls for p in self._production if p.job.end <= by)
        
        return max(0, self.rolls - applied)