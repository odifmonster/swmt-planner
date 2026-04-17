#!/usr/bin/env python

from swmtplanner.swmttypes.demand import Req

class Safety(Req):

    def __init__(self, item, rolls, week):
        super().__init__(item, rolls, week, 0)