#!/usr/bin/env python

from swmtplanner.support import SwmtBase

_RO_PROPS = ('item','rolls','lbs','week','prty')
_P_PROPS = ('job',)

class Req(SwmtBase, read_only=_RO_PROPS, priv=_P_PROPS):
    
    def __init_subclass__(cls, read_only=tuple(), priv=tuple()):
        super().__init_subclass__(read_only=_RO_PROPS+read_only, priv=priv+_P_PROPS)
    
    def __init__(self, item, rolls, week, prty, **kwargs):
        super().__init__(_item=item, _rolls=rolls, _lbs=rolls * item.tgt_wt,
                         _week=week, _prty=prty, _job=None, **kwargs)