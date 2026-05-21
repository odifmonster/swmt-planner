from abc import abstractmethod
from typing import Protocol, Hashable, Callable


def get_int_id_counter() -> Callable[[], int]:
    """Get a function for creating auto-incremented int ids."""
    ...


def get_str_id_counter(prefix: str, padding: int = 5) -> Callable[[], str]:
    """Get a function for creating string ids using a padded int and a prefix."""
    ...


class HasID[T: Hashable](Protocol):
    """Simple protocol for defining custom IDs on objects. Classes
    that implement HasID use the id property for equality checks and
    hashing."""
    def __eq__(self, value: HasID[T]) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...
    @property
    def prefix(self) -> str:
        """Ensures instances of different classes don't evaluate as equal."""
        ...
    @property
    @abstractmethod
    def id(self) -> T: ...