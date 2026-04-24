from datetime import datetime

from swmtplanner.swmttypes.product import Greige
from swmtplanner.swmttypes.demand import Order, Safety
from swmtplanner.swmttypes.schedule import Job

__all__ = ['InvTracker']

class InvTracker:
    def __init__(self, item: Greige, safety_lbs: float, safety_rolls: int,
                 init_lbs: float, init_rolls: int) -> None: ...
    @property
    def item(self) -> Greige: ...
    @property
    def safety_lbs(self) -> float: ...
    @property
    def safety_rolls(self) -> int: ...
    def assign_job(self, job: Job, assign_production: bool = False) -> tuple[int, int]:
        """
        Determines how many rolls produced by the given job are in excess of
        direct order requirements and safety stock needs.

        Iterates through unfulfilled orders, applying rolls from the job toward
        any order that is not yet fulfilled and whose due date falls within one
        week of the job's end date. If assign_production is True, creates and
        assigns Production objects to the relevant orders and appends any
        remaining rolls to this tracker's internal production log.

        Args:
            job: The Job whose output is being evaluated.
            assign_production: If True, Production objects are created and
                assigned to orders and this tracker's production log. If False,
                the method only calculates and returns the excess rolls without
                making any assignments. Defaults to False.

        Returns:
            A tuple of (excess_orders, excess_safety) where:
                excess_orders: Rolls remaining after fulfilling direct orders.
                excess_safety: Rolls remaining after also accounting for safety
                    stock replenishment needs for the job's running week.
        """
        ...

    def create_order(self, date: datetime, rolls: int) -> Order:
        """
        Creates a single Order for the given number of rolls due by the given date.

        Args:
            date: The due date of the order.
            rolls: The number of rolls required.
        """
        ...

    def split_orders(self, due_date: datetime, rolls: int, days_per_week: int) -> list[Order]:
        """
        Splits a roll requirement into multiple parallel Orders, each fulfillable
        within a single week by a single machine.

        Since a machine can produce at most one roll per day, any requirement
        exceeding days_per_week rolls must be split across multiple machines
        running simultaneously. All resulting orders share the same due date.

        Args:
            due_date: The date by which all orders must be fulfilled.
            rolls: The total number of rolls required.
            days_per_week: The number of working days per week, used to
                determine the maximum rolls a single machine can produce.

        Returns:
            A list of Orders split as evenly as possible across the minimum
            number of machines needed to fulfill the requirement in one week.
        """
        ...

    def get_safety_needed(self, week: int, year: int) -> int:
        """
        Calculates the number of rolls needed to bring inventory back to safety
        stock levels at the start of the given week.

        Inventory position is calculated as initial rolls plus any excess
        production scheduled to finish before the given week, minus any
        unfulfilled order rolls due before that week.

        Args:
            week: The ISO week number to check inventory for.
            year: The ISO year corresponding to the given week.

        Returns:
            The number of rolls needed to reach safety stock levels, or 0 if
            inventory is already at or above target.
        """
        ...

    def split_safety(self, week: int, year: int, days_per_week: int) -> list[Safety]:
        """
        Creates the Safety requirements needed to bring inventory back to safety
        stock levels for the given week, split across machines using the same
        logic as split_orders.

        Args:
            week: The ISO week number to replenish safety stock for.
            year: The ISO year corresponding to the given week.
            days_per_week: The number of working days per week, used to
                determine the maximum rolls a single machine can produce.

        Returns:
            A list of Safety requirements split as evenly as possible across the
            minimum number of machines needed, or an empty list if no
            replenishment is needed.
        """
        ...