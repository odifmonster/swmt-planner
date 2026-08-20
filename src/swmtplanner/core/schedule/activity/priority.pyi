__all__ = ['Priority']


class Priority:
    """A small mutable holder that gives an otherwise frozen record one
    settable value: the frozen record stores a reference to a Priority, and
    the priority's value can be changed without mutating the record."""
    def __init__(self, value: int | str | None) -> None:
        """Initialize with the given value, validated like the setter."""
        ...
    @property
    def value(self) -> int | str | None:
        """The priority value: an int demand week offset, 'S' (safety), or
        None (the cleared state — no requirement filled)."""
        ...
    @value.setter
    def value(self, value: int | str | None) -> None:
        """Set the priority value. The only valid string is 'S'; any other
        string raises ValueError."""
        ...
