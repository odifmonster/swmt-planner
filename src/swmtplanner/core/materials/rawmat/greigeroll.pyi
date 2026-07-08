from datetime import datetime

from swmtplanner.core.product.greige import Greige
from .rawmat import RawMat


__all__ = [
    'GreigeRoll',
    'SMALL', 'STANDARD', 'LARGE',
    'DEFAULT_ROLL_WT', 'SINGLE_PORT_MAX', 'STD_SIZE_TOL',
]


# greige roll sizes (ordered smallest -> largest)
SMALL: int
STANDARD: int
LARGE: int

# size-classification parameters (may change in the future)
DEFAULT_ROLL_WT: int   # assumed target roll weight when the greige style is unknown
SINGLE_PORT_MAX: int   # target <= this -> single-port style; above -> double-port
STD_SIZE_TOL: int      # avg_port_wt within this of single_target counts as STANDARD


class GreigeRoll(RawMat):
    """A physical roll of greige fabric available to be dyed. Uses a str id and
    a unit of 'lbs'."""
    def __init__(self, id: str, sku: str, avail_date: datetime, qty: float,
                 plant: str, variant: str, yarn_merge: int,
                 greige: Greige | None) -> None: ...
    @property
    def id(self) -> str:
        """The roll's unique identifier."""
        ...
    @property
    def plant(self) -> str:
        """The plant the roll belongs to."""
        ...
    @property
    def variant(self) -> str:
        """The greige variant (how the roll is classified in inventory)."""
        ...
    @property
    def yarn_merge(self) -> int:
        """The yarn merge."""
        ...
    @property
    def greige(self) -> Greige | None:
        """The Greige style this roll is, or None for styles we don't knit /
        don't have data for."""
        ...
    @property
    def single_target(self) -> float:
        """The per-port target weight for the roll's style (tgt_wt, or half it for
        double-port styles; DEFAULT_ROLL_WT when greige is None)."""
        ...
    @property
    def n_ports(self) -> int:
        """The number of ports the roll spans: max(1, round(qty /
        single_target))."""
        ...
    @property
    def avg_port_wt(self) -> float:
        """The approximate pounds per port: qty / n_ports."""
        ...
    @property
    def size(self) -> int:
        """The roll size (SMALL / STANDARD / LARGE), from avg_port_wt vs. the
        per-port target."""
        ...
    def split(self, lbs1: float, lbs2: float) -> tuple[GreigeRoll, GreigeRoll]:
        """Split into two rolls of lbs1 and lbs2 pounds (appending 'A'/'B' to the
        id). Raises ValueError unless lbs1 + lbs2 is close to qty."""
        ...
    def combine(self, roll: GreigeRoll) -> GreigeRoll:
        """Combine with roll into one roll (ids joined by '/', pounds summed,
        latest avail_date, variants joined-or-same, yarn_merge same-or-(-1)).
        Raises ValueError unless roll shares this roll's sku and plant."""
        ...
