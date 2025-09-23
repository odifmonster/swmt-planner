from typing import Any
import datetime as dt
from swmtplanner.support import SwmtBase, HasID, Viewer
from swmtplanner.swmttypes.products import GreigeStyle, FabricItem
from swmtplanner.swmttypes.materials import Lot, LotView

__all__ = ['Job', 'JobView']

type _Product = GreigeStyle | FabricItem

class Job[T: _Product](SwmtBase, HasID[str],
                       read_only=('id','start','end','cycle_time','rawmat','moveable'),
                       priv=('lots',)):
    """
    A class representing jobs in a schedule. Jobs are attached
    to a specific group of raw materials, a product, a machine,
    and a time. They can be activated or deactivated.
    """
    def __init__(self, lots: list[Lot[Any, T, Any]], start: dt.datetime,
                 cycle_time: dt.timedelta, moveable: bool, idx: int | None = None) -> None:
        """
        Initialize a new Job object.

          lots:
            The Lot (raw material) objects used by this Job.
          start:
            The date and time this job starts.
          cycle_time:
            The cycle time of this job.
          moveable:
            Whether or not this job is moveable on the schedule.
          idx: (default None)
            The position of this job on the schedule, or None if it
            is being bumped.
        """
        ...
    @property
    def start(self) -> dt.datetime:
        """The date and time this job starts."""
        ...
    @property
    def end(self) -> dt.datetime:
        """The date and time this job ends."""
        ...
    @property
    def cycle_time(self) -> dt.timedelta:
        """The cycle time of this job."""
        ...
    @property
    def moveable(self) -> bool:
        """Whether this job is moveable."""
        ...
    @property
    def rawmat(self) -> T:
        """The raw material item this job uses."""
        ...
    @property
    def lots(self) -> list[LotView[Any, T, Any]]:
        """The actual raw materials allocated to this job."""
        ...
    @property
    def is_product(self) -> bool:
        """Whether this job is producing an item (as opposed to cleaning)."""
        ...
    def copy_lots(self, start: dt.datetime, cycle_time: dt.timedelta,
                  moveable: bool, idx: int | None = None) -> Job[T]: ...
    def activate(self) -> None:
        """Activate this job on the schedule."""
        ...
    def deactivate(self) -> None:
        """Deactivate this job on the schedule."""
        ...
    def view(self) -> JobView[T]:
        """A live, read-only view of this object."""
        ...

class JobView[T: _Product](Viewer[Job[T]]):
    """A class for views of Job objects."""
    def __init_subclass__(cls, dunders: tuple[str, ...] = tuple(),
                          attrs: tuple[str, ...] = tuple(),
                          funcs: tuple[str, ...] = tuple(),
                          read_only: tuple[str, ...] = tuple(),
                          priv: tuple[str, ...] = tuple()) -> None:
        """
        Initialize a new JobView subclass.

          dunders:
            Dunder names to be passed to the Viewer subclass
            initializer. 'hash', 'eq', and 'repr' are added
            automatically.
          attrs:
            Attribute names to be passed to the Viewer subclass
            initializer. 'prefix', 'id', 'start', 'end',
            'cycle_time', 'rawmat', 'moveable', 'lots', and
            'is_product' are added automatically.
          funcs:
            Function names to be passed to the Viewer subclass
            initializer. 'copy_lots' is added automatically.
          read_only:
            Names to be passed to the Viewer subclass initializer.
          priv:
            Names to be passed to the Viewer subclass initializer.
        """
        ...
    def __hash__(self) -> int: ...
    def __eq__(self, value: Job[T] | JobView[T]) -> bool: ...
    def __repr__(self) -> str: ...
    @property
    def prefix(self) -> str:
        """Used to distinguish between different HasID implementations."""
        ...
    @property
    def id(self) -> int:
        """The unique, hashable id of this object."""
        ...
    @property
    def start(self) -> dt.datetime:
        """The date and time this job starts."""
        ...
    @property
    def end(self) -> dt.datetime:
        """The date and time this job ends."""
        ...
    @property
    def cycle_time(self) -> dt.timedelta:
        """The cycle time of this job."""
        ...
    @property
    def moveable(self) -> bool:
        """Whether this job is moveable."""
        ...
    @property
    def rawmat(self) -> T:
        """The raw material item this job uses."""
        ...
    @property
    def lots(self) -> list[LotView[Any, T, Any]]:
        """The actual raw materials allocated to this job."""
        ...
    @property
    def is_product(self) -> bool:
        """Whether this job is producing an item (as opposed to cleaning)."""
        ...
    def copy_lots(self, start: dt.datetime, cycle_time: dt.timedelta,
                  moveable: bool, idx: int | None = None) -> Job[T]: ...