from typing import Any, Callable, Sequence

from ..manifest import Column, TableSpec
from .helpers import Filter, FKLookup

__all__ = ['Query', 'CHUNK_SIZE']

CHUNK_SIZE: int


class Query:
    def __init__(
        self, cursor: Any, sql: str, nrows: int,
        distinct_queries: dict[str, tuple[str, str, Callable[[Any], Any]]],
        columns: Sequence[Column],
    ) -> None: ...
    @classmethod
    def build(
        cls, cursor: Any, run_id: int, spec: TableSpec,
        **constraints: Filter | FKLookup,
    ) -> Query: ...
    @property
    def nrows(self) -> int: ...
    @property
    def row_offset(self) -> int: ...
    def next_chunk(self) -> tuple[tuple, ...]: ...
    def prev_chunk(self) -> tuple[tuple, ...]: ...
    def unique(self, colname: str) -> list | None: ...
