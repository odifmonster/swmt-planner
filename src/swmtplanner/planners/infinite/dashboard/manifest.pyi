from dataclasses import dataclass
from typing import Literal

ColumnType = Literal['int', 'float', 'str', 'datetime']


@dataclass(frozen=True)
class Column:
    name: str
    type: ColumnType
    nullable: bool = ...


@dataclass(frozen=True)
class ForeignKey:
    column: str
    ref_table: str
    ref_column: str


@dataclass(frozen=True)
class TableSpec:
    name: str
    columns: tuple[Column, ...]
    pk: tuple[str, ...]
    fks: tuple[ForeignKey, ...] = ...
    @property
    def column_names(self) -> tuple[str, ...]: ...


RUN_ID: str
RUNS_TABLE: str
RUNS: TableSpec
TABLES: tuple[TableSpec, ...]
ALL_TABLES: tuple[TableSpec, ...]


def spec_for_name(name: str) -> TableSpec: ...
