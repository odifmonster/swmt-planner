#!/usr/bin/env python

from collections import namedtuple
from typing import NewType

_BuffInd = NewType('_BuffInd', str)
EOF = _BuffInd('EOF')

Pos = namedtuple('Pos', ['line', 'col'])

class File:

    def __init__(self, path):
        self._buffer = open(path)
        self._lines = []
        self._line_idx = 0
        self._col_idx = 0
        self._has_ended = False

    @property
    def has_ended(self):
        return self._has_ended

    def read(self):
        if self._has_ended:
            raise EOFError("cannot read past end of file")
        while True:
            if self._line_idx < len(self._lines):
                line = self._lines[self._line_idx]
                if self._col_idx == len(line):
                    if self._line_idx + 1 < len(self._lines):
                        raise RuntimeError('something very bad happened')
                    self._has_ended = True
                    self._col_idx += 1
                    return EOF
                char = line[self._col_idx]
                self._col_idx += 1
                if self._col_idx == len(line) and line[-1] == '\n':
                    self._line_idx += 1
                    self._col_idx = 0
                return char
            else:
                line = self._buffer.readline()
                if not line:
                    self._has_ended = True
                    if self._lines and self._lines[-1][-1] != '\n':
                        self._line_idx -= 1
                        self._col_idx = len(self._lines[-1])
                    return EOF
                self._lines.append(line)

    def backup(self, n):
        if n < 0:
            raise ValueError(f"backup amount must be non-negative, got {n}")
        if n == 0:
            return
        self._has_ended = False
        remaining = n
        while remaining > 0:
            if self._col_idx >= remaining:
                self._col_idx -= remaining
                return
            remaining -= self._col_idx
            if self._line_idx == 0:
                self._col_idx = 0
                return
            self._line_idx -= 1
            self._col_idx = len(self._lines[self._line_idx])

    def tell(self):
        return Pos(line=self._line_idx + 1, col=self._col_idx + 1)
