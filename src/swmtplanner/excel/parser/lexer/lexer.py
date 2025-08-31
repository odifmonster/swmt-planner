#!/usr/bin/env python

from ..file import CharStream, FilePos
from .token import TokType, Token

def _is_alpha(c):
    if len(c) == 0:
        return False
    return c == '_' or (ord('a') <= ord(c) <= ord('z')) or \
        (ord('A') <= ord(c) <= ord('Z'))

def _is_num(c):
    if len(c) == 0:
        return False
    return ord('0') <= ord(c) <= ord('9')

def _is_alpha_num(c):
    if len(c) == 0:
        return False
    return _is_alpha(c) or _is_num(c)

def _format_file_pos(pos: FilePos):
    return f'Line {pos.line} at column {pos.line_offset+1}'

def _get_unexpected_err(f: CharStream, c):
    msg = _format_file_pos(f.get_pos())+':'
    if len(c) == 1:
        msg += f' Unexpected character {repr(c)}'
    else:
        msg += ' Unexpected end of file'
    return SyntaxError(msg)

def _next_ws(f: CharStream, value, start: FilePos):
    c = f.read()

    if c == ' ':
        if len(value) == 3:
            return Token(TokType.INDENT, value+c, start)
        return _next_ws(f, value+c, start)
    
    if len(c) == 1:
        f.backup()
    return Token(TokType.WS, value, start)

def _next_dot(f: CharStream, value, start: FilePos):
    c = f.read()

    if c == '.':
        if len(value) == 2:
            return Token(TokType.ELLIPSIS, value+c, start)
        return _next_dot(f, value+c, start)
    
    if len(c) == 1:
        f.backup()
    raise _get_unexpected_err(f, c)

def _special_char(f: CharStream, value):
    c = f.read()

    if c == '\n' or len(c) == 0:
        if len(c) == 1:
            f.backup()
        raise _get_unexpected_err(f, c)
    if c in ('t','n','r'):
        return value+c
    return c

def _next_string(f: CharStream, value, start: FilePos):
    c = f.read()

    if c == '\n' or len(c) == 0:
        if len(c) == 1:
            f.backup()
        msg = _format_file_pos(f.get_pos())+':'
        msg += ' Unclosed string'
        raise SyntaxError(msg)
    
    if c == '"':
        return Token(TokType.STRING, value+c, start)
    
    if c == '\\':
        c = _special_char(f, c)

    return _next_string(f, value+c, start)

def _next_comment(f: CharStream, value, start: FilePos):
    c = f.read()

    if c == '\n' or len(c) == 0:
        if len(c) == 1:
            f.backup()
        return Token(TokType.COMMENT, value, start)
    return _next_comment(f, value+c, start)

def _next_file(f: CharStream, value, start: FilePos):
    c = f.read()

    if _is_alpha(c):
        return _next_file(f, value+c, start)
    if c == '.':
        return _next_ext_start(f, value+c, start)
    
    if len(c) == 1:
        f.backup()
    return Token(TokType.FILE, value, start)

def _next_ext_start(f: CharStream, value, start: FilePos):
    c = f.read()

    if _is_alpha(c):
        return _next_file(f, value+c, start)
    
    if len(c) == 1:
        f.backup()
    raise _get_unexpected_err(f, c)

def _next_name(f: CharStream, value, start: FilePos):
    c = f.read()

    if _is_alpha_num(c):
        return _next_name(f, value+c, start)
    if c == '.':
        return _next_ext_start(f, value+c, start)
    
    if len(c) == 1:
        f.backup()
    return Token(TokType.NAME, value, start)

def _next_num(f: CharStream, value, start: FilePos):
    c = f.read()

    if _is_num(c):
        return _next_num(f, value+c, start)
    if _is_alpha(c):
        return _next_name(f, value+c, start)
    if c == '.':
        return _next_ext_start(f, value+c, start)
    
    if len(c) == 1:
        f.backup()
    return Token(TokType.NUM, value, start)

def get_toks(f: CharStream):
    yield Token(TokType.START, 'START', FilePos(0, 0, 0))
    while True:
        pos = f.get_pos()
        c = f.read()
        if not c:
            return
        
        if c in ('\n', ':', ',', '='):
            match c:
                case '\n':
                    kind = TokType.NEWLINE
                case ':':
                    kind = TokType.COLON
                case ',':
                    kind = TokType.COMMA
                case '=':
                    kind = TokType.EQUALS
            yield Token(kind, c, pos)
            continue

        if c == '0' or _is_alpha(c):
            func = _next_name
        elif _is_num(c):
            func = _next_num
        else:
            match c:
                case ' ':
                    func = _next_ws
                case '.':
                    func = _next_dot
                case '"':
                    func = _next_string
                case '#':
                    func = _next_comment
                case _:
                    if len(c) == 1:
                        f.backup()
                    raise _get_unexpected_err(f, c)
        
        tok = func(f, c, pos)
        yield tok