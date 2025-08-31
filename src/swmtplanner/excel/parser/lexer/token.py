#!/usr/bin/env python

from typing import NamedTuple
from enum import Enum, auto

from ..file import FilePos

class TokType(Enum):
    START = auto()
    INDENT = auto()
    WS = auto()
    NEWLINE = auto()
    STRING = auto()
    NUM = auto()
    NAME = auto()
    FILE = auto()
    COLON = auto()
    EQUALS = auto()
    COMMA = auto()
    ELLIPSIS = auto()
    COMMENT = auto()

    def __repr__(self):
        return self.name
    
class Token(NamedTuple):
    kind: TokType
    value: str
    start: FilePos