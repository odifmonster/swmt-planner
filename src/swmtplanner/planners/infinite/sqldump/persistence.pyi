from typing import Any, Iterator

from swmtplanner.debuglog import DebugLog

from swmtplanner.dashboard.config import ConnConfig
from ..manifest import TableSpec

__all__ = ['persist_run', 'PersistenceError']


class PersistenceError(RuntimeError): ...


def to_sql(value: Any) -> Any: ...
def insert_sql(spec: TableSpec) -> str: ...
def project_rows(
    debuglog: DebugLog, spec: TableSpec, run_id: int,
) -> Iterator[tuple]: ...
def persist_run(
    debuglog: DebugLog, conn: ConnConfig, *,
    start_date: Any, total_score: Any, n_unmet: Any,
    label: str | None = ..., notes: str | None = ...,
) -> int: ...
