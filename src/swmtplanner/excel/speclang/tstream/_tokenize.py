#!/usr/bin/env python

from .. import file
from . import tokens
from .tokens import Token

def _unexpected_char(pos: file.Pos, c: str):
    msg = f'Line {pos.line} at column {pos.col}: Unexpected '
    if c != file.EOF:
        if c == '\n':
            msg += 'newline'
        else:
            msg += f'character {repr(c)}'
    else:
        msg += f'end of file'
    return SyntaxError(msg)

def _is_alpha(c: str):
    return c != file.EOF and ('a' <= c <= 'z' or 'A' <= c <= 'Z' or c == '_')

def _is_num(c: str):
    return c != file.EOF and ('0' <= c <= '9')

def _is_alpanum(c: str):
    return _is_alpha(c) or _is_num(c)

def _get_single_tok(c: str):
    TOK_MAP = {
        '[': tokens.LBRACK, ']': tokens.RBRACK,
        '(': tokens.LPAREN, ')': tokens.RPAREN, ':': tokens.COLON,
        ',': tokens.COMMA, '=': tokens.EQ, '*': tokens.STAR,
        '/': tokens.SLASH, '%': tokens.PCT, '+': tokens.PLUS
    }
    if c in TOK_MAP:
        return TOK_MAP[c]
    return None

def _next_arrow(f: file.File, prev: str, start: file.Pos):
    c = f.read()
    if c == '>':
        return Token(tokens.ARROW, prev+c, start)
    f.backup(1)
    return Token(tokens.MINUS, prev, start)

def _next_ellipsis(f: file.File, prev: str, start: file.Pos):
    c = f.read()
    if c == '.':
        if len(prev) < 2:
            return _next_ellipsis(f, prev+c, start)
        return Token(tokens.ELLIPSIS, prev+c, start)
    if len(prev) > 1:
        f.backup(1)
        raise _unexpected_char(f.tell(), c)
    if _is_num(c):
        return _next_float(f, prev+c, start)
    f.backup(1)
    return Token(tokens.DOT, prev, start)

def _next_comment(f: file.File, prev: str, start: file.Pos):
    c = f.read()
    if c == '\n' or c == file.EOF:
        f.backup(1)
        return Token(tokens.COMMENT, prev, start)
    return _next_comment(f, prev+c, start)

def _get_escaped_char(f: file.File):
    c = f.read()
    if c == '\n' or c == file.EOF:
        f.backup(1)
        raise _unexpected_char(f.tell(), c)
    match c:
        case 'n':
            return '\n'
        case 't':
            return '\t'
        case 'r':
            return '\r'
        case _:
            return c

def _next_string(f: file.File, prev: str, start: file.Pos):
    c = f.read()
    if c == '\n' or c == file.EOF:
        f.backup(1)
        raise _unexpected_char(f.tell(), c)
    if c == '"':
        return Token(tokens.STRING, prev+c, start)
    if c == '\\':
        c = _get_escaped_char(f)
    return _next_string(f, prev+c, start)

def _next_name(f: file.File, prev: str, start: file.Pos):
    c = f.read()
    if not _is_alpanum(c):
        f.backup(1)
        if prev == 'to':
            return Token(tokens.TO, prev, start)
        return Token(tokens.NAME, prev, start)
    return _next_name(f, prev+c, start)

def _next_float(f: file.File, prev: str, start: file.Pos):
    c = f.read()
    if _is_num(c):
        return _next_float(f, prev+c, start)
    if c == '.':
        f.backup(1)
        raise _unexpected_char(f.tell(), c)
    f.backup(1)
    return Token(tokens.FLOAT, prev, start)

def _next_int(f: file.File, prev: str, start: file.Pos):
    c = f.read()
    if _is_num(c):
        if prev == '0':
            f.backup(1)
            raise _unexpected_char(f.tell(), c)
        return _next_int(f, prev+c, start)
    if c == '.':
        return _next_float(f, prev+c, start)
    f.backup(1)
    return Token(tokens.INT, prev, start)

def _next_ws(f: file.File, prev: str, start: file.Pos, kind: str):
    c = f.read()
    if c == ' ':
        return _next_ws(f, prev+c, start, kind)
    f.backup(1)
    return Token(kind, prev, start)

def _tokenize_pass1(f: file.File):
    while True:
        pos = f.tell()
        c = f.read()

        single = _get_single_tok(c)
        if not single is None:
            yield Token(single, c, pos)
            continue

        if c == file.EOF:
            yield Token(tokens.NEWLINE, '\n', pos)
            yield Token(tokens.RAW_INDENT, '', pos)
            yield Token(tokens.EOF, c, pos)
            return
        
        match c:
            case '-':
                func = _next_arrow
            case '.':
                func = _next_ellipsis
            case '#':
                func = _next_comment
            case '"':
                func = _next_string
            case ' ':
                func = lambda x, y, z: _next_ws(x, y, z, tokens.WS)
            case '\n':
                yield Token(tokens.NEWLINE, c, pos)
                c = ''
                pos = f.tell()
                func = lambda x, y, z: _next_ws(x, y, z, tokens.RAW_INDENT)
            case _:
                if _is_alpha(c):
                    func = _next_name
                elif _is_num(c):
                    func = _next_int
                else:
                    raise _unexpected_char(pos, c)
        
        yield func(f, c, pos)

def _tokenize_pass2(f: file.File):
    toks = filter(lambda t: t.kind not in (tokens.COMMENT, tokens.WS), _tokenize_pass1(f))
    nxt = None

    while True:
        if nxt is None:
            cur = next(toks)
        else:
            cur = nxt
            nxt = None

        if cur.kind == tokens.ELLIPSIS:
            newline = next(toks)
            if newline.kind != tokens.NEWLINE:
                msg = f'Line {newline.start.line} at column {newline.start.col}: '
                msg += f'unexpected {newline.kind.lower()} token after ellipsis '
                msg += repr(newline.raw)
                raise SyntaxError(msg)
            indent = next(toks)
            if indent.kind != tokens.RAW_INDENT:
                raise RuntimeError('something very bad happened')
            continue

        if cur.kind == tokens.RAW_INDENT:
            nxt = next(toks)
            if nxt.kind == tokens.NEWLINE:
                nxt = None
                continue

        yield cur
        
        if cur.kind == tokens.EOF:
            return

def tokenize(f: file.File):
    toks = _tokenize_pass2(f)
    level = [0]

    while True:
        cur = next(toks)

        if cur.kind == tokens.RAW_INDENT:
            if len(cur.raw) == level[-1]: continue
            if len(cur.raw) > level[-1]:
                level.append(len(cur.raw))
                yield Token(tokens.INDENT, '', cur.start)
                continue
            else:
                while len(cur.raw) < level[-1]:
                    level.pop()
                    yield Token(tokens.DEDENT, '', cur.start)
                if len(cur.raw) != level[-1]:
                    msg = f'Line {cur.start.line} at column {cur.start.col}: bad indentation'
                    raise SyntaxError(msg)
                continue

        yield cur

        if cur.kind == tokens.EOF:
            return