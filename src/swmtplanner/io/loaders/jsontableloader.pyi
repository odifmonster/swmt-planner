from dataclasses import dataclass
from datetime import date

import pandas as pd

from .sources import JSONFile
from .tableloader import TableLoader

@dataclass(frozen=True)
class JSONTableLoader(TableLoader):
    """
    Loads a ``Table`` from a ``JSONFile`` with ``pd.read_json``, passing
    along the file's ``orient``.

    When ``orient`` is ``"index"`` (a JSON object keyed by row) the keys
    are made available as a source column named ``index``, which a
    ``Table`` can pick up with ``src_name='index'``. Keys are kept as the
    strings they are in the file.

    :raises TypeError: on construction if ``source`` is not a
        ``JSONFile``.
    """

    source: JSONFile

    def load(self, cfg: dict, dt: date | None = None,
             override_name: str | None = None) -> pd.DataFrame:
        """
        Resolve the file's path with ``source.get_fpath(cfg,
        override_name, dt)`` (a dated file defaults to today; an
        ``override_name`` replaces the file name entirely), read it, and
        convert the result.
        """
        ...
