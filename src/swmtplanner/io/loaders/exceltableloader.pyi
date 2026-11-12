from dataclasses import dataclass
from datetime import date

import pandas as pd

from .sources import ExcelFile
from .tableloader import TableLoader

@dataclass(frozen=True)
class ExcelTableLoader(TableLoader):
    """
    Loads a ``Table`` from an ``ExcelFile`` with ``pd.read_excel``,
    passing along the file's ``sheet_name``, ``header``, ``skiprows``,
    ``nrows``, and ``skipfooter``.

    :raises TypeError: on construction if ``source`` is not an
        ``ExcelFile``.
    """

    source: ExcelFile

    def load(self, cfg: dict, dt: date | None = None,
             override_name: str | None = None) -> pd.DataFrame:
        """
        Resolve the file's path with ``source.get_fpath(cfg,
        override_name, dt)`` (a dated file defaults to today; an
        ``override_name`` replaces the file name entirely), read it, and
        convert the result.
        """
        ...
