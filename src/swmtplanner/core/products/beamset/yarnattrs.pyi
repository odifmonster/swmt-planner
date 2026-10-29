from dataclasses import dataclass

@dataclass(frozen=True)
class YarnAttrs:
    """
    The additional attributes that distinguish otherwise-similar yarns.
    Yarns that differ in any of these are not interchangeable.

    The three fields are read as the bits of a binary number in field order
    (``textured`` most significant, ``recycled`` least) to give the yarn's
    two-digit attribute code; see ``__int__`` and ``from_int``.
    """

    textured: bool
    """Whether the yarn is textured."""
    cationic: bool
    """Whether the yarn is cationic."""
    recycled: bool
    """Whether the yarn is recycled (also called Repreve)."""

    @classmethod
    def from_int(cls, code: int) -> YarnAttrs:
        """
        Inverse of ``__int__``: build the attributes from an attribute code.

        :raises ValueError: if ``code`` is negative or too large for the
            number of attributes.
        """
        ...

    def __int__(self) -> int:
        """The attribute code for this set of attributes."""
        ...
