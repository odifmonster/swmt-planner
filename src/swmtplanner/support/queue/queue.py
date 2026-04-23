#!/usr/bin/env python

import bisect

from swmtplanner.support import SwmtBase

class Queue(SwmtBase, read_only=tuple(),
            priv=('items','keys','key_func')):
    
    def __init__(self, key_func):
        super().__init__(_items=[], _keys=[], _key_func=key_func)

    def __len__(self):
        return len(self._items)
    
    def __bool__(self):
        return bool(self._items)
    
    def put(self, item):
        k = self._key_func(item)
        idx = bisect.bisect_right(self._keys, k)
        self._items.insert(idx, item)
        self._keys.insert(idx, k)

    def get(self):
        if not self._items:
            raise IndexError('Cannot get from an empty queue')
        self._keys.pop()
        return self._items.pop()
    
    def peek(self):
        if not self._items:
            raise IndexError('Cannot peek at an empty queue')
        return self._items[-1]