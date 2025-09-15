#!/usr/bin/env python

from ..file import FilePos, CharStream
from .tokens import TokType, Token

def _unexpected_err(pos: FilePos, c: str):
    msg = f'Line {pos.line} at column {pos.column}: Unexpected '
    if len(c) == 0:
        msg += 'end of file'
    elif c == '\n':
        msg += 'end of line'
    else:
        msg += f'character {repr(c)}'
    return SyntaxError(msg)

def _is_alpha(c: str):
    return len(c) == 1 and (ord('a') <= ord(c) <= ord('z') or \
                            ord('A') <= ord(c) <= ord('Z') or c == '_')

def _is_num(c: str):
    return len(c) == 1 and ord('0') <= ord(c) <= ord('9')

def _is_alpha_num(c: str):
    return _is_alpha(c) or _is_num(c)

def _next_ws(f: CharStream, kind: TokType, value: str, start: FilePos):
    c = f.read()
    if c == ' ':
        return _next_ws(f, kind, value+c, start)
    
    if len(c) == 1:
        f.backup()
    
    if len(value) > 0:
        return kind, value, start
    return None, None, None

def _next_dots(f: CharStream, value: str, start: FilePos):
    c = f.read()
    
    if c == '.':
        if len(value) == 2:
            return TokType.ELLIPSIS, value+c, start
        return _next_dots(f, value+c, start)
    
    if len(c) == 1:
        f.backup()
    raise _unexpected_err(f.get_pos(), c)

def _next_ext(f: CharStream, value: str, start: FilePos):
    c = f.read()

    if _is_alpha(c):
        return _next_file(f, value+c, start)
    
    if len(c) == 1:
        f.backup()
    raise _unexpected_err(f.get_pos(), c)

def _next_file(f: CharStream, value: str, start: FilePos):
    c = f.read()

    if _is_alpha(c):
        return _next_file(f, value+c, start)
    if c == '.':
        return _next_ext(f, value+c, start)
    
    if len(c) == 1:
        f.backup()
    return TokType.FILE, value, start

def _next_varname2(f: CharStream, value: str, start: FilePos):
    c = f.read()

    if _is_alpha_num(c):
        return _next_varname2(f, value+c, start)
    
    if len(c) == 1:
        f.backup()
    return TokType.VARNAME, value, start

def _next_varname1(f: CharStream, value: str, start: FilePos):
    c = f.read()

    if _is_alpha(c):
        return _next_varname2(f, value+c, start)
    
    if len(c) == 1:
        f.backup()
    raise _unexpected_err(f.get_pos(), c)

def _next_name(f: CharStream, value: str, start: FilePos):
    c = f.read()

    if _is_alpha_num(c):
        return _next_name(f, value+c, start)
    if c == '.':
        return _next_ext(f, value+c, start)
    
    if len(c) == 1:
        f.backup()
    return TokType.NAME, value, start

def _next_number(f: CharStream, value: str, start: FilePos):
    c = f.read()

    if _is_num(c):
        return _next_number(f, value+c, start)
    if _is_alpha(c):
        return _next_name(f, value+c, start)
    if c == '.':
        return _next_ext(f, value+c, start)
    
    if len(c) == 1:
        f.backup()
    return TokType.NUMBER, value, start

def _escaped_char(f: CharStream, start: FilePos):
    c = f.read()

    if len(c) == 0 or c == '\n':
        if len(c) == 1:
            f.backup()
        raise _unexpected_err(f.get_pos(), c)
    match c:
        case 'n':
            return '\n'
        case 't':
            return '\t'
        case 'r':
            return '\r'
        case _:
            return c

def _next_string(f: CharStream, value: str, start: FilePos):
    c = f.read()

    if len(c) == 0 or c == '\n':
        if len(c) == 1:
            f.backup()
        raise _unexpected_err(f.get_pos(), c)
    if c == '\\':
        c = _escaped_char(f, start)
    elif c == '"':
        return TokType.STRING, value+c, start
    return _next_string(f, value+c, start)

def _next_comment(f: CharStream, value: str, start: FilePos):
    c = f.read()

    if len(c) == 0 or c == '\n':
        if len(c) == 1:
            f.backup()
        return TokType.COMMENT, value, start
    return _next_comment(f, value+c, start)

def tokenize(buffer):
    f = CharStream(buffer)
    yield Token(TokType.START, 'START', FilePos(1, 0, -1))

    tok_map = {
        '*': TokType.STAR, '=': TokType.EQUALS, ':': TokType.COLON,
        ',': TokType.COMMA
    }

    while True:
        pos = f.get_pos()
        c = f.read()
        
        if len(c) == 0:
            yield Token(TokType.END, 'END', pos)
            return

        if c in ('*', '=', ':', ',', '\n', ' ', '.', '$', '"', '#'):
            match c:
                case '*' | '=' | ':' | ',':
                    kind = tok_map[c]
                    value = c
                    start = pos
                case '\n':
                    yield Token(TokType.NEWLINE, c, pos)
                    kind, value, start = _next_ws(f, TokType.INDENT, '', f.get_pos())
                case ' ':
                    kind, value, start = _next_ws(f, TokType.WS, c, pos)
                case '.':
                    kind, value, start = _next_dots(f, c, pos)
                case '"':
                    kind, value, start = _next_string(f, c, pos)
                case '#':
                    kind, value, start = _next_comment(f, c, pos)
                case '$':
                    kind, value, start = _next_varname1(f, c, pos)
        elif c == '0' or _is_alpha(c):
            kind, value, start = _next_name(f, c, pos)
        elif _is_num(c):
            kind, value, start = _next_number(f, c, pos)
        else:
            raise _unexpected_err(pos, c)
        
        if kind is None: continue
        yield Token(kind, value, start)