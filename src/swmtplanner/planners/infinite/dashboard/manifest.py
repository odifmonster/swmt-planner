#!/usr/bin/env python

"""Static manifest of the planner's MySQL schema (database `swmtinfinite`).

The single source of truth shared by the persistence writer (INSERT layout +
order) and the `knit-debug` investigation app (foreign-key navigation, column
typing, the run registry). The MySQL base tables share their names with the
`DebugLog` tables (the database is dedicated to the knitting planner, so no
translation is needed), so each `TableSpec` carries a single `name` used both to
read rows (`DebugLog.get_df(name)`) and to write them (`INSERT INTO name`). The
manifest still records column types, the FK graph, and the FK-topological insert
order — none of which the `DebugLog` itself exposes. A test
(`tests/dashboard_tests.py`) checks it stays consistent with the live
`DebugLog`.

See `planners/infinite/dashboard/DESIGN.md`.
"""

from dataclasses import dataclass, field
from typing import Literal

# Column type, for the app's per-column filter modes: int/float -> numeric
# comparisons, datetime -> date comparisons, str -> text (LIKE).
ColumnType = Literal['int', 'float', 'str', 'datetime']


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
    """One MySQL table. `name` is the table — identical in the `DebugLog` (the
    row source, for the 8 detail tables) and the database. `columns` are the
    non-`run_id` columns in DB order; `pk` is the table's own primary-key
    column(s) after the implicit leading `run_id` (empty for a key-less table)."""
    name: str
    columns: tuple[Column, ...]
    pk: tuple[str, ...]
    fks: tuple[ForeignKey, ...] = field(default_factory=tuple)

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)


# The implicit run-tag column carried by every table, and the run registry that
# owns it (auto-incremented server-side). `runs` has no `DebugLog` counterpart.
RUN_ID = 'run_id'
RUNS_TABLE = 'runs'

RUNS = TableSpec(
    name=RUNS_TABLE,
    columns=(
        Column('run_id', 'int'),
        Column('created_at', 'datetime'),
        Column('start_date', 'datetime', nullable=True),
        Column('total_score', 'float', nullable=True),
        Column('n_unmet', 'int', nullable=True),
        Column('label', 'str', nullable=True),
        Column('notes', 'str', nullable=True),
    ),
    pk=('run_id',),
)

# The eight DebugLog tables, in FK-topological insert order (parents first):
# runs -> demand -> iteration_log -> cost_summary -> inv_cost_detail
#      -> sched_cost_detail -> production ; priority_detail, unmet_demand after.
TABLES: tuple[TableSpec, ...] = (
    TableSpec(
        'demand',
        columns=(
            Column('order_id', 'str'),
            Column('item', 'str'),
            Column('due_date', 'datetime', nullable=True),   # NaT for safety orders
            Column('demand', 'float'),
            Column('covered_on_hand', 'float'),
            Column('remaining', 'float'),
        ),
        pk=('order_id',),
    ),
    TableSpec(
        'iteration_log',
        columns=(
            Column('iteration_idx', 'int'),
            Column('move_id', 'int'),
            Column('order_id', 'str', nullable=True),         # None for run-up jobs
            Column('order_remaining_lbs', 'float'),
            Column('machine', 'str'),
            Column('decision_point', 'str'),
            Column('role', 'str'),
            Column('rank', 'int'),
            Column('total_cost', 'float'),
        ),
        pk=('move_id',),
        fks=(ForeignKey('order_id', 'demand', 'order_id'),),
    ),
    TableSpec(
        'cost_summary',
        columns=(
            Column('summary_id', 'str'),
            Column('move_id', 'int'),
            Column('label', 'str'),
            Column('kind', 'str'),
            Column('raw', 'float'),
            Column('cost', 'float'),
        ),
        pk=('summary_id',),
        fks=(ForeignKey('move_id', 'iteration_log', 'move_id'),),
    ),
    TableSpec(
        'inv_cost_detail',
        columns=(
            Column('icost_id', 'int'),
            Column('summary_id', 'str'),
            Column('move_id', 'int'),
            Column('label', 'str'),
            Column('item', 'str'),
            Column('days', 'float', nullable=True),           # blank for excess rows
            Column('qty', 'float'),
            Column('weight', 'float'),
            Column('value', 'float'),
        ),
        pk=('icost_id',),
        fks=(
            ForeignKey('summary_id', 'cost_summary', 'summary_id'),
            ForeignKey('move_id', 'iteration_log', 'move_id'),
        ),
    ),
    TableSpec(
        'sched_cost_detail',
        columns=(
            Column('activity_id', 'str'),
            Column('move_id', 'int'),
            Column('machine', 'str'),
            Column('start', 'datetime'),
            Column('end', 'datetime'),
            Column('desc', 'str'),
            Column('weight', 'float', nullable=True),         # blank for cost-free types
            Column('cost', 'float', nullable=True),
        ),
        pk=('activity_id',),
        fks=(ForeignKey('move_id', 'iteration_log', 'move_id'),),
    ),
    TableSpec(
        'production',
        columns=(
            Column('knit_id', 'str'),
            Column('move_id', 'int'),
            Column('roll_id', 'str'),
            Column('job_id', 'str'),
            Column('item', 'str'),
            Column('start', 'datetime'),
            Column('end', 'datetime'),
            Column('lbs', 'float'),
        ),
        pk=('knit_id',),
        fks=(
            # A knit IS a scheduled activity — a DB link not in DebugLog.schema.
            ForeignKey('knit_id', 'sched_cost_detail', 'activity_id'),
            ForeignKey('move_id', 'iteration_log', 'move_id'),
        ),
    ),
    TableSpec(
        'priority_detail',
        columns=(
            Column('move_id', 'int'),
            Column('item', 'str'),
            Column('week_idx', 'int'),
            Column('remaining_lbs', 'float'),
            Column('late_day', 'float', nullable=True),
            Column('weight', 'float'),
            Column('cost', 'float'),
        ),
        pk=(),                                                # key-less
        fks=(ForeignKey('move_id', 'iteration_log', 'move_id'),),
    ),
    TableSpec(
        'unmet_demand',
        columns=(
            Column('item', 'str'),
            Column('week_idx', 'int'),
            Column('unmet_lbs', 'float'),
        ),
        pk=(),                                                # key-less
    ),
)

# Lookups. `TABLES` is already the insert order; `ALL_TABLES` prepends the run
# registry (which the writer fills first).
ALL_TABLES: tuple[TableSpec, ...] = (RUNS,) + TABLES
_BY_NAME = {t.name: t for t in ALL_TABLES}


def spec_for_name(name: str) -> TableSpec:
    """The `TableSpec` for the table named `name` (any of the eight detail
    tables or the `runs` registry). Raises `KeyError` if unknown."""
    return _BY_NAME[name]
