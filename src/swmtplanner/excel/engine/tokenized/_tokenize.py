#!/usr/bin/env python

from .. import file
from .tokens import TokType, Token

def _unexpected_char(pos: file.Pos, c: str):
    msg = f'Line {pos.line} at column {pos.column}: Unexpected '
    if len(c) == 1:
        if c == '\n':
            msg += 'newline'
        msg += f'character {repr(c)}'
    else:
        msg += f'end of file'
    return SyntaxError(msg)

def _is_alpha(c: str):
    return len(c) == 1 and (c == '_' or ord('a') <= ord(c) <= ord('z') or \
                            ord('A') <= ord(c) <= ord('Z'))

def _is_num(c: str):
    return len(c) == 1 and ord('0') <= ord(c) <= ord('9')

def _is_alpha_num(c: str):
    return _is_alpha(c) or _is_num(c)

def _next_float(f: file.File, value: str, start: file.Pos):
    c = f.read()
    if _is_num(c):
        return _next_float(f, value+c, start)
    if c == '.':
        f.backup(1)
        raise _unexpected_char(f.tell(), c)
    if len(c) == 1:
        f.backup(1)
    return Token(TokType.FLOAT, value, start)

def _next_int(f: file.File, value: str, start: file.Pos):
    c = f.read()
    if _is_num(c):
        if value == '0':
            f.backup(1)
            raise _unexpected_char(f.tell(), c)
        return _next_int(f, value+c, start)
    if c == '.':
        return _next_float(f, value+c, start)
    if len(c) == 1:
        f.backup(1)
    return Token(TokType.INT, value, start)

def _get_escaped_char(f: file.File):
    c = f.read()
    if len(c) == 0 or c in ('\n', '\t', '\r', ' '):
        if len(c) == 1:
            f.backup(1)
        raise _unexpected_char(f.tell(), c)
    match c:
        case 'n': return '\n'
        case 't': return '\t'
        case 'r': return '\r'
        case _: return c

def _next_string(f: file.File, value: str, start: file.Pos):
    c = f.read()
    if c == '"':
        return Token(TokType.STRING, value+c, start)
    if len(c) == 0 or c == '\n':
        if len(c) == 1:
            f.backup(1)
        raise _unexpected_char(f.tell(), c)
    if c == '\\':
        c = _get_escaped_char(f)
    return _next_string(f, value+c, start)

def _next_name(f: file.File, value: str, start: file.Pos):
    c = f.read()
    if _is_alpha_num(c):
        return _next_name(f, value+c, start)
    if len(c) == 1:
        f.backup(1)
    return Token(TokType.NAME, value, start)

def _next_dash(f: file.File, value: str, start: file.Pos):
    c = f.read()
    if c == '>':
        return Token(TokType.ARROW, value+c, start)
    if len(c) == 1:
        f.backup(1)
    return Token(TokType.MINUS, value, start)

def _next_comment(f: file.File, value: str, start: file.Pos):
    c = f.read()
    if len(c) == 0 or c == '\n':
        if len(c) == 1:
            f.backup(1)
        return Token(TokType.COMMENT, value, start)
    return _next_comment(f, value+c, start)

def _next_ws(f: file.File, value: str, start: file.Pos, kind: TokType):
    c = f.read()
    if c == ' ':
        return _next_ws(f, value+c, start, kind)
    if len(c) == 1:
        f.backup(1)
    return Token(kind, value, start)

def _next_dots(f: file.File, value: str, start: file.Pos):
    c = f.read()
    if c == '.':
        if len(value) == 2:
            return Token(TokType.ELLIPSIS, value+c, start)
        return _next_dots(f, value+c, start)
    if len(value) > 1:
        f.backup(1)
        raise _unexpected_char(f.tell(), c)
    if _is_num(c):
        return _next_float(f, value+c, start)
    if len(c) == 1:
        f.backup(1)
    return Token(TokType.DOT, value, start)

