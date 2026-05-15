#!/usr/bin/env python

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal
from abc import abstractmethod

from swmtplanner.demand.order import RawOrder, SafetyAwareOrder, WeeklyDemand

if TYPE_CHECKING:
    from swmtplanner.demand.rlsitem import RlsItem
    from swmtplanner.demand.order import Order
    from swmtplanner.schedule import Job

_SECONDS_PER_DAY = 86400.0

_EventQty = tuple[Literal['chunk'], float] | tuple[Literal['drain'], 'Order']

class RawView:

    def __init__(self, rls_item: 'RlsItem', weekly_demand: list[WeeklyDemand]) -> None:
        self._rls_item = rls_item
        self._orders = tuple(RawOrder(rls_item, week) for week in weekly_demand)
        self._lateness: float = 0.0

    @property
    def orders(self) -> tuple[RawOrder, ...]:
        return self._orders

    @property
    def lateness(self) -> float:
        return self._lateness

    def recompute(self, jobs: list['Job'], on_hand: float) -> None:
        # FIFO stream over (availability_time, lbs). Jobs are expected sorted
        # by job.end (RlsItem maintains the invariant via bisect.insort).
        # On-hand is available "now"; stamping it at the first order's due
        # date keeps it on-time for every order without taking start_date as a
        # caller-supplied param (which would let a caller make on-hand
        # unavailable to some orders).
        first_due = self._orders[0].week.due_date
        stream: list[tuple[datetime, float]] = [(first_due, on_hand)]
        stream.extend((j.end, j.lbs) for j in jobs)

        chunk_idx = 0
        chunk_remaining = stream[0][1]
        self._lateness = 0.0

        for order in self._orders:
            order.allocated_lbs = 0.0
            needed = order.week.qty_lbs

            while needed > 0 and chunk_idx < len(stream):
                if chunk_remaining <= 0:
                    chunk_idx += 1
                    if chunk_idx >= len(stream):
                        break
                    chunk_remaining = stream[chunk_idx][1]
                    continue

                take = min(needed, chunk_remaining)
                order.allocated_lbs += take

                avail_time = stream[chunk_idx][0]
                if avail_time > order.week.due_date:
                    days_late = (avail_time - order.week.due_date).total_seconds() / _SECONDS_PER_DAY
                    self._lateness += take * (2.0 ** days_late)

                chunk_remaining -= take
                needed -= take


