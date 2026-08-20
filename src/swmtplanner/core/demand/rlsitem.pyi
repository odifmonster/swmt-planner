from datetime import datetime, timedelta

from swmtplanner.core.product import Product
from swmtplanner.core.demand.chunk import Chunk
from swmtplanner.core.demand.view import RawView, SafetyView
from swmtplanner.core.schedule import Job


__all__ = ['RlsItem']


class RlsItem[T: Product]:
    """The top-level release item for a single product: packages order
    fulfillment (RawView) and safety-stock replenishment (SafetyView), and owns
    the scheduled-supply chunk list (kept sorted by avail_date). Abstract:
    planner-specific subclasses implement register_job (job -> Chunks)."""
    def __init__(self, item: T, lead_time: timedelta, on_hand: float,
                 safety_tgt: float, start_week: tuple[int, int],
                 today: datetime,
                 due_reqs: list[tuple[float, datetime]]) -> None:
        """Builds the RawView and SafetyView from due_reqs, netting on_hand into
        each view's covered_on_hand — raw: sequential by due date; safety:
        near-term demand -> safety -> future, at horizon today + lead_time."""
        ...
    @property
    def item(self) -> T:
        """The product style this release is for."""
        ...
    @property
    def raw_view(self) -> RawView[T]:
        """The order-lateness view."""
        ...
    @property
    def safety_view(self) -> SafetyView[T]:
        """The inventory-level-maintenance view."""
        ...
    @property
    def lead_time(self) -> timedelta:
        """The ideal production lead time."""
        ...
    @property
    def safety_tgt(self) -> float:
        """The target safety-stock level."""
        ...
    @property
    def today(self) -> datetime:
        """The plan's reference current date."""
        ...
    @property
    def init_on_hand(self) -> float:
        """The starting on-hand quantity the release was constructed with."""
        ...
    def register_chunk(self, chunk: Chunk[T], job: Job | None = None) -> None:
        """Insert one chunk of scheduled supply into the release's chunk list,
        kept sorted by avail_date; when job is given, record it as the chunk's
        source in the chunk -> job map. Does not recompute."""
        ...
    def register_chunks(self, chunks: list[Chunk[T]],
                        job: Job | None = None) -> None:
        """Register each chunk (list convenience form; all the chunks share
        the one source job). Does not recompute."""
        ...
    def register_job(self, job) -> None:
        """Convert a planner schedule job into Chunks and register them with
        the job as their source. Abstract: raises NotImplementedError on the
        base; concrete planner subclasses implement it."""
        ...
    def recompute(self) -> None:
        """Recompute both views over the release's current (sorted) chunk
        list, then push priorities back onto the source jobs: clear every
        mapped job's priority.value to None, then apply the SafetyView's
        (chunk, priority) pairs in chunk order — the first write to a job
        wins ('S' or a week offset). A job whose priority is still None after
        the push is entirely excess."""
        ...
