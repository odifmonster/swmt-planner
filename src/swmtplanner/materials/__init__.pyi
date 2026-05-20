from datetime import date
from typing import Literal

from ..support import HasID
from . import product as product
from .product import Product, Greige


__all__ = ['product', 'RawMat', 'GreigeRoll', 'RollSize']


RollSize = Literal['partial', 'half', 'small', 'full', 'large']


class RawMat(HasID[str]):
    """Abstract base for a consumable quantity/unit of raw material.

    Carries the physical-inventory ID, the product this material is an
    instance of, the consumable quantity, and the availability date.
    Subclasses extend with stage-specific metadata (e.g., `GreigeRoll`).
    """
    def __init__(
        self,
        id_: str,
        product: Product,
        qty: float,
        avail_date: date | None,
    ) -> None:
        """Build a RawMat.

        `id_` is the physical-inventory ID, distinct from `product.id`
        (the SKU). `avail_date` is the date this material first becomes
        available; `None` means it is already in physical inventory.
        """
        ...
    @property
    def id(self) -> str:
        """Physical-inventory ID."""
        ...
    @property
    def product(self) -> Product:
        """The product this quantity is an instance of."""
        ...
    @property
    def qty(self) -> float:
        """Consumable quantity (units depend on the product)."""
        ...
    @property
    def avail_date(self) -> date | None:
        """Date this material first becomes available; `None` if already in inventory."""
        ...


class GreigeRoll(RawMat):
    """`RawMat` subclass representing a single roll of greige fabric.

    Adds the metadata needed for dye-cycle compatibility checks. `size` is
    derived at construction from `qty` and `product.roll_tgt_wt`.

    `id` should begin with a two-letter plant code: `"FS"` for rolls from
    Fairystone, `"WF"` for rolls from Whiteville Fabrics.
    """
    def __init__(
        self,
        id_: str,
        product: Greige,
        qty: float,
        avail_date: date | None,
        plant: str,
        item_variant: str,
        yarn_merge: str,
    ) -> None:
        """Build a GreigeRoll.

        `size` is computed from `qty / product.roll_tgt_wt` and is not a
        constructor parameter.
        """
        ...
    @property
    def product(self) -> Greige:
        """The `Greige` item this roll is an instance of."""
        ...
    @property
    def plant(self) -> str:
        """Knitting plant the roll came from. Used by the planner for dye-cycle matching."""
        ...
    @property
    def item_variant(self) -> str:
        """Roll's item variant. Reported to the end user only; not used for matching."""
        ...
    @property
    def yarn_merge(self) -> str:
        """Roll's yarn merge. Reported to the end user only; not used for matching."""
        ...
    @property
    def size(self) -> RollSize:
        """Discrete size bucket derived from `qty / product.roll_tgt_wt`."""
        ...
    def split(self, lbs1: float, lbs2: float) -> tuple[GreigeRoll, GreigeRoll]:
        """Split this roll into two rolls of weights `lbs1` and `lbs2`.

        The two new rolls inherit `product`, `avail_date`, `plant`,
        `item_variant`, and `yarn_merge` from this roll. Their IDs are
        this roll's ID suffixed with `'A'` and `'B'` respectively.

        Raises `ValueError` if `lbs1 + lbs2` is not approximately equal
        to this roll's `qty`.
        """
        ...
    def combine(self, roll: GreigeRoll) -> GreigeRoll:
        """Combine this roll with `roll` to produce a single combined roll.

        The combined roll's `id` is the concatenation of the two source
        rolls' IDs (this roll first). `item_variant` and `yarn_merge` are
        each concatenated only when the two source values differ; if both
        rolls share the same `item_variant` (or `yarn_merge`), that
        single value is kept on the combined roll. `qty` is the sum.
        `avail_date` is the later of the two (with `None` treated as
        already-available).

        Raises `ValueError` if the two rolls come from different plants
        or are instances of different greige items.
        """
        ...
