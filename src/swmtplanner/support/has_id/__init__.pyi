from typing import Protocol, Hashable
from abc import abstractmethod

__all__ = ['HasID']

class HasID[T: Hashable](Protocol):
    """Basic protocol for custom equality checking by constructed identifier
    rather than default object equality."""
    def __eq__(self, value: 'HasID') -> bool: ...
    def __hash__(self) -> int: ...
    @property
    def prefix(self) -> str:
        """Returns the name of the instance's class. Prevents different types
        from being equal."""
        ...
    @property
    @abstractmethod
    def id(self) -> T: ...