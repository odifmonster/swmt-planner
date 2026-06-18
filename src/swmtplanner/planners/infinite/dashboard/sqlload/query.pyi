from typing import Any

from .helpers import Filter, FKLookup

__all__ = ['Query', 'CHUNK_SIZE']

CHUNK_SIZE: int


class Query:
    def __init__(
        self, cursor: Any, sql: str, nrows: int,
        uniques: dict[str, set | None],
    ) -> None: ...
    @classmethod
    def build(
        cls, cursor: Any, run_id: int, table: str,
        **constraints: Filter | FKLookup,
    ) -> Query: ...
    @property
    def nrows(self) -> int: ...
    @property
    def row_offset(self) -> int: ...
    def next_chunk(self) -> tuple[tuple, ...]: ...
    def prev_chunk(self) -> tuple[tuple, ...]: ...
    def unique(self, colname: str) -> list | None: ...
