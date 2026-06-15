#!/usr/bin/env python

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal
from abc import abstractmethod

from swmtplanner.demand.order import (
    RawOrder, SafetyAwareOrder, WeeklyDemand, Safety,
)

if TYPE_CHECKING:
    from swmtplanner.demand.rlsitem import RlsItem
    from swmtplanner.demand.order import Order
    from swmtplanner.schedule import Job, Roll

_SECONDS_PER_DAY = 86400.0

_EventQty = (tuple[Literal['chunk'], float, 'Roll | None']
             | tuple[Literal['drain'], 'Order'])

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

    def recompute(self, jobs: list['Job'], on_hand: float,
                  detail_sink=None) -> None:
        # FIFO stream over (availability_time, lbs). Each Job expands
        # into one chunk per `Roll` via `Job.rolls` — rolls ship as they
        # come off the machine rather than as a single bundle, so the
        # chunk granularity matches reality. A Job with no rolls
        # contributes nothing (it carries no completion times of its own).
        #
        # On-hand is available "now"; stamping it at the first order's
        # due date keeps it on-time for every order without taking
        # start_date as a caller-supplied param.
        first_due = self._orders[0].week.due_date
        stream: list[tuple[datetime, float]] = [(first_due, on_hand)]
        for j in jobs:
            stream.extend(
                (roll.completion_time, roll.lbs) for roll in j.rolls
            )
        # Multiple machines producing the same item can interleave
        # rolls in time; sort to keep the FIFO walk well-formed.
        stream.sort(key=lambda e: e[0])

        chunk_idx = 0
        chunk_remaining = stream[0][1]
        self._lateness = 0.0

        for order in self._orders:
            order.allocated_lbs = 0.0
            order.late_lbs = 0.0
            order.late_fill_date = None
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
                if order.late_fill_date is None or avail_time > order.late_fill_date:
                    order.late_fill_date = avail_time
                if avail_time > order.week.due_date:
                    order.late_lbs += take
                    days_late = (avail_time - order.week.due_date).total_seconds() / _SECONDS_PER_DAY
                    contribution = take * (2.0 ** days_late)
                    self._lateness += contribution
                    if detail_sink is not None:
                        # One row per late delivery of material to an order.
                        detail_sink('lateness', self._rls_item.item.id,
                                    days_late, take, contribution)

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
        # Safety-replenishment "order" + resolved roll->order fill links.
        self._safety = Safety(rls_item, self)
        self._roll_order_links: list[tuple['Roll', str]] = []
        # Transient: the roll awaiting its first fill-link during the current
        # _distribute_chunk (None for the on_hand pseudo-roll, or once linked).
        self._link_target: 'Roll | None' = None
        # Transient: the per-window cost-detail sink active during recompute
        # (set each recompute; None when not collecting detail).
        self._detail_sink = None

    @property
    def orders(self) -> tuple[SafetyAwareOrder, ...]:
        return self._orders

    @property
    def safety(self) -> Safety:
        return self._safety

    @property
    def roll_order_links(self) -> tuple[tuple['Roll', str], ...]:
        """Resolved (roll, order-id) fill links from the latest recompute —
        one per filled roll, the earliest order it fills. See "Roll → order
        fill links" in DESIGN.md."""
        return tuple(self._roll_order_links)

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

    def recompute(self, jobs: list['Job'], on_hand: float,
                  detail_sink=None) -> None:
        # On-hand is processed as a pseudo-job at the first order's due_date
        # (so it's on-time for every order). Roll arrivals are merged into
        # the event list below and sorted by time, so job order doesn't
        # matter here.
        for order in self._orders:
            order.allocated_lbs = 0.0
        self._safety_pool = 0.0
        self._excess = 0.0
        self._carrying = 0.0
        self._drainage = 0.0
        self._physical_pool = 0.0
        self._drained.clear()
        self._roll_order_links = []
        self._link_target = None
        self._detail_sink = detail_sink            # used by _fill_orders too
        item_id = self._rls_item.item.id

        first_due = self._orders[0].week.due_date
        last_due = self._orders[-1].week.due_date

        # Merge chunk arrivals with order drain events. Chunks (priority 0)
        # fire before drains (priority 1) at the same timestamp — material is
        # available at the start of the period, demand ships at the end.
        # Each Job expands into one chunk per `Roll` via `Job.rolls` so the
        # drainage sim sees fabric arriving as rolls come off the machine.
        # A Job with no rolls contributes nothing.
        events: list[tuple[datetime, int, _EventQty]] = [
            (first_due, 0, ('chunk', on_hand, None))
        ]
        for j in jobs:
            events.extend(
                (roll.completion_time, 0, ('chunk', roll.lbs, roll))
                for roll in j.rolls
            )
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
                if detail_sink is not None and deficit > 0:
                    # One row per stretch the pool sits below target.
                    detail_sink('drainage', item_id, duration_days, deficit,
                                deficit * duration_days)

            if ev[0] == 'chunk':
                _, available, roll = ev
                self._distribute_chunk(t, available, roll)
            else:  # 'drain'
                order = ev[1]
                gap = max(0.0, order.week.qty_lbs - order.allocated_lbs)
                self._physical_pool -= gap
                self._drained.add(order)

            last_t = t

        if last_t < last_due:
            duration_days = (last_due - last_t).total_seconds() / _SECONDS_PER_DAY
            deficit = self.safety_target - max(0.0, self._physical_pool)
            self._drainage += deficit * duration_days
            if detail_sink is not None and deficit > 0:
                detail_sink('drainage', item_id, duration_days, deficit,
                            deficit * duration_days)

        # Excess has no time dimension: one aggregate row (days = None).
        if detail_sink is not None and self._excess > 0:
            detail_sink('excess', item_id, None, self._excess, self._excess)

    def _distribute_chunk(
        self, avail_time: datetime, available: float,
        roll: 'Roll | None' = None,
    ) -> None:
        # Record the first destination this roll's lbs reach as its fill-link
        # (see "Roll → order fill links" in DESIGN.md). The on_hand pseudo-roll
        # has no Roll, so it never links. `_fill_orders` / `_refill_safety`
        # consume `_link_target` on their first positive take, so any later
        # destination for the same roll is left unlinked.
        self._link_target = roll

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
                self._link_roll(order.id)
                # Late fills (bucket 1 lbs going to an order that has already
                # drained) refund the safety that covered the order earlier.
                if order in self._drained:
                    self._physical_pool += take
                if chunk_time is not None:
                    hold = order.week.due_date - chunk_time
                    beyond_lead = max(timedelta(0), hold - self.lead_time)
                    beyond_lead_days = (
                        beyond_lead.total_seconds() / _SECONDS_PER_DAY
                    )
                    self._carrying += take * beyond_lead_days
                    if self._detail_sink is not None and beyond_lead_days > 0:
                        # One row per fill held beyond lead time.
                        self._detail_sink(
                            'carrying', self._rls_item.item.id,
                            beyond_lead_days, take, take * beyond_lead_days,
                        )
            available -= take
        return available

    def _refill_safety(self, available: float) -> float:
        if available <= 0:
            return 0.0
        room = max(0.0, self.safety_target - self._safety_pool)
        take = min(room, available)
        if take > 0:
            self._link_roll(self._safety.id)
        self._safety_pool += take
        self._physical_pool += take
        return available - take

    def _link_roll(self, order_id: str) -> None:
        """Record the current chunk's roll as filling `order_id` — but only
        the first destination it reaches (and never the on_hand pseudo-roll).
        Consumes `_link_target` so later buckets for the same roll no-op."""
        if self._link_target is not None:
            self._roll_order_links.append((self._link_target, order_id))
            self._link_target = None
