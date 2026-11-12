#!/usr/bin/env python

from dataclasses import dataclass
from datetime import date

import pandas as pd

from .sources import ExcelFile
from .tableloader import TableLoader


@dataclass(frozen=True)
class ExcelTableLoader(TableLoader):
    source: ExcelFile

    def __post_init__(self) -> None:
        if not isinstance(self.source, ExcelFile):
            raise TypeError(f'ExcelTableLoader source must be an ExcelFile, got {type(self.source).__name__}')

    def load(self, cfg: dict, dt: date | None = None,
             override_name: str | None = None) -> pd.DataFrame:
        path = self.source.get_fpath(cfg, override_name, dt)
        raw = pd.read_excel(path, sheet_name=self.source.sheet_name, header=self.source.header,
                            skiprows=self.source.skiprows, nrows=self.source.nrows,
                            skipfooter=self.source.skipfooter)
        return self._convert(raw)
