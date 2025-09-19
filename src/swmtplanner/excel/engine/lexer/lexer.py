#!/usr/bin/env python

from .tokens import TokType
from ._tokenize import tokenize

class Lexer:

    def __init__(self, f):
        _prev = None
        def skip_empty_lines(cur):
            nonlocal _prev
            if (_prev is None or _prev.kind == TokType.NEWLINE) and cur.kind == TokType.NEWLINE:
                ret = False
            else:
                ret = True
            _prev = cur
            return ret
        self._stream = filter(skip_empty_lines, tokenize(f))
        self._prev = []
        self._idx = 0
        self._ended = False
    
    @property
    def ended(self):
        return self._ended

    @property
    def last_tok(self):
        if not self._prev:
            raise RuntimeError('FATAL: something unexpected occurred')
        return self._prev[-1]
    
    def advance(self):
        if self._idx < len(self._prev):
            ret = self._prev[self._idx]
        else:
            ret = next(self._stream)
            self._prev.append(ret)

        self._idx += 1
        self._ended = ret.kind == TokType.END
        return ret
    
    def backup(self, n: int):
        if n > self._idx:
            raise RuntimeError('FATAL: something unexpected occurred')
        self._idx -= n
        if self.ended and n > 0:
            self._ended = False

    def reset(self):
        self._idx = 0