#!/usr/bin/env python

from collections import namedtuple

WS = 'WS'
RAW_INDENT = 'RAW_INDENT'
ELLIPSIS = 'ELLIPSIS'
COMMENT = 'COMMENT'
NEWLINE = 'NEWLINE'
INDENT = 'INDENT'
DEDENT = 'DEDENT'
LBRACK = 'LBRACK'
RBRACK = 'RBRACK'
LPAREN = 'LPAREN'
RPAREN = 'RPAREN'
COLON = 'COLON'
COMMA = 'COMMA'
ARROW = 'ARROW'
DOT = 'DOT'
EQ = 'EQ'
STAR = 'STAR'
SLASH = 'SLASH'
PCT = 'PCT'
PLUS = 'PLUS'
MINUS = 'MINUS'
INT = 'INT'
FLOAT = 'FLOAT'
STRING = 'STRING'
NAME = 'NAME'
TO = 'TO'
EOF = 'EOF'

Token = namedtuple('Token', ['kind', 'raw', 'start'])