from typing import Any

import pandas as pd

NEW_LINE: tuple[str, ...]
FALLBACK_GROUPS: tuple[tuple[int, ...], tuple[int, ...]]
DEFAULT_STATUS: str


def is_new(machine: str) -> bool: ...
def bar_groups(
    variants: pd.DataFrame, style: Any,
) -> tuple[tuple[int, ...], tuple[int, ...]] | None: ...
def gen_machines(
    runout: dict[str, dict[int, dict[str, Any]]],
    machine_status: pd.DataFrame,
    racks: pd.DataFrame,
    variants: pd.DataFrame,
) -> list[dict[str, Any]]: ...
