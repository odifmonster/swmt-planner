#!/usr/bin/env python

from typing import Protocol, TYPE_CHECKING
from abc import abstractmethod


def _cls_name(x) -> str:
    return x.__class__.__name__


class HasID[T](Protocol):

    def __eq__(self, value: 'HasID[T]'):
        return _cls_name(self) == _cls_name(value) and self.id == value.id
    
    def __hash__(self):
        return hash(self.id)
    
    def __repr__(self):
        return f'{_cls_name(self)}(id={self.id!r})'
    
    @property
    @abstractmethod
    def id(self) -> T:
        raise NotImplementedError('implementers of HasID must provide an \'id\' implementation')