from typing import Protocol, Hashable
from abc import abstractmethod

__all__ = ['HasID']

class HasID[T: Hashable](Protocol):
    """
    A simple protocol for defining objects uniquely identified
    by ids not provided by the system.
    """
    def __hash__(self) -> int: ...
    def __eq__(self, value: 'HasID[T]') -> bool: ...
    def __repr__(self) -> str: ...
    @property
    @abstractmethod
    def prefix(self) -> str:
        """Used to distinguish between different HasID implementations."""
        ...
    @property
    @abstractmethod
    def id(self) -> T:
        """The unique, hashable id of this object."""
        ...