#!/usr/bin/env python

from collections import namedtuple

Pos = namedtuple('Pos', ['line', 'column', 'file_offset'])

class File:

    def __init__(self, buffer):
        self._buffer = buffer
        self._line = 1
        self._column = 1
        self._prev_lines = []
        self._cur_line = ''
        self._file_off = 0

    def _read_prev(self):
        self._file_off += 1
        if self._line <= len(self._prev_lines):
            c = self._prev_lines[self._line - 1][self._column - 1]
            self._column += 1
            if self._column > len(self._prev_lines[self._line - 1]):
                self._line += 1
                self._column = 1
            return c
        c = self._cur_line[self._column - 1]
        self._column += 1
        return c

    def read(self):
        if self._line <= len(self._prev_lines) or self._column <= len(self._cur_line):
            return self._read_prev()
        
        c = self._buffer.read(1)
        if len(c) == 1:
            self._cur_line += c
            self._file_off += 1
            if c == '\n':
                self._prev_lines.append(self._cur_line)
                self._cur_line = ''
                self._line += 1
                self._column = 1
            else:
                self._column += 1
        return c
    
    def backup(self):
        if self._file_off == 0:
            raise RuntimeError('Cannot backup at start of file')
        
        self._file_off -= 1
        self._column -= 1
        if self._column < 1:
            self._line -= 1
            self._column = len(self._prev_lines[self._line - 1])

    def tell(self):
        return Pos(self._line, self._column, self._file_off)