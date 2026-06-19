from typing import Any

from ..manifest import TableSpec


def message_page(text: str) -> Any: ...


class RawViewPage:
    def __init__(
        self, cursor: Any, specs: dict[str, TableSpec],
        back_refs: dict[str, tuple[tuple[str, str], ...]],
        parent: Any = ...,
    ) -> None: ...
    def show_table(self, spec: TableSpec, run_id: int) -> None: ...


class PrettyViewPage:
    def __init__(self, parent: Any = ...) -> None: ...
