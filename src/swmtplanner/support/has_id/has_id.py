#!/usr/bin/env python

from typing import Protocol
from abc import abstractmethod

class HasID[T](Protocol):

    def __eq__(self, value):
        if not (hasattr(value, 'prefix') and hasattr(value, 'id')):
            return super().__eq__(value)
        return self.prefix == value.prefix and self.id == value.id
    
    def __hash__(self):
        return hash(self.id)
    
    def __repr__(self):
        return f'{self.prefix}(id={repr(self.id)})'

    @property
    def prefix(self):
        return self.__class__.__name__
    
    @property
    @abstractmethod
    def id(self):
        raise NotImplementedError()