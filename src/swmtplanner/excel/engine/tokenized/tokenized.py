#!/usr/bin/env python

from .tokens import TokType
from ._tokenize import tokenize

class Tokenized:

    def __init__(self, file):
        self._file = file
        self._tok_stream = tokenize(file)
        self._prev = []
        self._idx = 0
        self._ended = False

    @property
    def ended(self):
        return self._ended
    
    @property
    def last_tok(self):
        if not self._prev:
            raise AttributeError('FATAL: something unexpected occurred')
        return self._prev[-1]
    
    def advance(self):
        if self._idx < len(self._prev):
            ret = self._prev[self._idx]
        else:
            try:
                ret = next(self._tok_stream)
                self._prev.append(ret)
                if ret.kind == TokType.END:
                    self._file.close()
            except StopIteration:
                raise RuntimeError('FATAL: something unexpected occurred')
        
        self._idx += 1
        self._ended = ret.kind == TokType.END
        return ret
    
    def backup(self, n: int):
        if n > self._idx:
            raise RuntimeError(f'cannot back up token stream at position {self._idx} ' + \
                               f'by {n} tokens')
        self._idx -= n
        if n > 0:
            self._ended = False