from dataclasses import dataclass
from datetime import datetime
from typing import Callable

type DefaultVal = None | Callable[[], datetime]
"""
A date parameter's default: a zero-argument callable producing the
datetime to use (evaluated when the query is built, not at import), or
``None`` meaning the parameter has no default and must be supplied.
"""

@dataclass(frozen=True)
class SQLQuery:
    """
    An immutable query against the SQL database whose text may contain
    places where date parameters must be inserted before it is run.

    :raises ValueError: on construction if the query has date parameters
        but no ``date_fmt``, or if ``defaults`` does not match the shape of
        ``date_params``.
    """

    raw_str: str
    """The query text, a Python ``str.format`` string with a placeholder
    for each date parameter: ``{0}``, ``{1}``, … for positional parameters,
    ``{name}`` for named ones."""
    date_params: int | tuple[str, ...]
    """The query's date parameters. An ``int`` gives the number of
    positional parameters; a tuple of strings gives the name of each
    parameter as it appears in the format string."""
    date_fmt: str | None = None
    """The ``strftime`` format used to render each datetime argument into
    the query text (e.g. ``"'%Y-%m-%d'"`` for a quoted SQL date literal).
    May be omitted only for a query with no parameters."""
    defaults: tuple[DefaultVal, ...] | tuple[tuple[str, DefaultVal], ...] = ()
    """Optional defaults. Positional form: one entry per parameter, in
    order. Named form: ``(name, default)`` pairs. Empty means no parameter
    has a default."""

    def get_query(self, *args: datetime | None, **kwargs: datetime | None) -> str:
        """
        Return the query text with every date parameter filled in.

        Call with positional arguments for positional ``date_params`` or
        keyword arguments for named ``date_params``. An argument that is
        omitted or ``None`` falls back to the parameter's default; with
        positional arguments, pass ``None`` at the position where the
        default should be used. Each resolved datetime is rendered with
        ``date_fmt`` and substituted with ``str.format``.

        :raises ValueError: if both positional and keyword arguments are
            given, if the form does not match ``date_params``, if too many
            or unknown arguments are given, or if a parameter has neither a
            value nor a default.
        """
        ...
