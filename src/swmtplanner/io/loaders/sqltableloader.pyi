from dataclasses import dataclass

import pandas as pd
import pyodbc

from .sources import SQLQuery
from .tableloader import TableLoader

@dataclass(frozen=True)
class SQLTableLoader(TableLoader):
    """
    Loads a ``Table`` from a ``SQLQuery`` over a ``pyodbc`` connection.

    :raises TypeError: on construction if ``source`` is not a
        ``SQLQuery``.
    """

    source: SQLQuery

    def load(self, conn: pyodbc.Connection, *args, **kwargs) -> pd.DataFrame:
        """
        Build the query text with ``source.get_query(*args, **kwargs)``
        (so the date arguments and their defaults follow the ``SQLQuery``
        rules), run it over ``conn``, and convert the result.
        """
        ...
