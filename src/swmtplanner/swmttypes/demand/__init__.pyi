from typing import NamedTuple, Hashable, Any
from enum import Enum
import datetime as dt
from swmtplanner.support import Quantity, SwmtBase
from swmtplanner.support.grouped import Data, DataView
from swmtplanner.swmttypes.products import GreigeStyle, FabricItem
from swmtplanner.swmttypes.materials import Lot, LotView

__all__ = ['OrderKind', 'OrderQty', 'Order', 'OrderView', 'Req']

class OrderKind(Enum):
    """A class representing a type of order/demand."""
    HARD = ...
    SOFT = ...
    SAFETY = ...

class OrderQty(NamedTuple):
    normal: Quantity
    cumulative: Quantity

type _Product = GreigeStyle | FabricItem

class Order[T: Hashable, U: _Product](
    Data[T], mut_in_group=True, read_only=('item','pnum','hard_date','soft_date'),
    priv=('qty_map','req')):
    """
    A class representing individual orders for a product. Has
    hard (i.e. minimum), soft (i.e. needed for schedule), and
    safety-replenishment components.
    """
    def __init__(self, id: T, item: U, req: Req[U], pnum: int,
                 hard_qty: OrderQty, hard_date: dt.datetime,
                 soft_qty: OrderQty, soft_date: dt.datetime,
                 safety_qty: OrderQty) -> None:
        """
        Initialize a new Order object.

          id:
            The unique, hashable id assigned to this order.
          item:
            The product being ordered.
          req:
            The Req object this order is attached to.
          hard_qty:
            The normal and cumulative hard/minimum quantities.
          hard_date:
            The latest date this can be finished to meet the
            customer's schedule.
          soft_qty:
            The normal and cumulative soft quantities (that is, what
            is needed to match the production schedule).
          soft_date:
            The latest date this can be finished to meet the
            production schedule.
          safety_qty:
            The normal and cumulative quantities of safety stock
            replenishment.
        """
        ...
    @property
    def item(self) -> U:
        """The item being ordered."""
        ...
    @property
    def pnum(self) -> int:
        """The priority number (i.e. week bucket) of this item."""
        ...
    @property
    def hard_date(self) -> dt.datetime:
        """The hard due date for this order."""
        ...
    @property
    def soft_date(self) -> dt.datetime:
        """The soft due date for this order."""
        ...
    def remaining(self, kind: OrderKind, by: dt.datetime | None = None) -> OrderQty:
        """
        Get the remaining quantity to be scheduled for this order,
        optionally by some date.

          kind:
            The kind of demand being targeted (hard, soft, or
            safety).
          by: (default None)
            The date by which to calculate the state of this order.
            If None, all lots will be counted towards fulfilling the
            order. If provided, only lots before or on the 'by' date
            will count.
        
        Returns an OrderQty with the normal and cumulative unmet
        demand.
        """
        ...
    def late(self, kind: OrderKind) -> list[tuple[dt.timedelta, Quantity]]:
        """
        Get a table of late quantities on this order.

          kind:
            The kind of demand being targeted (hard or soft).
        
        Returns a table of pairs of timedeltas and Quantities for
        every lot needed to fulfill this order that finishes after
        the associated due date.
        """
        ...
    def assign(self, lot: Lot[Any, Any, U]) -> None:
        """Assign a lot to this order."""
        ...
    def unassign(self, lot: LotView[Any, Any, U]) -> None:
        """Unassign a lot from this order."""
        ...
    def view(self) -> OrderView[T, U]: ...

class OrderView[T: Hashable, U: _Product](
    DataView[T], attrs=('item','pnum','hard_date','soft_date'),
    funcs=('late','remaining')):
    """A class for views of Order objects."""
    def __init__(self, link: Order[T, U]) -> None: ...
    @property
    def item(self) -> U:
        """The item being ordered."""
        ...
    @property
    def pnum(self) -> int:
        """The priority number (i.e. week bucket) of this item."""
        ...
    @property
    def hard_date(self) -> dt.datetime:
        """The hard due date for this order."""
        ...
    @property
    def soft_date(self) -> dt.datetime:
        """The soft due date for this order."""
        ...
    def remaining(self, kind: OrderKind, by: dt.datetime | None = None) -> OrderQty:
        """
        Get the remaining quantity to be scheduled for this order,
        optionally by some date.

          kind:
            The kind of demand being targeted (hard, soft, or
            safety).
          by: (default None)
            The date by which to calculate the state of this order.
            If None, all lots will be counted towards fulfilling the
            order. If provided, only lots before or on the 'by' date
            will count.
        
        Returns an OrderQty with the normal and cumulative unmet
        demand.
        """
        ...
    def late(self, kind: OrderKind) -> list[tuple[dt.timedelta, Quantity]]:
        """
        Get a table of late quantities on this order.

          kind:
            The kind of demand being targeted (hard or soft).
        
        Returns a table of pairs of timedeltas and Quantities for
        every lot needed to fulfill this order that finishes after
        the associated due date.
        """
        ...

class Req[T: _Product](SwmtBase, read_only=('item',), priv=('orders','lots')):
    """A class representing all the requirements for a single item."""
    def __init__(self, item: T) -> None:
        """
        Initialize a new Req object.

          item:
            The item attached to the requirements.
        """
        ...
    @property
    def item(self) -> T:
        """The item attached to the requirements."""
        ...
    @property
    def orders(self) -> list[OrderView[Any, T]]:
        """The views of the orders under this requirement."""
        ...
    @property
    def lots(self) -> list[LotView[Any, Any, T]]:
        """The views of the lots going towards this requirement."""
        ...
    def add_order(self, id: Hashable, hard_qty: Quantity, hard_date: dt.datetime,
                  soft_qty: Quantity, soft_date: dt.datetime, safety_qty: Quantity) \
                    -> Order[Any, T]:
        """
        Add a new order under this requirement.

          id:
            The unique, hashable id of the order.
          hard_qty:
            The additional (if any) hard demand in this order
            bucket.
          hard_date:
            The hard due date for this order.
          soft_qty:
            The additional (if any) soft demand in this order
            bucket.
          soft_date:
            The soft due date for this order.
          safet_qty:
            The additional (if any) safety stock replenishment in
            this order bucket.
        """
        ...
    def total_prod(self, by: dt.datetime | None = None) -> Quantity:
        """
        Get the total quantity produced towards this requirement,
        optionally by some date.
        """
        ...
    def assign(self, lot: Lot[Any, Any, T]) -> None:
        """Assign a lot to this requirement."""
        ...
    def unassign(self, lot: LotView[Any, Any, T]) -> None:
        """Unassign a lot from this requirement."""
        ...