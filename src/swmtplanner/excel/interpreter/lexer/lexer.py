#!/usr/bin/env python

from .tokens import TokType
from .get_tokens import tokenize

class Lexer:

    def __init__(self, buffer):
        self._stream = filter(lambda t: t.kind not in (TokType.COMMENT, TokType.WS),
                              tokenize(buffer))
        self._prev_toks = []
        self._idx = 0

    def __iter__(self):
        while True:
            if self._idx < len(self._prev_toks):
                yield self._prev_toks[self._idx]
                self._idx += 1
                continue

            try:
                tok = next(self._stream)
                self._prev_toks.append(tok)
                self._idx += 1
                yield tok
            except StopIteration:
                return
    
    def backup(self, n):
        if n > self._idx:
            raise ValueError(f'Cannot backup by {n} when stream position ' + \
                             f'is at {self._idx}')
        self._idx -= n