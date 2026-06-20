from typing import Protocol, Hashable
from abc import abstractmethod


class HasID[T: Hashable](Protocol):
    """Simple protocol for defining hash and equality behavior on complex
    objects."""
    def __eq__(self, value: HasID[T]) -> bool: ...
    def __hash__(self) -> int: ...
    def __repr__(self) -> str: ...
    @property
    @abstractmethod
    def id(self) -> T:
        """The unique, hashable identifier of this object."""
        ...