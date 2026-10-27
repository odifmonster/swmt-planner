from typing import Any

import pandas as pd

DEFAULT_STATUS: str


def floor_status_map(floor_status: pd.DataFrame) -> dict[tuple[str, int], str]: ...
def gen_inventory(
    active: pd.DataFrame,
    assigned: pd.DataFrame,
    floor_status: pd.DataFrame,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]: ...
