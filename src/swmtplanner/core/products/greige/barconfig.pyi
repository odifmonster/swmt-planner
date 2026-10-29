from dataclasses import dataclass

@dataclass(frozen=True)
class BarConfig:
    """
    An immutable configuration of a single guide bar. Values are pulled
    largely directly from the database; any formatting and translation is
    done by whatever constructs it (the readers in ``swmtplanner.io``).

    Equality is field-wise.
    """

    num: int
    """The bar number."""
    runlen: float
    """Runner length."""
    pct: float
    """Percent of the style's weight contributed by this bar."""
    stitch: str
    """Stitch notation for the bar, e.g. ``"1/0,1/2"``."""
