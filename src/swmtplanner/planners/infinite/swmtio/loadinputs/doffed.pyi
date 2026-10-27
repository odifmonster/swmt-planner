from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd


@dataclass
class Roll:
    machine: str
    ticket: str
    style: str | None
    racks: float | None
    rack_wt: float | None
    start: datetime
    end: datetime | None

    @property
    def lbs(self) -> float | None: ...
    def record(self) -> dict[str, Any]: ...


def gen_doffed(doffed: pd.DataFrame, tkts_since: pd.DataFrame) -> dict[str, list[dict[str, Any]]]: ...
