#!/usr/bin/env python

from swmtplanner.support.grouped import Grouped
from swmtplanner.swmttypes.materials import Status

class PAInv(Grouped[str, Status]):

    def __init__(self):
        super().__init__('status','plant','item','size','id')