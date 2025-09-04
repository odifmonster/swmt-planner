#!/usr/bin/env python

from .tokens import TokType
from .get_tokens import tokenize

class Lexer:

    def __init__(self, buffer):
        self._stream = filter(lambda t: t.kind not in (TokType.COMMENT, TokType.WS),
                              tokenize(buffer))
        self._prev_toks = []
        self._idx = 0
        self._ended = False

    def _skip_ellipses(self, curtok):
        msg = 'Line {} at column {}: {}'
        line = curtok.start.line
        column = curtok.start.column + len(curtok.value)

        try:
            nl = next(self._stream)
            line = nl.start.line + 1
            column = 1
            if nl.kind != TokType.NEWLINE:
                raise SyntaxError(msg.format(nl.start.line, nl.start.column,
                                             'expected newline after ellipsis'))
            
            ind = next(self._stream)
            if ind.kind == TokType.END:
                raise SyntaxError(msg.format(ind.start.line, ind.start.column,
                                             'unexpected end of file'))
            if ind.kind != TokType.INDENT:
                return ind
            
            line = ind.start.line
            column = ind.start.column + len(ind.value)
            return next(self._stream)
        except StopIteration:
            raise RuntimeError(msg.format(line, column, 'unfinished stream'))

    def __iter__(self):
        return self
    
    def __next__(self):
        if self._idx < len(self._prev_toks):
            ret = self._prev_toks[self._idx]
            self._idx += 1
            self._ended = ret.kind == TokType.END
            return ret
        
        tok = next(self._stream)
        while tok.kind == TokType.ELLIPSIS:
            tok = self._skip_ellipses(tok)
            
        self._prev_toks.append(tok)
        self._idx += 1
        self._ended = tok.kind == TokType.END
        return tok

    @property
    def ended(self):
        return self._ended
    
    def backup(self, n):
        if n > self._idx:
            raise ValueError(f'Cannot backup by {n} when stream position ' + \
                             f'is at {self._idx}')
        self._idx -= n