def _tokenize_pass1(f: file.File):
    tok_map = {
        '[': TokType.LBRACK, ']': TokType.RBRACK, '(': TokType.LPAREN,
        ')': TokType.RPAREN, ':': TokType.COLON, ',': TokType.COMMA,
        '=': TokType.EQ, '*': TokType.STAR, '/': TokType.SLASH, '%': TokType.PCT,
        '+': TokType.PLUS
    }
    keywords = {
        'use': TokType.USE, 'from': TokType.FROM, 'to': TokType.TO
    }

    while True:
        pos = f.tell()
        c = f.read()

        if len(c) == 0:
            yield Token(TokType.NEWLINE, '', pos)
            yield Token(TokType.RAW_INDENT, '', pos)
            yield Token(TokType.END, 'E', pos)
            return
        
        if c != ' ' and pos.line == 1 and pos.column == 1:
            yield Token(TokType.RAW_INDENT, '', pos)
        
        if c in tok_map:
            yield Token(tok_map[c], c, pos)
            continue

        if _is_alpha(c):
            func = _next_name
        elif _is_num(c):
            func = _next_int
        else:
            match c:
                case '-':
                    func = _next_dash
                case '.':
                    func = _next_dots
                case '#':
                    func = _next_comment
                case '"':
                    func = _next_string
                case ' ':
                    if pos.line == 1 and pos.column == 1:
                        func = lambda f, val, start: _next_ws(f, val, start,
                                                              TokType.RAW_INDENT)
                    else:
                        func = lambda f, val, start: _next_ws(f, val, start, TokType.WS)
                case '\n':
                    yield Token(TokType.NEWLINE, c, pos)
                    pos = f.tell()
                    c = ''
                    func = lambda f, val, start: _next_ws(f, val, start, TokType.RAW_INDENT)
                case _:
                    raise _unexpected_char(pos, c)
        
        tok = func(f, c, pos)
        if tok.kind == TokType.NAME and tok.value in keywords:
            tok = Token(keywords[tok.value], tok.value, tok.start)
        yield tok

def _tokenize_pass2(f: file.File):
    tok_stream = filter(lambda t: t.kind not in (TokType.COMMENT, TokType.WS),
                        _tokenize_pass1(f))
    nxt = None

    while True:
        if nxt is None:
            cur = next(tok_stream)
        else:
            cur = nxt
            nxt = None

        if cur.kind == TokType.END:
            yield cur
            return
        
        if cur.kind == TokType.ELLIPSIS:
            newline = next(tok_stream)
            if newline.kind != TokType.NEWLINE:
                msg = f'Line {newline.start.line} at column {newline.start.column}: '
                msg += f'Unexpected {newline.kind.name.lower()} token after ellipsis '
                msg += f'({repr(newline.value)})'
                raise SyntaxError(msg)
            indent = next(tok_stream)
            if indent.kind != TokType.RAW_INDENT:
                raise RuntimeError('FATAL: something unexpected occurred')
            continue

        if cur.kind == TokType.RAW_INDENT:
            nxt = next(tok_stream)
            if nxt.kind == TokType.NEWLINE:
                nxt = None
                continue
        
        yield cur

def tokenize(f: file.File):
    tok_stream = _tokenize_pass2(f)
    level = [0]

    while True:
        cur = next(tok_stream)

        if cur.kind == TokType.END:
            yield cur
            return
        
        if cur.kind == TokType.RAW_INDENT:
            if len(cur.value) == level[-1]: continue
            if len(cur.value) > level[-1]:
                level.append(len(cur.value))
                yield Token(TokType.INDENT, '', cur.start)
                continue
            else:
                while len(cur.value) < level[-1]:
                    level.pop()
                    yield Token(TokType.DEDENT, '', cur.start)
                if level[-1] != len(cur.value):
                    msg = f'Line {cur.start.line}: Bad indentation'
                    raise SyntaxError(msg)
                continue
        
        yield cur