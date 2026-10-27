from typing import Any

import pandas as pd

BARS: tuple[int, ...]


def parse_bars(text: Any) -> list[int]: ...
def racks_on_roll(racks: pd.DataFrame) -> dict[str, float]: ...
def compute_runout(
    threadings: pd.DataFrame,
    doffed: dict[str, list[dict[str, Any]]],
    racks: pd.DataFrame,
    variants: pd.DataFrame,
    last_tkt: pd.DataFrame,
    threaded: pd.DataFrame,
) -> dict[str, dict[int, dict[str, Any]]]: ...
