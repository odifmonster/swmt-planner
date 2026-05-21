#!/usr/bin/env python

from abc import abstractmethod
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from typing import Hashable


def get_int_id_counter():
    ctr = 0
    def func():
        nonlocal ctr
        ctr += 1
        return ctr
    return func


def get_str_id_counter(prefix: str, padding = 5):
    ctr = 0
    fmt_str = '{0}{1:0' + str(padding) + '}'
    def func():
        nonlocal ctr
        ctr += 1
        return fmt_str.format(prefix, ctr)
    return func


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