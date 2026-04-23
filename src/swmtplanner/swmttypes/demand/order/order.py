#!/usr/bin/env python

from swmtplanner.swmttypes.demand import Req

class Order(Req, read_only=('date',)):

    def __init__(self, item, rolls, date, tracker):
        year, week, _ = date.isocalendar()
        super().__init__(item, rolls, year, week, 1, tracker, _date=date)