#!/usr/bin/env python

from typing import Protocol
from abc import abstractmethod

class Observer[T](Protocol):

    @abstractmethod
    def update(self, value: T):
        raise NotImplementedError()