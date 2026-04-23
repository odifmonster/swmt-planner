#!/usr/bin/env python

from swmtplanner.swmttypes.demand import Req

class Safety(Req):

    def __init__(self, item, rolls, year, week, tracker):
        super().__init__(item, rolls, year, week, 0, tracker)