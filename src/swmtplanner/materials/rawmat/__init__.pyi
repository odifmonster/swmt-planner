from typing import NewType, Hashable
import datetime as dt
from swmtplanner.support import SwmtBase, HasID, Quantity
from swmtplanner.support.grouped import Data, DataView
from swmtplanner.items import GreigeStyle, FabricStyle
from swmtplanner.materials import Snapshot

__all__ = ['RMAlloc', 'Status', 'ARRIVED', 'EN_ROUTE', 'RawMat', 'RawMatView']

class RMAlloc[T: Hashable](SwmtBase, HasID[int],
                           read_only=('id','raw_mat_id','qty','avail_date')):
    """Represents an allocated piece of some raw material."""
    def __init__(self, raw_mat_id: T, avail_date: dt.datetime, qty: Quantity) -> None:
        """
        Initialize a new RMAlloc object.

          raw_mat_id:
            The id of the raw material object that was allocated.
          avail_date:
            The first date this allocated piece will be available.
          qty:
            The quantity being allocated.
        """
        ...
    @property
    def raw_mat_id(self) -> T:
        """The id of the allocated raw material."""
        ...
    @property
    def qty(self) -> Quantity: ...
    @property
    def avail_date(self) -> dt.datetime:
        """The first date this piece will be available."""
        ...

Status = NewType('Status', str)
ARRIVED: Status = ...
EN_ROUTE: Status = ...

class RawMat[T: Hashable](Data[T]):
    """
    Represents raw materials in inventory (or planned to arrive
    in inventory). Subclasses can define additional attributes
    and methods. These objects are not mutable inside of groups.
    Uses its 'snapshot' attribute to calculate its remaining
    quantity in different scenarios.
    """
    def __init_subclass__(cls, read_only: tuple[str, ...] = tuple(),
                          priv: tuple[str, ...] = tuple()) -> None:
        """
        Initialize a new RawMat subclass.

          read_only:
            Inherits values from Data. Includes 'item', 'status',
            and 'receipt_date'. See SwmtBase for more details.
          priv:
            Inherits values from Data. Includes 'cur_qty', 'allocs',
            and 'temp_allocs'. See SwmtBase for more details.
        """
        ...
    def __init__(self, prefix: str, id: T, view: RawMatView[T],
                 item: GreigeStyle | FabricStyle, status: Status,
                 receipt_date: dt.datetime, qty: Quantity, **kwargs) -> None:
        """
        Initialize a new RawMat object.

          prefix:
            The prefix associated with the current subclass.
          id:
            The unique id of this raw material in inventory.
          view:
            The corresponding RawMatView object.
          item:
            An object representing the item/style of this raw
            material.
          status:
            The status of these materials (ARRIVED or EN_ROUTE).
          receipt_date:
            The date the materials were/will be received.
          qty:
            The material quantity.
          **kwargs:
            Additional keyword arguments (if any) to pass to the
            Data initializer.
        """
        ...
    snapshot: Snapshot | None
    @property
    def item(self) -> GreigeStyle | FabricStyle:
        """The raw material item."""
        ...
    @property
    def status(self) -> Status:
        """The status of the raw materials (ARRIVED or EN_ROUTE)."""
        ...
    @property
    def receipt_date(self) -> dt.datetime:
        """The date the materials were/will be received."""
        ...
    @property
    def qty(self) -> Quantity:
        """The material quantity."""
        ...
    def allocate(self, amount: Quantity,
                 snapshot: Snapshot | None = None) -> RMAlloc[T]:
        """
        Allocate some of this raw material.

          amount:
            The amount to allocate.
          snapshot: (default None)
            The "snapshot" where this piece is being allocated. If
            None, the allocation is permanent and all snapshots are
            applied on top. Otherwise, the piece only appears as
            removed when the object's snapshot is set to the
            provided snapshot.

        Returns the allocated piece.
        """
        ...
    def deallocate(self, piece: RMAlloc[T], snapshot: Snapshot | None = None) -> None:
        """
        Deallocate a piece of this raw material.

          piece:
            The actual object returned from a previous call to the
            'allocate' method.
          snapshot: (default None)
            The snapshot this piece was allocated on.
        """
        ...
        
class RawMatView[T: Hashable](DataView[T]):
    """A class for views of RawMat objects."""
    def __init_subclass__(cls, dunders: tuple[str, ...] = tuple(),
                          attrs: tuple[str, ...] = tuple(),
                          funcs: tuple[str, ...] = tuple(),
                          read_only: tuple[str, ...] = tuple(),
                          priv: tuple[str, ...] = tuple()) -> None:
        """
        Initialize a new RawMatView subclass. For all arguments not
        listed, see DataView.

          attrs:
            Inherits values from Data. Includes 'item', 'status',
            'receipt_date', 'qty', and 'snapshot'. See SwmtBase for
            more details.
        """
        ...
    def __init__(self, link: RawMat[T], **kwargs) -> None: ...
    @property
    def item(self) -> GreigeStyle | FabricStyle:
        """The raw material item."""
        ...
    @property
    def status(self) -> Status:
        """The status of the raw materials (ARRIVED or EN_ROUTE)."""
        ...
    @property
    def receipt_date(self) -> dt.datetime:
        """The date the materials were/will be received."""
        ...
    @property
    def qty(self) -> Quantity:
        """The material quantity."""
        ...
    @property
    def snapshot(self) -> Snapshot | None: ...