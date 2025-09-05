#!/usr/bin/env python

from ..lexer import TokType, Lexer
from .trees import Empty, AtomType, Atom, VarType, Variable, Attribute, Block

def _match_tok(tstream: Lexer, is_tgt, converter = None):
    if tstream.ended:
        return None, 0
    
    if type(is_tgt) is list:
        is_tgt_raw = is_tgt
        is_tgt = lambda t: t.kind in is_tgt_raw
    elif isinstance(is_tgt, TokType):
        is_tgt_raw = is_tgt
        is_tgt = lambda t: t.kind == is_tgt_raw

    if converter is None:
        converter = lambda t: Empty()
    
    tok = next(tstream)
    if not is_tgt(tok):
        tstream.backup(1)
        return None, 0
    return converter(tok), 1

def _match_empty(tstream: Lexer):
    total = 0

    res, consumed = _match_tok(tstream, TokType.START)
    total += consumed

    res, consumed = _match_tok(tstream, TokType.INDENT)
    total += consumed

    res, consumed = _match_tok(tstream, [TokType.NEWLINE, TokType.END])
    total += consumed

    if res is None:
        tstream.backup(total)
        return None, 0
    return Empty(), total

def _get_atom(tok):
    val = tok.value
    match tok.kind:
        case TokType.VARNAME:
            at_kind = AtomType.VARNAME
            val = tok.value[1:]
        case TokType.NAME:
            at_kind = AtomType.NAME
        case TokType.NUMBER:
            at_kind = AtomType.NUMBER
        case TokType.FILE:
            at_kind = AtomType.FILE
        case TokType.STRING:
            at_kind = AtomType.STRING
            val = tok.value[1:-1]
        case _:
            raise RuntimeError('FATAL: Don\'t do that')
    return Atom(at_kind, val)

def _match_value(tstream: Lexer):
    total = 0
    vals: list[Atom] = []

    res, consumed = _match_tok(tstream,
                               [TokType.VARNAME, TokType.NAME, TokType.NUMBER,
                                TokType.FILE, TokType.STRING], converter=_get_atom)
    total += consumed
    if res is None:
        return None, 0
    vals.append(res)

    while True:
        cur_cnsm = 0

        res, consumed = _match_tok(tstream, TokType.COMMA)
        cur_cnsm += consumed
        if res is None:
            break

        res, consumed = _match_tok(tstream,
                                   [TokType.VARNAME, TokType.NAME, TokType.FILE,
                                    TokType.NUMBER, TokType.STRING],
                                    converter=_get_atom)
        cur_cnsm += consumed
        if res is None:
            tstream.backup(cur_cnsm)
            break

        total += cur_cnsm
        vals.append(res)

    return vals, total

def _match_var_decl(tstream: Lexer):
    total = 0

    tups = [(TokType.START, None, True),
            (TokType.STAR, None, True),
            (TokType.NAME, lambda t: t.value, False),
            (TokType.EQUALS, None, False)]
    items = []
    
    for is_tgt, converter, is_opt in tups:
        res, consumed = _match_tok(tstream, is_tgt, converter=converter)
        total += consumed
        if res is None and not is_opt:
            tstream.backup(total)
            return None, 0
        items.append(res)

    star = items[1]
    name = items[2]

    if star is not None:
        match_func = _match_value
        kind = VarType.LIST
    else:
        match_func = lambda lxr: _match_tok(lxr,
                                            [TokType.VARNAME, TokType.NAME, TokType.FILE,
                                             TokType.NUMBER, TokType.STRING],
                                             converter=_get_atom)
        kind = VarType.NORMAL
    
    res, consumed = match_func(tstream)
    total += consumed
    if res is None:
        tstream.backup(total)
        return None, 0
    
    val = res

    res, consumed = _match_tok(tstream, [TokType.NEWLINE, TokType.END])
    total += consumed
    if res is None:
        tstream.backup(total)
        return None, 0
    
    return Variable(name, kind, val), total

def _match_block_attr(tstream: Lexer):
    total = 0

    while True:
        res, consumed = _match_empty(tstream)
        total += consumed
        if res is None:
            break

    tups = [(TokType.INDENT, None), (TokType.NAME, lambda t: t.value),
            (TokType.EQUALS, None)]
    items = []

    for is_tgt, converter in tups:
        res, consumed = _match_tok(tstream, is_tgt, converter=converter)
        total += consumed
        if res is None:
            tstream.backup(total)
            return None, 0
        items.append(res)

    name = items[1]

    res, consumed = _match_value(tstream)
    total += consumed
    if res is None:
        tstream.backup(total)
        return None, 0
    
    vals = res

    res, consumed = _match_tok(tstream, [TokType.NEWLINE, TokType.END])
    total += consumed
    if res is None:
        tstream.backup(total)
        return None, 0
    
    return Attribute(name, vals), total

def _match_block(tstream: Lexer):
    total = 0

    tups = [(TokType.START, None, True),
            (TokType.NAME, lambda t: t.value, False),
            (TokType.COLON, None, False),
            (TokType.NEWLINE, None, False)]
    items = []

    for is_tgt, converter, is_opt in tups:
        res, consumed = _match_tok(tstream, is_tgt, converter=converter)
        total += consumed
        if res is None and not is_opt:
            tstream.backup(total)
            return None, 0
        items.append(res)

    name = items[1]

    attrs: list[Attribute] = []

    while True:
        res, consumed = _match_block_attr(tstream)
        total += consumed
        if res is None:
            break
        attrs.append(res)

    return Block(name, attrs), total

def parse(buffer):
    tstream = Lexer(buffer)
    stmts: list[Block | Variable] = []

    while True:
        if tstream.ended:
            return stmts
        
        res, _ = _match_empty(tstream)
        if res is not None: continue

        res, _ = _match_var_decl(tstream)
        if res is not None:
            stmts.append(res)
            continue

        res, _ = _match_block(tstream)
        if res is None:
            curtok = next(tstream)
            msg = f'Line {curtok.start.line} at column {curtok.start.column}: '
            msg += 'unable to parse'
            raise SyntaxError(msg)
        
        stmts.append(res)