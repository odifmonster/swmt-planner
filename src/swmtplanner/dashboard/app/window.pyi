from typing import Any

from ..manifest import TableSpec


class DashboardWindow:
    selected_run_id: int | None
    def __init__(
        self, cursor: Any, table_specs: list[TableSpec],
        runs_spec: TableSpec, parent: Any = ...,
    ) -> None: ...
