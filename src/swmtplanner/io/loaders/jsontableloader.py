#!/usr/bin/env python

from dataclasses import dataclass
from datetime import date

import pandas as pd

from .sources import JSONFile
from .tableloader import TableLoader


@dataclass(frozen=True)
class JSONTableLoader(TableLoader):
    source: JSONFile

    def __post_init__(self) -> None:
        if not isinstance(self.source, JSONFile):
            raise TypeError(f'JSONTableLoader source must be a JSONFile, got {type(self.source).__name__}')

    def load(self, cfg: dict, dt: date | None = None,
             override_name: str | None = None) -> pd.DataFrame:
        path = self.source.get_fpath(cfg, override_name, dt)
        raw = pd.read_json(path, orient=self.source.orient, convert_axes=False)
        if self.source.orient == 'index':
            raw = raw.reset_index()
        return self._convert(raw)
