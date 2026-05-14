#!/usr/bin/env python

from abc import abstractmethod

class LinkedList:

    def __init__(self):
        self._prev: 'LinkedList | None' = None
        self._next: 'LinkedList | None' = None

    def __len__(self):
        if self.nxt is None:
            return 1
        return 1 + len(self.nxt)

    @property
    def prev(self):
        return self._prev
    
    @property
    def nxt(self):
        return self._next
    
    def append(self, node: 'LinkedList'):
        if self._next is not None:
            raise ValueError('cannot append node to middle of list')
        self._next = node
        node._prev = self
    
    def get(self, i: int):
        if i < 0:
            raise IndexError('cannot use negative indexing on linked list')
        
        if i == 0:
            return self
        
        if self._next is None:
            raise IndexError('index out of bounds')
        
        return self.nxt.get(i - 1)