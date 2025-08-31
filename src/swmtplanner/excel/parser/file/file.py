#!/usr/bin/env python

from typing import NamedTuple
from io import TextIOBase

class FilePos(NamedTuple):
    line: int
    line_offset: int
    file_offset: int

class CharStream:

    def __init__(self, buffer: TextIOBase):
        self._buffer = buffer
        self._line = 1
        self._prev_line = None
        self._line_off = 1
        self._file_off = 0
    
    def read(self):
        c = self._buffer.read(1)
        if len(c) == 1:
            self._file_off += 1
            if c == '\n':
                self._prev_line = self._line_off
                self._line += 1
                self._line_off = 1
            else:
                self._line_off += 1
        return c
    
    def backup(self):
        if self._file_off == 0:
            raise RuntimeError('Cannot backup at start of stream')
        
        self._buffer.seek(self._file_off-1)
        self._file_off -= 1
        self._line_off -= 1
        
        if self._line_off < 1:
            if self._prev_line is None:
                raise RuntimeError('Backed up too many times')
            self._line_off = self._prev_line
            self._prev_line = None
            self._line -= 1
        
    def get_pos(self):
        return FilePos(self._line, self._line_off, self._file_off)