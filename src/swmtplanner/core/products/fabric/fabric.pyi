from dataclasses import dataclass

from ....support import HasID
from ..greige import Greige
from .dyeformula import DyeFormula

@dataclass(frozen=True, eq=False)
class Fabric(HasID[str]):
    """
    An immutable finished (dyed and finished) fabric product: a greige
    style dyed with a particular dye formula to a finished width. The
    relationship from greige style to fabric style is one to many.

    Equality and hashing are by ``id``.
    """

    id: str
    """The fabric item code:
    ``FF <style name>-<dye formula number>-<finished width>``."""
    greige_style: Greige
    """The greige style this fabric is made from."""
    master_style: str
    """The master style name for this fabric."""
    color: DyeFormula
    """The dye formula this fabric is dyed with."""
    width: float
    """Finished width."""
    yld: float
    """Yield, in yards per pound."""
    jets: tuple[str, ...]
    """The ids of all the jets that can run this fabric."""

    def can_run_on_jet(self, j_id: str) -> bool:
        """Whether this fabric can be dyed on the jet with id ``j_id``,
        i.e. whether ``j_id`` is in ``jets``."""
        ...
