#!/usr/bin/env python

from datetime import date, datetime
import math

from swmtplanner.support import SwmtBase
from swmtplanner.swmttypes.demand import Order, Safety

class InvTracker(SwmtBase, read_only=('item','safety_lbs','safety_rolls'),
                 priv=('usage','production','init_lbs','init_rolls')):
    
    def __init__(self, item, safety_lbs, safety_rolls, init_lbs, init_rolls):
        super().__init__(_item=item, _safety_lbs=safety_lbs,
                         _safety_rolls=safety_rolls, _usage=[],
                         _production=[], _init_lbs=init_lbs,
                         _init_rolls=init_rolls)

    def _assign_job(self, job):
        self._production.append(job)

    def create_order(self, date, rolls):
        ret = Order(self.item, rolls, date, self)
        self._usage.append(ret)
        return ret
    
    def create_orders(self, week: int, year: int, days_per_week: int, rolls: int) -> list[Order]:
        """
        Returns a list of Order requirements to fulfill the given number of rolls,
        due on Monday of the given week. If the total rolls exceed what a single
        machine can produce in a week (one roll per day), the requirement is split
        across multiple Order objects as evenly as possible.

        week:
            The target ISO week number (1-53).
        year:
            The year corresponding to the ISO week number.
        days_per_week:
            The number of working days in a week, used to determine the
            per-machine roll capacity.
        rolls:
            The total number of rolls to be produced.
        """
        if rolls <= 0:
            return []

        due_date = datetime.fromisocalendar(year, week, 1)
        machines_needed = math.ceil(rolls / days_per_week)
        base_rolls = rolls // machines_needed
        remainder = rolls % machines_needed

        return [
            self.create_order(
                date=due_date,
                rolls=base_rolls + (1 if i < remainder else 0),
            )
            for i in range(machines_needed)
        ]
    
    def create_safeties(self, week: int, year: int, days_per_week: int) -> list[Safety]:
        """
        Returns a list of Safety requirements needed to maintain safety stock
        levels in the given week. If the total rolls needed exceed what a single
        machine can produce in a week (one roll per day), the requirement is
        split across multiple Safety objects as evenly as possible.

        week:
            The target ISO week number (1-53).
        year:
            The year corresponding to the ISO week number.
        days_per_week:
            The number of working days in a week, used to determine the
            per-machine roll capacity.
        """
        week_start = datetime.fromisocalendar(year, week, 1)
        net_lbs = self.net_position_by(week_start)

        if net_lbs >= 0:
            return []

        shortfall = math.ceil(-net_lbs / self.item.tgt_wt)
        machines_needed = math.ceil(shortfall / days_per_week)
        base_rolls = shortfall // machines_needed
        remainder = shortfall % machines_needed

        return [
            Safety(
                item=self.item,
                rolls=base_rolls + (1 if i < remainder else 0),
                week=week,
                tracker=self,
            )
            for i in range(machines_needed)
        ]
    
    def net_position_by(self, date):
        return (self._init_rolls + sum(map(lambda j: j.rolls_prod,
                                          filter(lambda j: j.end <= date, self._production))) \
                                - sum(map(lambda o: o.rolls,
                                          filter(lambda o: o.date <= date, self._usage)))) \
                * self.item.tgt_wt - self.safety_lbs