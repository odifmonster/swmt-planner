#!/usr/bin/env python

from .. import file
from . import tokens
from ._tokenize import tokenize

class TStream:
    """Reads a file as a stream of tokens."""

    __slots__ = ('_tokens', '_tokenizer', '_idx', '_ended')

    def __init__(self, f: file.File) -> None:
        self._tokens = []
        self._tokenizer = tokenize(f)
        self._idx = 0
        self._ended = False

    @property
    def has_ended(self) -> bool:
        return self._ended

    @property
    def last_token(self) -> tokens.Token:
        return self._tokens[-1]

    def advance(self) -> tokens.Token:
        idx = self._idx
        if idx < len(self._tokens):
            tok = self._tokens[idx]
        elif self._ended:
            raise EOFError("cannot advance past end of token stream")
        else:
            tok = next(self._tokenizer)
            self._tokens.append(tok)
            if tok.kind == tokens.EOF:
                self._ended = True

        self._idx = idx + 1
        return tok

    def backup(self, n: int) -> None:
        if n < 0:
            raise ValueError(f"backup amount must be non-negative, got {n}")
        if n > 0:
            self._ended = False
        self._idx = max(0, self._idx - n)
