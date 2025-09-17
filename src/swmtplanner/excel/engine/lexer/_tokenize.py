#!/usr/bin/env python

from ..file import File
from .tokens import TokType, Token

REGULAR, SKIP_NL, SKIP_IND = 0, 1, 2

def _unexpected_err(f: File, c: str):
    pos = f.tell()
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

def _next_ws(f: File, value: str, kind: TokType):
    c = f.read()
    if c == ' ':
        return _next_ws(f, value+c, kind)
    if len(c) == 1:
        f.backup()
    return kind, value

def _next_comment(f: File, value: str):
    c = f.read()
    if len(c) == 0 or c == '\n':
        if len(c) == 1:
            f.backup()
        return TokType.COMMENT, value
    return _next_comment(f, value+c)

def _next_dash(f: File, value: str):
    c = f.read()
    if c == '>':
        return TokType.ARROW, value+c
    if len(c) == 1:
        f.backup()
    return TokType.MINUS, value

def _next_float(f: File, value: str, at_start = False):
    c = f.read()
    if _is_num(c):
        return _next_float(f, value+c)
    if c == '.':
        if at_start:
            f.backup()
            raise _unexpected_err(f, c)
        return _next_ext(f, value+c, at_start=True)
    if _is_alpha(c):
        return _next_name(f, value+c, kind=TokType.STRING)
    if len(c) == 1:
        f.backup()
    if at_start:
        raise _unexpected_err(f, c)
    return TokType.FLOAT, value

def _next_dots(f: File, value: str):
    c = f.read()
    if c == '.':
        return TokType.ELLIPSIS, value+c
    if len(c) == 1:
        f.backup()
    raise _unexpected_err(f, c)

def _next_dot(f: File, value: str):
    c = f.read()
    if c == '.':
        return _next_dots(f, value+c)
    if _is_num(c):
        return _next_float(f, value+c, at_start=True)
    if len(c) == 1:
        f.backup()
    return TokType.DOT, value

def _next_ref(f: File, value: str):
    c = f.read()
    if _is_alpha(c):
        return _next_ref(f, value+c)
    if len(c) == 1:
        f.backup()
    if len(value) == 1:
        raise _unexpected_err(f, c)
    return TokType.REF, value

def _escaped_char(f: File):
    c = f.read()
    if len(c) == 0 or c in ('\n', '\t', '\r'):
        if len(c) == 1:
            f.backup()
        raise _unexpected_err(f, c)
    if c in ('n', 't', 'r'):
        match c:
            case 'n': return '\n'
            case 't': return '\t'
            case 'r': return '\r'
    return c

def _next_string(f: File, value: str):
    c = f.read()
    if len(c) == 0 or c == '\n':
        if len(c) == 1:
            f.backup()
        raise _unexpected_err(f, c)
    if c == '"':
        return TokType.STRING, value+c
    if c == '\\':
        c = _escaped_char(f)
    return _next_string(f, value+c)

def _next_ext(f: File, value: str, at_start = False):
    c = f.read()
    if _is_alpha_num(c):
        return _next_ext(f, value+c)
    if c == '.':
        if at_start:
            f.backup()
            raise _unexpected_err(f, c)
        return _next_ext(f, value+c, at_start=True)
    if len(c) == 1:
        f.backup()
    if at_start:
        raise _unexpected_err(f, c)
    return TokType.STRING, value

def _next_name(f: File, value: str, kind: TokType = TokType.NAME):
    c = f.read()
    if _is_alpha_num(c):
        return _next_name(f, value+c, kind=kind)
    if c == '.':
        return _next_ext(f, value+c, at_start=True)
    if len(c) == 1:
        f.backup()
    return kind, value

def _next_int(f: File, value: str):
    c = f.read()
    if _is_num(c):
        return _next_int(f, value+c)
    if c == '.':
        return _next_float(f, value+c)
    if _is_alpha(c):
        return _next_name(f, value+c, TokType.STRING)
    if len(c) == 1:
        f.backup()
    return TokType.INT, value

def _raw_tokens(f: File):
    tok_map = {
        '[': TokType.LBRACK, ']': TokType.RBRACK, '(': TokType.LPAREN,
        ')': TokType.RPAREN, ':': TokType.COLON, ',': TokType.COMMA,
        '=': TokType.EQ, '+': TokType.PLUS, '*': TokType.STAR,
        '/': TokType.SLASH, '%': TokType.MOD
    }

    kw_map = {
        'use': TokType.USE, 'from': TokType.FROM, 'to': TokType.TO
    }

    while True:
        pos = f.tell()
        c = f.read()

        if len(c) == 0:
            yield Token(TokType.NEWLINE, '', pos)
            yield Token(TokType.RAW_INDENT, '', pos)
            yield Token(TokType.END, '', pos)
            return
        
        if c in tok_map:
            kind, value = tok_map[c], c
        elif c == '0':
            kind, value = _next_name(f, c, kind=TokType.STRING)
        elif _is_alpha(c):
            kind, value = _next_name(f, c)
        elif _is_num(c):
            kind, value = _next_int(f, c)
        else:
            match c:
                case '-':
                    kind, value = _next_dash(f, c)
                case '.':
                    kind, value = _next_dot(f, c)
                case '$':
                    kind, value = _next_ref(f, c)
                case '#':
                    kind, value = _next_comment(f, c)
                case ' ':
                    kind, value = _next_ws(f, c, TokType.WS)
                case '\n':
                    yield Token(TokType.NEWLINE, c, pos)
                    pos = f.tell()
                    kind, value = _next_ws(f, '', TokType.RAW_INDENT)
                case '"':
                    kind, value = _next_string(f, c)
                case _:
                    f.backup()
                    raise _unexpected_err(f, c)
        
        if kind == TokType.NAME and value in kw_map:
            kind = kw_map[value]
        
        yield Token(kind, value, pos)

def tokenize(f: File):
    toks = filter(lambda t: t.kind not in (TokType.COMMENT, TokType.WS),
                  _raw_tokens(f))
    indentation = [0]
    state = REGULAR
    nxt = None

    while True:
        if nxt is not None:
            cur = nxt
        else:
            cur = next(toks)

        nxt = None
        nxt_state = state

        if cur.kind == TokType.END:
            yield cur
            return
        
        if cur.kind == TokType.ELLIPSIS:
            if state == REGULAR:
                nxt_state = SKIP_NL
            else:
                msg = f'Line {cur.start.line} at column {cur.start.column}'
                msg += f': Unexpected {cur.kind.name.lower()} token '
                msg += f'({repr(cur.value)})'
                raise SyntaxError(msg)
        elif cur.kind == TokType.NEWLINE and state == SKIP_NL:
            state = SKIP_IND
            continue
        elif state == SKIP_IND:
            nxt_state = REGULAR
            if cur.kind == TokType.RAW_INDENT:
                state = nxt_state
                continue
        
        if cur.kind == TokType.RAW_INDENT:
            cur_ind = len(cur.value)
            nxt = next(toks)
            if nxt.kind in (TokType.NEWLINE, TokType.END):
                continue
            
            if cur_ind > indentation[-1]:
                indentation.append(cur_ind)
                yield Token(TokType.INDENT, '', cur.start)
            elif cur_ind < indentation[-1]:
                while cur_ind < indentation[-1]:
                    indentation.pop()
                    yield Token(TokType.DEDENT, '', cur.start)
                if cur_ind != indentation[-1]:
                    msg = f'Line {cur.start.line} at column {cur.start.column}'
                    msg += f': Bad indentation'
                    raise SyntaxError(msg)
        else:
            yield cur