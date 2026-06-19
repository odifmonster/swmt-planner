from typing import Any, Callable

__all__ = ['FilterPopup']


class FilterPopup:
    def __init__(
        self, column: str, col_type: str,
        unique_getter: Callable[[], list | None],
        on_apply: Callable[[str, Any], None],
        parent: Any = ...,
    ) -> None: ...
