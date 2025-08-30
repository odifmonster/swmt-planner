#!/usr/bin/env python

from typing import Protocol
from abc import abstractmethod

class HasID[T](Protocol):

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, value):
        return self.prefix == value.prefix and self.id == value.id
    
    def __repr__(self):
        return f'{self.prefix}(id={repr(self.id)})'

    @property
    @abstractmethod
    def prefix(self):
        raise NotImplementedError()
    
    @property
    @abstractmethod
    def id(self):
        raise NotImplementedError()