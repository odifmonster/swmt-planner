#!/usr/bin/env python

import datetime as _dt
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class File:
    cfg_name: str
    stem: str
    ext: str
    date_fmt: str | None = None

    def get_fpath(self, cfg: dict, override_name: str | None = None,
                  date: _dt.date | None = None) -> str:
        folder = cfg[self.cfg_name]
        if override_name is not None:
            name = override_name
        elif self.date_fmt is None:
            name = self.stem + self.ext
        else:
            if date is None:
                date = _dt.date.today()
            name = self.stem.format(date.strftime(self.date_fmt)) + self.ext
        return os.path.join(folder, name)


@dataclass(frozen=True)
class CSVFile(File):
    sep: str = ','


@dataclass(frozen=True)
class ExcelFile(File):
    ext: str = '.xlsx'
    sheet_name: str | int = 0
    header: int | None = 0
    skiprows: int | None = None
    nrows: int | None = None
    skipfooter: int = 0


@dataclass(frozen=True)
class JSONFile(File):
    ext: str = '.json'
    orient: str = 'records'
