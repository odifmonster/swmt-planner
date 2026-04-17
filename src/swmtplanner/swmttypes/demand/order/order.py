#!/usr/bin/env python

from swmtplanner.swmttypes.demand import Req

from datetime import datetime

class Order(Req, read_only=('date',)):

    def __init__(self, item, rolls, date: datetime):
        super().__init__(item, rolls, date.isocalendar()[1], 1, _date=date)