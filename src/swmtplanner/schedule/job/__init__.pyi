from datetime import datetime

from swmtplanner.support import HasID
from swmtplanner.products import Greige

__all__ = ['Job']

class Job(HasID[str]):
    """Represents a job on the schedule."""
    def __init__(self, item: Greige, start: datetime, end: datetime, lbs: float) -> None: ...
    @property
    def item(self) -> Greige: ...
    @property
    def start(self) -> datetime: ...
    @property
    def end(self) -> datetime: ...
    @property
    def lbs(self) -> float: ...