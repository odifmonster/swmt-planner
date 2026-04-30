#!/usr/bin/env python

from typing import Protocol
from abc import abstractmethod

class HasID[T](Protocol):

    def __eq__(self, value: 'HasID'):
        return self.prefix == value.prefix and self.id == value.id
    
    def __hash__(self):
        return hash(self.id)

    @property
    @abstractmethod
    def prefix(self) -> str:
        raise NotImplementedError()
    
    @property
    @abstractmethod
    def id(self) -> T:
        raise NotImplementedError()