from typing import Protocol
from abc import abstractmethod

__all__ = ['Observer']

class Observer[T](Protocol):
    """Basic observer protocol."""
    @abstractmethod
    def update(self, value: T) -> None:
        """Update method for this observer."""
        ...