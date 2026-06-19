from typing import Any

from ..manifest import TableSpec


def list_runs(cursor: Any, runs_spec: TableSpec) -> list[tuple]: ...


class RunButton:
    run_id: int
    def __init__(
        self, run_id: int, created_at: Any, start_date: Any,
        total_score: Any, parent: Any = ...,
    ) -> None: ...
    def set_selected(self, on: bool) -> None: ...


class RunSelectionPage:
    def __init__(
        self, cursor: Any, runs_spec: TableSpec, parent: Any = ...,
    ) -> None: ...
    def reload(self) -> None: ...
    def set_selected(self, run_id: int) -> None: ...
