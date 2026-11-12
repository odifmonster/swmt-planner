from dataclasses import dataclass
from typing import Any, Callable

@dataclass(frozen=True)
class Column:
    """
    An immutable description of one column of a ``Table``: where it comes
    from in the source, what it is called once loaded, and how its values
    are converted on the way.
    """

    name: str
    """The column's name in the resulting pandas ``DataFrame``."""
    dtype: str
    """The string name of the pandas datatype the column is converted to
    (e.g. ``"int64"``, ``"float64"``, ``"string"``, ``"boolean"``)."""
    src_name: str | None = None
    """The column's name in the source. ``None`` means the same as
    ``name``."""
    converter: Callable[[Any], Any] | None = None
    """Optional single-argument function applied to each source value
    before it is handed to pandas. Runs after ``read_na_as``
    substitution."""
    read_na_as: Any | None = None
    """Optional value substituted for null, NaN, or ``None`` source
    values."""
