#!/usr/bin/env python

from typing import NamedTuple
from enum import Enum, auto

from ..file import FilePos

class TokType(Enum):
    START = auto()
    END = auto()
    NEWLINE = auto()
    WS = auto()
    INDENT = auto()
    STAR = auto()
    EQUALS = auto()
    COLON = auto()
    COMMA = auto()
    ELLIPSIS = auto()
    VARNAME = auto()
    NAME = auto()
    FILE = auto()
    NUMBER = auto()
    STRING = auto()
    COMMENT = auto()

class Token(NamedTuple):
    kind: TokType
    value: str
    start: FilePos