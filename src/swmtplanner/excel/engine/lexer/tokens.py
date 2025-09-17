#!/usr/bin/env python

from collections import namedtuple
from enum import Enum, auto

class TokType(Enum):
    LBRACK = auto()
    RBRACK = auto()
    LPAREN = auto()
    RPAREN = auto()
    COLON = auto()
    COMMA = auto()
    EQ = auto()
    DOT = auto()
    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    MOD = auto()
    ARROW = auto()
    ELLIPSIS = auto()
    USE = auto()
    FROM = auto()
    TO = auto()
    NAME = auto()
    REF = auto()
    INT = auto()
    FLOAT = auto()
    STRING = auto()
    COMMENT = auto()
    NEWLINE = auto()
    WS = auto()
    RAW_INDENT = auto()
    INDENT = auto()
    DEDENT = auto()
    END = auto()

Token = namedtuple('Token', ['kind', 'value', 'start'])