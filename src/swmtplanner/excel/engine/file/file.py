#!/usr/bin/env python

from collections import namedtuple

Pos = namedtuple('Pos', ['line', 'column'])

class File:

    def __init__(self, buffer):
        self._buffer = buffer
        self._lines: list[str] = ['']
        self._line_num = 0
        self._col_num = 0
        self._offset = 0

    def read(self):
        if self._line_num == len(self._lines) - 1 and \
            self._col_num == len(self._lines[self._line_num]):
            c = self._buffer.read(1)
            self._lines[self._line_num] += c
        else:
            c = self._lines[self._line_num][self._col_num]

        if len(c) == 1:
            self._col_num += 1
            self._offset += 1

            if c == '\n':
                self._col_num = 0
                self._line_num += 1
                if self._line_num == len(self._lines):
                    self._lines.append('')
        
        return c
    
    def backup(self, n: int):
        if n > self._offset:
            raise RuntimeError(f'Cannot backup file at position {self._offset} by' + \
                               f' {n} characters')
        
        self._offset -= n

        while n > 0:
            if self._col_num == 0:
                self._line_num -= 1
                self._col_num = len(self._lines[self._line_num])
            
            to_sub = min(n, self._col_num)
            n -= to_sub
            self._col_num -= to_sub
    
    def tell(self):
        return Pos(self._line_num + 1, self._col_num + 1)