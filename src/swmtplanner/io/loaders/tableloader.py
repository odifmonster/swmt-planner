#!/usr/bin/env python

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd

from .table import Table, Column
from .sources import SQLQuery, File


@dataclass(frozen=True)
class TableLoader(ABC):
    tbl: Table
    source: SQLQuery | File

    @abstractmethod
    def load(self, *args, **kwargs) -> pd.DataFrame: ...

    def _convert_column(self, raw: pd.DataFrame, col: Column) -> pd.Series:
        src = col.src_name if col.src_name is not None else col.name
        if src not in raw.columns:
            raise KeyError(f'table {self.tbl.name!r}: column {src!r} not found in source')
        series = raw[src]
        if col.read_na_as is not None:
            series = series.mask(series.isna(), col.read_na_as)
        if col.converter is not None:
            series = series.map(col.converter)
        return series.astype(col.dtype)

    def _convert(self, raw: pd.DataFrame) -> pd.DataFrame:
        cols = list(self.tbl.columns)
        if self.tbl.index is not None:
            cols.append(self.tbl.index)
        out = pd.DataFrame({col.name: self._convert_column(raw, col) for col in cols})
        if self.tbl.index is not None:
            out = out.set_index(self.tbl.index.name)
        return out
