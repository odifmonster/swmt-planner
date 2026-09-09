from dataclasses import dataclass
from typing import Any, Collection, Literal

__all__ = ['Filter', 'FKLookup', 'FilterError', 'LIKE_ESCAPE']

FilterKind = Literal['selection', 'exclusion', 'range', 'pattern']

LIKE_ESCAPE: str


class FilterError(ValueError): ...


@dataclass
class Filter:
    kind: FilterKind
    rule: Any
    def to_sql_str(self) -> str: ...


@dataclass
class FKLookup:
    ref_table: str
    ref_col: str
    vals: Collection[Any]
    def to_sql_str(self) -> str: ...
