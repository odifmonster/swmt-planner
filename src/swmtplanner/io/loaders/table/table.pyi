from dataclasses import dataclass

from .column import Column

@dataclass(frozen=True)
class Table:
    """
    An immutable description of a generic table: its name and the columns
    it is made of. How it is filled from a source is the job of a
    ``TableLoader``.
    """

    name: str
    """The table's name."""
    columns: tuple[Column, ...]
    """The columns to load, in order."""
    index: Column | None = None
    """Optionally, the column to use as the ``DataFrame`` index. ``None``
    means the frame keeps a default integer index."""