class SafetyAwareView:

    def __init__(self, rls_item: 'RlsItem', weekly_demand: list[WeeklyDemand]) -> None:
        self._rls_item = rls_item
        self._orders = tuple(SafetyAwareOrder(rls_item, week) for week in weekly_demand)
        self._safety_pool: float = 0.0
        self._excess: float = 0.0
        self._carrying: float = 0.0
        self._drainage: float = 0.0
        # Transient simulation state used during recompute. _physical_pool is
        # the safety pool's actual level at the current sim time (affected by
        # bucket-2 fills, late-fill refunds, and demand drains). _drained
        # holds the orders whose due_date has already passed in the sim.
        self._physical_pool: float = 0.0
        self._drained: set = set()

    @property
    def orders(self) -> tuple[SafetyAwareOrder, ...]:
        return self._orders

    @property
    def safety_target(self) -> float:
        return self._rls_item.item.safety

    @property
    def lead_time(self) -> timedelta:
        return self._rls_item.lead_time

    @property
    def safety_pool(self) -> float:
        return self._safety_pool

    @property
    def excess(self) -> float:
        return self._excess

    @property
    def carrying(self) -> float:
        return self._carrying

    @property
    def drainage(self) -> float:
        return self._drainage

    def recompute(self, jobs: list['Job'], on_hand: float) -> None:
        # On-hand is processed as a pseudo-job at the first order's due_date
        # (so it's on-time for every order). Real jobs are expected sorted by
        # job.end; RlsItem maintains that invariant via bisect.insort.
        for order in self._orders:
            order.allocated_lbs = 0.0
        self._safety_pool = 0.0
        self._excess = 0.0
        self._carrying = 0.0
        self._drainage = 0.0
        self._physical_pool = 0.0
        self._drained.clear()

        first_due = self._orders[0].week.due_date
        last_due = self._orders[-1].week.due_date

        # Merge chunk arrivals with order drain events. Chunks (priority 0)
        # fire before drains (priority 1) at the same timestamp — material is
        # available at the start of the period, demand ships at the end.
        events: list[tuple[datetime, int, _EventQty]] = [(first_due, 0, ('chunk', on_hand))]
        events.extend((j.end, 0, ('chunk', j.lbs)) for j in jobs)
        events.extend(
            (order.week.due_date, 1, ('drain', order)) for order in self._orders
        )
        events.sort(key=lambda e: (e[0], e[1]))

        # Walk events, accumulating drainage piecewise (constant between
        # events) up to last_due. Deficits past last_due are not modeled —
        # the raw view's lateness covers reality from there.
        last_t = first_due
        for t, _, ev in events:
            if t > last_t and last_t < last_due:
                end_t = min(t, last_due)
                duration_days = (end_t - last_t).total_seconds() / _SECONDS_PER_DAY
                # Cap deficit at safety_target: any over-drain below 0 means
                # demand exceeded what safety could cover — real shipment
                # lateness, which the raw view accounts for. We don't
                # double-count those lbs here.
                deficit = self.safety_target - max(0.0, self._physical_pool)
                self._drainage += deficit * duration_days

            kind, payload = ev
            if kind == 'chunk':
                self._distribute_chunk(t, payload)
            else:  # 'drain'
                order = payload
                gap = max(0.0, order.week.qty_lbs - order.allocated_lbs)
                self._physical_pool -= gap
                self._drained.add(order)

            last_t = t

        if last_t < last_due:
            duration_days = (last_due - last_t).total_seconds() / _SECONDS_PER_DAY
            deficit = self.safety_target - max(0.0, self._physical_pool)
            self._drainage += deficit * duration_days

    def _distribute_chunk(self, avail_time: datetime, available: float) -> None:
        # Find earliest on-time order (smallest index whose due_date >= avail_time).
        on_time_idx: int | None = None
        for i, order in enumerate(self._orders):
            if order.week.due_date >= avail_time:
                on_time_idx = i
                break

        if on_time_idx is not None:
            # Bucket 1: cumulative unfilled demand across orders 0..on_time_idx,
            # earliest-first (late orders before the on-time one are paid down
            # first; this matches reality where material catches up missed
            # shipments before backing further-out work). No carrying — these
            # lbs are either late or going to the nearest on-time order.
            available = self._fill_orders(0, on_time_idx + 1, available)
            # Bucket 2: refill safety toward target. No carrying — refilling
            # safety should not be discouraged.
            available = self._refill_safety(available)
            # Bucket 3: later on-time orders, in week order. Carrying accrues
            # on any lbs held longer than lead_time before the order's due
            # date.
            available = self._fill_orders(
                on_time_idx + 1, len(self._orders), available, chunk_time=avail_time,
            )
        else:
            # Job late to every order: bucket 1 spans all orders (earliest
            # first), bucket 3 is empty, bucket 2 still applies. Nothing
            # contributes to carrying.
            available = self._fill_orders(0, len(self._orders), available)
            available = self._refill_safety(available)

        # Bucket 4: anything still left over after demand + safety is excess.
        if available > 0:
            self._excess += available

    def _fill_orders(
        self,
        start_idx: int,
        end_idx: int,
        available: float,
        chunk_time: datetime | None = None,
    ) -> float:
        # When chunk_time is supplied, this fill is treated as a bucket-3
        # pass: lbs held from chunk_time to order.due_date beyond lead_time
        # accrue carrying. When chunk_time is None (buckets 1 and the
        # late-to-all bucket 1), no carrying is recorded.
        for i in range(start_idx, end_idx):
            if available <= 0:
                return available
            order = self._orders[i]
            take = min(order.remaining_lbs, available)
            order.allocated_lbs += take
            if take > 0:
                # Late fills (bucket 1 lbs going to an order that has already
                # drained) refund the safety that covered the order earlier.
                if order in self._drained:
                    self._physical_pool += take
                if chunk_time is not None:
                    hold = order.week.due_date - chunk_time
                    beyond_lead = max(timedelta(0), hold - self.lead_time)
                    self._carrying += take * (beyond_lead.total_seconds() / _SECONDS_PER_DAY)
            available -= take
        return available

    def _refill_safety(self, available: float) -> float:
        if available <= 0:
            return 0.0
        room = max(0.0, self.safety_target - self._safety_pool)
        take = min(room, available)
        self._safety_pool += take
        self._physical_pool += take
        return available - take
