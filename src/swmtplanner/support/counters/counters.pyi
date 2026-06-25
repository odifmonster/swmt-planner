from typing import Callable


__all__ = ['mk_counter', 'Counters']


def mk_counter(start: int = ...) -> Callable[[], int]:
    """Make a new counter function starting at start."""
    ...


class Counters:
    """Simple class for tracking multiple counters in parallel."""

    def __init__(self, names: list[str] = [], **kwargs) -> None:
        """Initialize counters with names starting at 0 or with name-start
        pairs as keyword arguments."""
        ...
    def __call__(self, name: str, advance: bool = ...) -> int:
        """Call the given counter or get its last value. Default behavior
        calls the counter. Raises if trying to get the last value on a
        counter that has not been started."""
        ...
    @property
    def names(self) -> tuple[str, ...]:
        """The counter names in this object."""
        ...
