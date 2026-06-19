from swmtplanner.dashboard.manifest import (
    Column as Column,
    ColumnType as ColumnType,
    ForeignKey as ForeignKey,
    TableSpec as TableSpec,
    RUN_ID as RUN_ID,
)

RUNS_TABLE: str
RUNS: TableSpec
TABLES: tuple[TableSpec, ...]
VIEWS: tuple[TableSpec, ...]
ALL_TABLES: tuple[TableSpec, ...]


def spec_for_name(name: str) -> TableSpec: ...
