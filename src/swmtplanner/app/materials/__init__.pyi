from typing import Protocol, Hashable
from enum import Enum
from abc import abstractmethod
import datetime as dt
from swmtplanner.support import SwmtBase, HasID, Quantity
from swmtplanner.app.products import GreigeStyle, FabricItem

__all__ = ['Status', 'Lot', 'Snapshot']

class Status(Enum):
    ARRIVED = ...
    PLANNED = ...
    NEW = ...

type _Product = GreigeStyle | FabricItem

class Lot[T: Hashable, U: _Product, S: _Product](HasID[T], Protocol):
    """
    A protocol representing a "lot" of raw materials that will
    produce some quantity of a different product. The materials
    have a status and a received date, and the lot has a start
    and end time if it has been placed on the schedule.
    """
    @property
    @abstractmethod
    def status(self) -> Status:
        """The status of the raw materials used in this lot."""
        ...
    @property
    @abstractmethod
    def received(self) -> dt.datetime:
        """The date the materials were/will be received."""
        ...
    @property
    @abstractmethod
    def rawmat(self) -> U:
        """The raw material item used for this lot."""
        ...
    @property
    @abstractmethod
    def product(self) -> S:
        """The product produced by this lot."""
        ...
    @property
    @abstractmethod
    def qty(self) -> Quantity:
        """The quantity of materials (used and produced) by this lot."""
        ...
    @property
    @abstractmethod
    def start(self) -> dt.datetime | None:
        """The date and time the job (if any) assigned to this lot starts."""
        ...
    @property
    @abstractmethod
    def fin(self) -> dt.datetime | None:
        """
        The date and time the finished product becomes available, or
        None if this lot is not on the schedule.
        """
        ...

class Snapshot(SwmtBase, HasID[int], read_only=('id',)):
    """A class representing one "snapshot" of inventory."""
    def __init__(self) -> None: ...