from dataclasses import dataclass
from datetime import date


class QueryArgumentError(ValueError): ...


@dataclass(frozen=True)
class SQLQuery:
    raw_str: str
    num_args: int
    date_fmt: str | None

    def get_query(self, *args: date) -> str: ...


DATETIMEFROMPARTS_FMT: str

ACTIVE: SQLQuery
ASSIGNED: SQLQuery
DOFFED: SQLQuery
THREADED: SQLQuery
LAST_TKT: SQLQuery
SCANNED: SQLQuery
ALL_VARIANTS: SQLQuery

__all__: list[str]
