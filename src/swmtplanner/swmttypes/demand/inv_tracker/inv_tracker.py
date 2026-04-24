#!/usr/bin/env python

from datetime import datetime
import math

from swmtplanner.support import SwmtBase
from swmtplanner.swmttypes.demand import Order, Safety, Production

class InvTracker(SwmtBase, read_only=('item','safety_lbs','safety_rolls'),
                 priv=('jobs','usage','production','init_lbs','init_rolls')):
    
    def __init__(self, item, safety_lbs, safety_rolls, init_lbs, init_rolls):
        super().__init__(_item=item, _safety_lbs=safety_lbs,
                         _safety_rolls=safety_rolls, _jobs=[], _usage=[],
                         _production=[], _init_lbs=init_lbs,
                         _init_rolls=init_rolls)

    def get_excess_rolls(self, job, assign_production: bool = False) -> tuple[int, int]:
        remaining = round(job.lbs_prod / self.item.tgt_wt)

        for order in self._usage:
            if remaining <= 0:
                break

            order_remaining = order.remaining_rolls()
            if order_remaining <= 0:
                continue

            days_early = (order.date - job.end).days
            if not (0 <= days_early <= 7):
                continue

            rolls_to_apply = min(remaining, order_remaining)

            if assign_production:
                order.add_production(Production(
                    job=job,
                    rolls=rolls_to_apply
                ))

            remaining -= rolls_to_apply

        # Excess beyond direct orders
        excess_orders = remaining

        # Excess beyond safety stock needs for the job's week
        iso = job.start.isocalendar()
        safety_needed = self.get_safety_needed(iso.week, iso.year)
        excess_safety = max(0, remaining - safety_needed)

        if assign_production and remaining > 0:
            self._production.append(Production(
                job=job,
                rolls=remaining
            ))

        return excess_orders, excess_safety

    def create_order(self, date, rolls):
        ret = Order(self.item, rolls, date, self)
        self._usage.append(ret)
        return ret
    
    def split_orders(self, due_date: datetime, rolls: int, days_per_week: int) -> list[Order]:
        n_orders = math.ceil(rolls / days_per_week)
        base, extra = divmod(rolls, n_orders)

        return [
            self.create_order(due_date, base + (1 if i < extra else 0))
            for i in range(n_orders)
        ]

    def get_safety_needed(self, week: int, year: int) -> int:
        week_start = datetime.fromisocalendar(year, week, 1)

        # Rolls going out: unfulfilled rolls from orders due before this week
        outbound = sum(
            o.remaining_rolls(by=week_start) for o in self._usage
            if o.date < week_start
        )

        # Rolls coming in: excess production scheduled to finish before this week
        inbound = sum(
            p.rolls for p in self._production
            if p.job.end < week_start
        )

        inventory = self.init_rolls + inbound - outbound
        return max(0, self.safety_rolls - inventory)

    def split_safety(self, week: int, year: int, days_per_week: int) -> list[Safety]:
        needed = self.get_safety_needed(week, year)
        if needed <= 0:
            return []

        n_orders = math.ceil(needed / days_per_week)
        base, extra = divmod(needed, n_orders)

        return [
            Safety(self.item, base + (1 if i < extra else 0), year, week, self)
            for i in range(n_orders)
        ]