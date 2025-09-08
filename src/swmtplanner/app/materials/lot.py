#!/usr/bin/env python

from typing import Protocol
from enum import Enum, auto
from abc import abstractmethod

from swmtplanner.support import HasID

class Status(Enum):
    ARRIVED = auto()
    PLANNED = auto()
    NEW = auto()

class Lot[T, U, S](HasID[T], Protocol):

    @property
    @abstractmethod
    def status(self):
        raise NotImplementedError()
    
    @property
    @abstractmethod
    def received(self):
        raise NotImplementedError()
    
    @property
    @abstractmethod
    def rawmat(self):
        raise NotImplementedError()
    
    @property
    @abstractmethod
    def product(self):
        raise NotImplementedError()
    
    @property
    @abstractmethod
    def qty(self):
        raise NotImplementedError()
    
    @property
    @abstractmethod
    def start(self):
        raise NotImplementedError()
    
    @property
    @abstractmethod
    def fin(self):
        raise NotImplementedError()
    
    @abstractmethod
    def view(self):
        raise NotImplementedError()
    
class LotView[T, U, S](Protocol):

    @property
    def prefix(self):
        raise NotImplementedError()
    
    @property
    def id(self):
        raise NotImplementedError()

    @property
    def status(self):
        raise NotImplementedError()
    
    @property
    def received(self):
        raise NotImplementedError()
    
    @property
    def rawmat(self):
        raise NotImplementedError()
    
    @property
    def product(self):
        raise NotImplementedError()
    
    @property
    def qty(self):
        raise NotImplementedError()
    
    @property
    def start(self):
        raise NotImplementedError()
    
    @property
    def fin(self):
        raise NotImplementedError()