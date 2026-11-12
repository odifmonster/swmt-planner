from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd

from .table import Table, Column
from .sources import SQLQuery, File

@dataclass(frozen=True)
class TableLoader(ABC):
    """
    Abstract base for loading a ``Table`` from a source. All loading and
    conversion lives here: a loader reads the raw rows from its source and
    then converts them, column by column, into the frame the ``Table``
    describes. Subclasses differ only in how they read the raw rows.

    **Conversion.** For each ``Column`` in ``tbl.columns`` (and
    ``tbl.index``, if set):

    1. take the source column ``src_name`` (or ``name``) and call it
       ``name``;
    2. substitute ``read_na_as`` for every null/NaN/``None`` value, if
       given;
    3. apply ``converter`` to every value, if given;
    4. cast to ``dtype``.

    Source columns not listed in the ``Table`` are dropped silently. If
    ``tbl.index`` is set, that column becomes the frame's index.
    """

    tbl: Table
    """The table to load."""
    source: SQLQuery | File
    """Where to load it from; narrowed by each subclass."""

    @abstractmethod
    def load(self, *args, **kwargs) -> pd.DataFrame:
        """Read the raw rows from ``source`` and return the converted
        frame."""
        ...

    def _convert_column(self, raw: pd.DataFrame, col: Column) -> pd.Series:
        """
        Convert one column of the raw frame per the rules above.

        :raises KeyError: if the column's source name is not in ``raw``.
        """
        ...

    def _convert(self, raw: pd.DataFrame) -> pd.DataFrame:
        """
        Convert the raw frame into the frame ``tbl`` describes.

        :raises KeyError: if any listed column is missing from ``raw``.
        """
        ...
