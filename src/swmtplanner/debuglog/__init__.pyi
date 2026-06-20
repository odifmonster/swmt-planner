from dataclasses import dataclass
from typing import Any

import pandas as pd

__all__ = ['DebugLog', 'TableSchema', 'ForeignKey']


@dataclass(frozen=True)
class ForeignKey:
    column: str
    ref_table: str
    ref_column: str


@dataclass(frozen=True)
class TableSchema:
    columns: tuple[str, ...]
    pk: tuple[str, ...]
    fks: tuple[ForeignKey, ...]


class DebugLog:
    def __init__(self, **tables: list[tuple[str, Any]]) -> None: ...
    @property
    def tables(self) -> tuple[str, ...]: ...
    @property
    def schema(self) -> dict[str, TableSchema]: ...
    def set_pk(
        self, table: str, *columns: str, ctr_name: str | None = ...,
    ) -> None: ...
    def set_fk(
        self, table: str, column: str,
        foreign_table: str, foreign_column: str,
    ) -> None: ...
    def add_row(self, table: str, **kwargs: Any) -> Any: ...
    def get_last_pk_val(self, table: str) -> Any: ...
    def update_row(self, table: str, pk_val: Any, **kwargs: Any) -> None: ...
    def get_nrows(self, table: str) -> int: ...
    def get_df(self, table: str, **kwargs: Any) -> pd.DataFrame: ...
