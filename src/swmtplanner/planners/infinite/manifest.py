#!/usr/bin/env python

"""The infinite knitting planner's concrete debug schema (database
`swmtinfinite`).

The single source of truth for *this planner's* table set, column types, primary
keys, the FK graph, and the FK-topological insert order. The generic `TableSpec`
/ `Column` / `ForeignKey` dataclasses (and the universal `RUN_ID`) come from the
planner-agnostic `swmtplanner.dashboard.manifest`; this module fills them in. The
persistence writer uses it to lay out INSERTs in order, and the dashboard app is
handed it to drive FK navigation / typing / the table list. It is **not** derived
from `DebugLog.schema` — it adds column *types*, the FK-topological order, and one
FK link `DebugLog.schema` doesn't carry (see `planners/infinite/DESIGN.md`, Debug-
log persistence). A test (`tests/dashboard_tests.py`) checks it stays consistent
with the live `DebugLog`.
"""

from swmtplanner.dashboard.manifest import (
    Column, ColumnType, ForeignKey, TableSpec, RUN_ID,
)

__all__ = [
    'Column', 'ColumnType', 'ForeignKey', 'TableSpec', 'RUN_ID',
    'RUNS_TABLE', 'RUNS', 'TABLES', 'VIEWS', 'ALL_TABLES', 'spec_for_name',
]

# The run registry that owns the auto-incremented `run_id` (no `DebugLog`
# counterpart).
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
        order_by=('move_id', 'item', 'week_idx'),
    ),
    TableSpec(
        'unmet_demand',
        columns=(
            Column('item', 'str'),
            Column('week_idx', 'int'),
            Column('unmet_lbs', 'float'),
        ),
        pk=(),                                                # key-less
        order_by=('item', 'week_idx'),
    ),
)

# The committed-move DB **views** — read-only slices the dashboard reads (the
# writer never touches them, so they are NOT in `TABLES`/`ALL_TABLES`). Each
# exposes a subset of its base table's columns for the rows whose move committed,
# and carries no FK columns. Key-less; `order_by` mirrors the view's own ORDER BY
# with the base PK appended for a stable, total paging order.
VIEWS: tuple[TableSpec, ...] = (
    TableSpec(
        'committed_sched',                       # committed slice of sched_cost_detail
        columns=(
            Column('activity_id', 'str'),
            Column('machine', 'str'),
            Column('start', 'datetime'),
            Column('end', 'datetime'),
            Column('desc', 'str'),
        ),
        pk=(),
        order_by=('machine', 'start', 'activity_id'),
    ),
    TableSpec(
        'committed_prod',                        # committed slice of production
        columns=(
            Column('knit_id', 'str'),
            Column('roll_id', 'str'),
            Column('job_id', 'str'),
            Column('item', 'str'),
            Column('start', 'datetime'),
            Column('end', 'datetime'),
            Column('lbs', 'float'),
        ),
        pk=(),
        order_by=('item', 'knit_id'),
    ),
)

# Lookups. `TABLES` is already the insert order; `ALL_TABLES` prepends the run
# registry (which the writer fills first). `_BY_NAME` also resolves the views, so
# the dashboard can look them up, but they stay out of the writable table set.
ALL_TABLES: tuple[TableSpec, ...] = (RUNS,) + TABLES
_BY_NAME = {t.name: t for t in ALL_TABLES + VIEWS}


def spec_for_name(name: str) -> TableSpec:
    """The `TableSpec` for `name` — any of the eight detail tables, the `runs`
    registry, or a committed-move view (`committed_sched` / `committed_prod`).
    Raises `KeyError` if unknown."""
    return _BY_NAME[name]
