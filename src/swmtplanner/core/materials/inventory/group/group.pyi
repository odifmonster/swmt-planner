from abc import ABC, abstractmethod
from typing import Any

from ...rawmat import RawMat
from ..condition import Condition


__all__ = ['Group', 'ValGroup', 'SortedGroup']


class Group[T: RawMat](ABC):
    """Abstract base for the group types: tracks the RawMat objects relevant to
    one attribute so subsets can be pulled efficiently."""
    def __init__(self, attr: str) -> None: ...
    @property
    def attr(self) -> str:
        """The attribute this group is keyed on."""
        ...
    @abstractmethod
    def add(self, mat: T) -> None:
        """Add a RawMat to the group."""
        ...
    @abstractmethod
    def remove(self, id: str | int, val: Any) -> None:
        """Remove the RawMat with the given id, where val is that object's value
        for attr. Raises KeyError if no such material is found at val (which
        signals the grouping was broken by external mutation)."""
        ...
    @abstractmethod
    def get_group(self, cond: Condition) -> set[T]:
        """The set of RawMat objects matching the given Condition."""
        ...


class ValGroup[T: RawMat](Group[T]):
    """A group backed by a mapping of attribute values to sets of RawMat objects.
    Efficient for Exactly selections (direct keyed lookup)."""
    def __init__(self, attr: str) -> None: ...
    def add(self, mat: T) -> None: ...
    def remove(self, id: str | int, val: Any) -> None: ...
    def get_group(self, cond: Condition) -> set[T]: ...


class SortedGroup[T: RawMat](Group[T]):
    """A group backed by a list of RawMat objects sorted by the attribute.
    Efficient for the range conditions (Greater / Less / InRange)."""
    def __init__(self, attr: str) -> None: ...
    def add(self, mat: T) -> None: ...
    def remove(self, id: str | int, val: Any) -> None: ...
    def get_group(self, cond: Condition) -> set[T]: ...
