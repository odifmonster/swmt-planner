from typing import Any

from ...sqlload.table import Table

ROWS_PER_PAGE: int


class PagedGrid:
    def __init__(self, parent: Any = ...) -> None: ...
    def show_table(self, table: Table) -> None: ...
