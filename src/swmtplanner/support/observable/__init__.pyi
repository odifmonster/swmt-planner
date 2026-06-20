from typing import Protocol
from abc import abstractmethod


__all__ = ['Observer', 'Observable']


class Observer[T](Protocol):
    """Simple protocol for observer objects."""
    @abstractmethod
    def update(self, value: T) -> None:
        """Called by the observed class when updated."""
        ...


class Observable[T]:
    """Simple observable base class."""
    def __init__(self) -> None: ...
    def subscribe(self, obs: Observer[T]) -> None:
        """Subscribe the given object to this observable's updates."""
        ...
    def publish(self, value: T) -> None:
        """Publish a new value to all observers."""
        ...