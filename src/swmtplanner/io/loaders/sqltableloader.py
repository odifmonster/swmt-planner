#!/usr/bin/env python

from dataclasses import dataclass

import pandas as pd
import pyodbc

from .sources import SQLQuery
from .tableloader import TableLoader


@dataclass(frozen=True)
class SQLTableLoader(TableLoader):
    source: SQLQuery

    def __post_init__(self) -> None:
        if not isinstance(self.source, SQLQuery):
            raise TypeError(f'SQLTableLoader source must be a SQLQuery, got {type(self.source).__name__}')

    def load(self, conn: pyodbc.Connection, *args, **kwargs) -> pd.DataFrame:
        query = self.source.get_query(*args, **kwargs)
        raw = pd.read_sql(query, conn)
        return self._convert(raw)
