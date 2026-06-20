from dataclasses import dataclass
from typing import Iterable, Literal

ColumnType = Literal['int', 'float', 'str', 'datetime']

RUN_ID: str


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
    disp_name: str
    desc: str
    columns: tuple[Column, ...]
    pk: tuple[str, ...]
    fks: tuple[ForeignKey, ...] = ...
    order_by: tuple[str, ...] = ...
    @property
    def column_names(self) -> tuple[str, ...]: ...
    @property
    def order_columns(self) -> tuple[str, ...]: ...


def referencing_fks(
    specs: Iterable[TableSpec],
) -> dict[str, tuple[tuple[str, str], ...]]: ...
