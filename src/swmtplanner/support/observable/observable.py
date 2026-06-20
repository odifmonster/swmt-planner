#!/usr/bin/env python

from typing import Protocol
from abc import abstractmethod


class Observer[T](Protocol):

    @abstractmethod
    def update(self, value: T) -> None:
        raise NotImplementedError()


class Observable[T]:

    def __init__(self):
        self._subscribers: list[Observer[T]] = []

    def subscribe(self, obs: Observer[T]):
        self._subscribers.append(obs)
    
    def publish(self, value: T):
        for obs in self._subscribers:
            obs.update(value)