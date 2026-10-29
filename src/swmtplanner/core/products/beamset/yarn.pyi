from dataclasses import dataclass

from ....support import HasID
from .yarnattrs import YarnAttrs

MATERIAL_CODES: dict[str, str]
"""
The valid ``Yarn.material`` values and the one-letter code each
contributes to ``Yarn.id``: ``P`` polyester, ``N`` nylon, ``L`` lycra,
``S`` spandex, ``A`` acetate, ``E`` eptfe.
"""

COLOR_CODES: dict[str, str]
"""
The valid ``Yarn.color`` values and the two-letter code each contributes
to ``Yarn.id``: ``WT`` white, ``GY`` grey, ``BK`` black, ``GB`` greener
black (a recycled solution-dyed black).
"""

LUSTER_CODES: dict[str, str]
"""
The valid ``Yarn.luster`` values and the one-letter code each contributes
to ``Yarn.id``: ``D`` dull, ``S`` semi-dull, ``B`` bright, ``C`` clear.
"""

@dataclass(frozen=True, eq=False)
class Yarn(HasID[str]):
    """
    An immutable master yarn. A ``Yarn`` stands for every vendor merge that
    shares its properties; two merges that resolve to the same ``Yarn`` are
    interchangeable.

    Equality and hashing are by ``id``.

    :raises ValueError: on construction if ``material``, ``color``, or
        ``luster`` is not a key of its code map.
    """

    denier: int
    """Nominal denier as prescribed by the vendor (not a measurement)."""
    material: str
    """A key of ``MATERIAL_CODES``."""
    color: str
    """A key of ``COLOR_CODES``."""
    luster: str
    """A key of ``LUSTER_CODES``. Dull and semi-dull yarn are not
    interchangeable."""
    attrs: YarnAttrs
    """Additional distinguishing attributes."""

    @property
    def id(self) -> str:
        """
        ``<denier><material code><color code><luster code><2-digit
        attribute code>``, e.g. ``75PWTS04`` for a 75 denier semi-dull
        textured white polyester and ``75PWTD04`` for its dull counterpart.
        """
        ...

@dataclass(frozen=True, eq=False)
class Merge(HasID[str]):
    """
    An immutable, vendor-specific merge of a yarn. A merge is what the
    database calls a yarn item. Where ``Yarn`` identifies interchangeable
    yarn regardless of source, ``Merge`` identifies a particular vendor's
    version of it.

    Equality and hashing are by ``id``.
    """

    id: str
    """The vendor's item code. No specific format."""
    yarn: Yarn
    """The master yarn this merge is of."""
    vendor: str
    """The vendor supplying this merge."""
