#!/usr/bin/env python

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .activity import Activity

if TYPE_CHECKING:
    from swmtplanner.core.materials import DyeLot
    from .priority import Priority


@dataclass(frozen=True, eq=False)
class Job(Activity):

    priority: 'Priority'


@dataclass(frozen=True, eq=False)
class DyeJob(Job):

    lot: 'DyeLot'
