#!/usr/bin/env python

from abc import abstractmethod
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from typing import Hashable


class HasID[T: 'Hashable'](Protocol):

    def __eq__(self, value: 'HasID[T]'):
        return self.prefix == value.prefix and self.id == value.id
    
    def __hash__(self):
        return hash(self.id)
    
    def __repr__(self):
        return f'{self.prefix}(id={repr(self.id)})'

    @property
    def prefix(self) -> str:
        return self.__class__.__name__
    
    @property
    @abstractmethod
    def id(self) -> T:
        raise NotImplementedError()