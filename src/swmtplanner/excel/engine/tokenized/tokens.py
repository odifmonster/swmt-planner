#!/usr/bin/env python

from collections import namedtuple
from enum import Enum, auto

class TokType(Enum):
    WS = auto()
    RAW_INDENT = auto()
    ELLIPSIS = auto()
    COMMENT = auto()
    NEWLINE = auto()
    INDENT = auto()
    DEDENT = auto()
    LBRACK = auto()
    RBRACK = auto()
    LPAREN = auto()
    RPAREN = auto()
    COLON = auto()
    COMMA = auto()
    ARROW = auto()
    DOT = auto()
    EQ = auto()
    STAR = auto()
    SLASH = auto()
    PCT = auto()
    PLUS = auto()
    MINUS = auto()
    INT = auto()
    FLOAT = auto()
    STRING = auto()
    NAME = auto()
    TO = auto()
    END = auto()

Token = namedtuple('Token', ['kind', 'value', 'start'])