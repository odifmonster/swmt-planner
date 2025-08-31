#!/usr/bin/env python

from typing import NamedTuple

from ..lexer import TokType

class Atom(NamedTuple):
    kind: TokType
    value: str

class KWArg(NamedTuple):
    name: str
    value: Atom | list[Atom]

class Info(NamedTuple):
    name: str
    kwargs: list[KWArg]

class Empty:
    pass