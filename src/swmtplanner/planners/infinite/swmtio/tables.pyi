from datetime import datetime
from typing import Any

from .translate import Table

STRING_DTYPE: str
COUNT_DTYPE: str
NUMBER_DTYPE: str


def utc_to_plant(value: Any) -> datetime | None: ...
def to_number(value: Any) -> float | None: ...
def to_string(value: Any) -> str | None: ...
def norm_machine(value: Any) -> str | None: ...


ACTIVE: Table
ASSIGNED: Table
DOFFED: Table
THREADED: Table
LAST_TKT: Table
SCANNED: Table
ALL_VARIANTS: Table

FLOOR_STATUS: Table
MACHINE_STATUS: Table
RACKS: Table

__all__: list[str]
