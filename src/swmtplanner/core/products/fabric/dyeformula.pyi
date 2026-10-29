from dataclasses import dataclass

from ....support import HasID
from .shade import Shade

@dataclass(frozen=True, eq=False)
class DyeFormula(HasID[int]):
    """
    An immutable dye formula.

    Equality and hashing are by ``id``.
    """

    id: int
    """The dye formula number (the number that appears in a fabric item
    code)."""
    name: str
    """The formula's name."""
    shade: Shade
    """The shade category of the formula."""
