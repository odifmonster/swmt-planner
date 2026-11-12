from dataclasses import dataclass
from datetime import date

import pandas as pd

from .sources import CSVFile
from .tableloader import TableLoader

@dataclass(frozen=True)
class CSVTableLoader(TableLoader):
    """
    Loads a ``Table`` from a ``CSVFile`` with ``pd.read_csv``, passing
    along the file's ``sep``.

    :raises TypeError: on construction if ``source`` is not a ``CSVFile``.
    """

    source: CSVFile

    def load(self, cfg: dict, dt: date | None = None,
             override_name: str | None = None) -> pd.DataFrame:
        """
        Resolve the file's path with ``source.get_fpath(cfg,
        override_name, dt)`` (a dated file defaults to today; an
        ``override_name`` replaces the file name entirely), read it, and
        convert the result.
        """
        ...
