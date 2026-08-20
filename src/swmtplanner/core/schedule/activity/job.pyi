from dataclasses import dataclass

from swmtplanner.core.materials import DyeLot
from .activity import Activity
from .priority import Priority


__all__ = ['Job', 'DyeJob']


@dataclass(frozen=True, eq=False)
class Job(Activity):
    """The generic unit of scheduled work. The record itself is frozen; its
    priority's value is owned by the RlsItem the job is registered with: each
    recompute clears it to None, then sets 'S' when the job's supply first
    fills safety stock, or the week_offset of the first order it fills. A
    value still None after a recompute marks the job as entirely excess."""
    priority: Priority


@dataclass(frozen=True, eq=False)
class DyeJob(Job):
    """The dye-planner job."""
    lot: DyeLot
    """The single DyeLot the job produces."""
