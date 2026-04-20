#!/usr/bin/env python

from swmtplanner.swmttypes.demand import Req

class Order(Req, read_only=('date',)):

    def __init__(self, item, rolls, date):
        super().__init__(item, rolls, date.isocalendar()[1], 1, _date=date)