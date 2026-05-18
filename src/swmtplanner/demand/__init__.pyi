from datetime import datetime
from pathlib import Path

from swmtplanner.products import Greige
from . import order, view
from .rlsitem import RlsItem

__all__ = ['order', 'view', 'read_rls_items']


def read_rls_items(
    path: str | Path, *,
    start_date: datetime,
    greige_by_id: dict[str, Greige],
) -> dict[str, RlsItem]: ...