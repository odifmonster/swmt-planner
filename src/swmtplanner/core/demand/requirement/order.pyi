from datetime import datetime

from swmtplanner.core.product import Product

from .requirement import Requirement


__all__ = ['Order']


class Order[T: Product](Requirement[T]):
    """A single dated order. Extends Requirement with a due date and the
    release-week offset it falls in."""
    def __init__(self, item: T, init_qty: float, covered_on_hand: float,
                 first_week: tuple[int, int], due_date: datetime) -> None:
        """first_week is an (ISO year, ISO week) pair identifying the release's
        first week; week_offset is derived from it and due_date by counting
        whole ISO weeks (via ISO-calendar Mondays, so 52/53-week years are
        handled)."""
        ...
    @property
    def id(self) -> str:
        """f'P{week_offset}-{iso_weekday}@{item.id}', where iso_weekday is
        due_date.isoweekday() (Mon = 1 ... Sun = 7)."""
        ...
    @property
    def week_offset(self) -> int:
        """How many ISO weeks after the release's first_week the due_date
        falls."""
        ...
    @property
    def due_date(self) -> datetime:
        """The order's due date."""
        ...
