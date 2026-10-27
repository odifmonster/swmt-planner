from datetime import date
from typing import Any, Iterable, Sequence

import pandas as pd

from .translate import Table

SQLCONFIG_ENV: str
DRIVER: str
REQUIRED_KEYS: tuple[str, ...]
OPTIONAL_KEYS: tuple[str, ...]
DATE_STAMP_FMT: str
NA_VALUES: tuple[str, ...]


class SQLConfigError(ValueError): ...
class SourceColumnError(ValueError): ...


def parse_sql_config(lines: Iterable[str], source: str = ...) -> dict[str, str]: ...
def load_sql_config(fpath: str | None = ...) -> dict[str, str]: ...
def connection_string(cfg: dict[str, str]) -> str: ...
def align_rows(
    source_names: Sequence[str],
    rows: Iterable[Sequence[Any]],
    tbl: Table,
    source: str,
) -> list[tuple]: ...
def run_query(query_str: str, tbl: Table, cfgpath: str | None = ...) -> pd.DataFrame: ...
def read_csv(fpath: str, tbl: Table, sep: str = ...,
             na_values: Sequence[str] = ...) -> pd.DataFrame: ...
def get_file_name(stem: str, ext: str, dt: date | None = ...,
                  is_dated: bool = ...) -> str: ...
