from typing import Protocol, Hashable
from abc import abstractmethod

__all__ = ['HasID']

class HasID[T: Hashable](Protocol):
    def __eq__(self, value) -> bool: ...
    def __hash__(self) -> int: ...
    @abstractmethod
    @property
    def prefix(self) -> str: ...
    @abstractmethod
    @property
    def id(self) -> T: ...