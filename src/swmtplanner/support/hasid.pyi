class HasID[T]:
    """
    Lightweight generic base class for objects identified by an ``id`` of
    type ``T``.

    Lets the same logical object be reconstructed many times, from
    different sources, and still be recognized as the same object: two
    instances of the same class are equal if and only if their ids are
    equal, and equal instances hash equally.

    Subclasses declare what their ``id`` is, either as a dataclass field or
    as a property computed from other fields. Dataclass subclasses must be
    declared with ``eq=False`` so that the generated field-wise ``__eq__``
    and ``__hash__`` do not override the id-based ones inherited from here.
    """

    id: T
    """The identifying value. Declared by the subclass."""

    def __eq__(self, other: object) -> bool:
        """
        ``True`` if and only if ``other`` is an instance of the same class
        as ``self`` and ``other.id == self.id``.
        """
        ...

    def __hash__(self) -> int:
        """``hash(self.id)``."""
        ...
