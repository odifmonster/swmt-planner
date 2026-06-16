#!/usr/bin/env python

"""Static manifest mapping the planner's `DebugLog` tables to the
user-provisioned MySQL schema (database `swmtplanner`).

The single source of truth shared by the persistence writer (INSERT layout +
order) and the `knit-debug` investigation app (foreign-key navigation, column
typing, the run registry). Hand-maintained to match the DDL — the table names
differ from the `DebugLog`'s, the columns are identity, and the FK graph adds
one link (`knitprod.knit_id -> knitschedcost.activity_id`) that
`DebugLog.schema` doesn't carry. A test (`tests/dashboard_tests.py`) checks the
manifest stays consistent with the live `DebugLog`.

See `planners/infinite/dashboard/DESIGN.md`.
"""

from dataclasses import dataclass, field
from typing import Literal

# Column type, for the app's per-column filter modes: int/float -> numeric
# comparisons, datetime -> date comparisons, str -> text (LIKE).
ColumnType = Literal['int', 'float', 'str', 'datetime']


@dataclass(frozen=True)
class Column:
    """One non-`run_id` column of a MySQL table. `name` is both the DB column
    and the `DebugLog` column (identity today). `nullable` reflects whether the
    value is genuinely optional in the data (so the app can offer a "(blank)"
    filter), not merely the DDL's nullability."""
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
    """One MySQL table. `debuglog` is the source `DebugLog` table name (None for
    the run registry, which has no `DebugLog` counterpart). `columns` are the
    non-`run_id` columns in DB order; `pk` is the table's own primary-key
    column(s) after the implicit leading `run_id` (empty for a key-less table)."""
    debuglog: str | None
    table: str
    columns: tuple[Column, ...]
    pk: tuple[str, ...]
    fks: tuple[ForeignKey, ...] = field(default_factory=tuple)

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)


# The implicit run-tag column carried by every table, and the run registry that
# owns it (auto-incremented server-side).
RUN_ID = 'run_id'
RUNS_TABLE = 'knitruns'

# The run registry. `run_id` + `created_at` are server-filled; the writer
# supplies `start_date` / `total_score` / `n_unmet`; `label` / `notes` start
# NULL (and are only writable by the writer role, off by default in the app).
RUNS = TableSpec(
    debuglog=None,
    table=RUNS_TABLE,
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
# knitruns -> knitdmnd -> knititerlog -> knitcostsum -> knitinvcost
#          -> knitschedcost -> knitprod ; knitpriority, knitunmet after parents.
TABLES: tuple[TableSpec, ...] = (
    TableSpec(
        'demand', 'knitdmnd',
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
        'iteration_log', 'knititerlog',
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
        fks=(ForeignKey('order_id', 'knitdmnd', 'order_id'),),
    ),
    TableSpec(
        'cost_summary', 'knitcostsum',
        columns=(
            Column('summary_id', 'str'),
            Column('move_id', 'int'),
            Column('label', 'str'),
            Column('kind', 'str'),
            Column('raw', 'float'),
            Column('cost', 'float'),
        ),
        pk=('summary_id',),
        fks=(ForeignKey('move_id', 'knititerlog', 'move_id'),),
    ),
    TableSpec(
        'inv_cost_detail', 'knitinvcost',
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
            ForeignKey('summary_id', 'knitcostsum', 'summary_id'),
            ForeignKey('move_id', 'knititerlog', 'move_id'),
        ),
    ),
    TableSpec(
        'sched_cost_detail', 'knitschedcost',
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
        fks=(ForeignKey('move_id', 'knititerlog', 'move_id'),),
    ),
    TableSpec(
        'production', 'knitprod',
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
            ForeignKey('knit_id', 'knitschedcost', 'activity_id'),
            ForeignKey('move_id', 'knititerlog', 'move_id'),
        ),
    ),
    TableSpec(
        'priority_detail', 'knitpriority',
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
        fks=(ForeignKey('move_id', 'knititerlog', 'move_id'),),
    ),
    TableSpec(
        'unmet_demand', 'knitunmet',
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
_BY_DEBUGLOG = {t.debuglog: t for t in TABLES}
_BY_DB_TABLE = {t.table: t for t in ALL_TABLES}


def spec_for_debuglog(name: str) -> TableSpec:
    """The `TableSpec` whose `DebugLog` source table is `name`. Raises
    `KeyError` if unknown (the run registry has no `DebugLog` source)."""
    return _BY_DEBUGLOG[name]


def spec_for_table(db_table: str) -> TableSpec:
    """The `TableSpec` for the MySQL table named `db_table` (incl. the run
    registry). Raises `KeyError` if unknown."""
    return _BY_DB_TABLE[db_table]
