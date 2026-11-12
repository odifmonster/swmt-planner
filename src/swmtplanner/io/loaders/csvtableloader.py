#!/usr/bin/env python

from dataclasses import dataclass
from datetime import date

import pandas as pd

from .sources import CSVFile
from .tableloader import TableLoader


@dataclass(frozen=True)
class CSVTableLoader(TableLoader):
    source: CSVFile

    def __post_init__(self) -> None:
        if not isinstance(self.source, CSVFile):
            raise TypeError(f'CSVTableLoader source must be a CSVFile, got {type(self.source).__name__}')

    def load(self, cfg: dict, dt: date | None = None,
             override_name: str | None = None) -> pd.DataFrame:
        path = self.source.get_fpath(cfg, override_name, dt)
        raw = pd.read_csv(path, sep=self.source.sep)
        return self._convert(raw)
