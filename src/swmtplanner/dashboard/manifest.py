#!/usr/bin/env python

"""Generic manifest dataclasses for the debug dashboard.

A **planner-agnostic** description of a schema's *shape* — the dataclasses a
planner fills in to describe its debug tables, and the universal `run_id`
tag-column name. The concrete instance (a planner's actual tables, FK graph, and
FK-topological insert order) is built and owned by that planner and handed to the
dashboard; nothing here hard-codes a particular planner's schema.

See `swmtplanner/dashboard/DESIGN.md`.
"""

from dataclasses import dataclass, field
from typing import Iterable, Literal

# Column type, for the app's per-column filter modes (int/float -> numeric
# comparisons, datetime/date -> temporal comparisons, str -> text (LIKE)) and for
# the storage shape: a `datetime` is stored as an INT `_date`/`_time` pair, a
# `date` (a calendar date) as a single YYYYMMDD INT — see DESIGN.md, "Storage
# mapping".
ColumnType = Literal['int', 'float', 'str', 'datetime', 'date']

# The implicit run-tag column every persisted table carries (universal across
# planners): every row belongs to a run, and the registry owns the value.
RUN_ID = 'run_id'


@dataclass(frozen=True)
class Column:
    """One non-`run_id` column. `nullable` reflects whether the value is
    genuinely optional in the data (so the app can offer a "(blank)" filter),
    not merely the DDL's nullability."""
    name: str
    type: ColumnType
    nullable: bool = False


@dataclass(frozen=True)
class ForeignKey:
    """A foreign-key link out of a table: `column` references
    `ref_table.ref_column`. The composite `run_id` is implicit on both sides."""
    column: str
    ref_table: str
    ref_column: str


@dataclass(frozen=True)
class TableSpec:
    """One table. `name` is the **logical** table name — identical to the
    planner's debug-log table; `db_name` is the **physical** name in the store
    (defaults to `name`; a planner may prefix it). `columns` are the
    non-`run_id` columns in DB
    order; `pk` is the table's own primary-key column(s) after the implicit
    leading `run_id` (empty for a key-less table). `order_by`, when set, is the
    stable paging/display order and **overrides** the `pk` — for a key-less table,
    or a keyed table shown in a non-key order (e.g. a keyed view ordered by its
    base table's sort). A keyed table without `order_by` paginates by its `pk`;
    every table must end up with one or the other (see `order_columns`)."""
    name: str
    disp_name: str
    desc: str
    columns: tuple[Column, ...]
    pk: tuple[str, ...]
    fks: tuple[ForeignKey, ...] = field(default_factory=tuple)
    order_by: tuple[str, ...] = field(default_factory=tuple)
    # The physical table name in the store. '' (the default) means "same as
    # `name`", resolved in __post_init__ (frozen, hence object.__setattr__).
    db_name: str = ''

    def __post_init__(self) -> None:
        if not self.db_name:
            object.__setattr__(self, 'db_name', self.name)

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    @property
    def order_columns(self) -> tuple[str, ...]:
        """Columns to `ORDER BY` for stable offset paging: the explicit
        `order_by` if set, else the `pk`. (`order_by` wins so a keyed table can
        be displayed in a non-key order.)"""
        return self.order_by if self.order_by else self.pk


def referencing_fks(
    specs: Iterable[TableSpec],
) -> dict[str, tuple[tuple[str, str], ...]]:
    """The inverse of each spec's `fks`: map a **referenced table name** to the
    `(source_table, fk_column)` pairs that point at it. For backward FK
    navigation — given a table's PK, which tables' FK columns reference it.

    Pure and derived only from the given specs: views carry no `fks` (so they
    never appear as a source) and nothing references a view (so they never
    appear as a key). A table absent from the result is referenced by nothing."""
    out: dict[str, list[tuple[str, str]]] = {}
    for spec in specs:
        for fk in spec.fks:
            out.setdefault(fk.ref_table, []).append((spec.name, fk.column))
    return {table: tuple(pairs) for table, pairs in out.items()}
