#!/usr/bin/env python

from ..lexer import TokType, Lexer
from .trees import Empty, AtomType, Atom, Attribute, Block

"""
file -> (empty | block)*

block -> START? NAME COLON line_end (empty* attribute)+
"""

def _match_tok(tstream: Lexer, is_tgt, converter = None):
    try:
        tok = next(tstream)

        if type(is_tgt) is list:
            tgt_list = is_tgt
            is_tgt = lambda t: t.kind in tgt_list
        elif isinstance(is_tgt, TokType):
            ttype = is_tgt
            is_tgt = lambda t: t.kind == ttype

        if converter is None:
            converter = lambda t: Empty()

        if not is_tgt(tok):
            tstream.backup(1)
            return None, 0
        
        return converter(tok), 1
    except StopIteration:
        return None, 0

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
    if tok.kind == TokType.NAME:
        at_kind = AtomType.NAME
    elif tok.kind == TokType.NUMBER:
        at_kind = AtomType.NUMBER
    elif tok.kind == TokType.FILE:
        at_kind = AtomType.FILE
    else:
        at_kind = AtomType.STRING
    
    return Atom(at_kind, tok.value)

def _match_value(tstream: Lexer):
    total = 0
    vals: list[Atom] = []

    res, consumed = _match_tok(tstream, [TokType.NAME, TokType.NUMBER, TokType.FILE,
                                         TokType.STRING], converter=_get_atom)
    total += consumed
    if res is None:
        return None, 0
    vals.append(res)

    while True:
        cur_cnsmd = 0

        res, consumed = _match_tok(tstream, TokType.COMMA)
        cur_cnsmd += consumed
        if res is None:
            return vals, total
        
        res, consumed = _match_tok(tstream,
                                   [TokType.NAME, TokType.NUMBER, TokType.FILE,
                                    TokType.STRING], converter=_get_atom)
        cur_cnsmd += consumed
        if res is None:
            tstream.backup(cur_cnsmd)
            return vals, total
        
        total += cur_cnsmd
        vals.append(res)

def _match_attribute(tstream: Lexer):
    total = 0

    tups = [
        (TokType.INDENT, None), (TokType.NAME, lambda t: t.value),
        (TokType.EQUALS, None)
    ]
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

def _match_block_attr(tstream: Lexer):
    total = 0

    while True:
        res, consumed = _match_empty(tstream)
        total += consumed
        if res is None:
            break

    res, consumed = _match_attribute(tstream)
    total += consumed
    if res is None:
        tstream.backup(total)
        return None, 0
    
    return res, total

def _match_block(tstream: Lexer):
    total = 0

    _, consumed = _match_tok(tstream, TokType.START)
    total += consumed

    tups = [
        (TokType.NAME, lambda t: t.value), (TokType.COLON, None),
        (TokType.NEWLINE, None)
    ]
    items = []

    for is_tgt, converter in tups:
        res, consumed = _match_tok(tstream, is_tgt, converter=converter)
        total += consumed
        if res is None:
            tstream.backup(total)
            return None, 0
        items.append(res)

    name = items[0]
    attrs: list[Attribute] = []

    while True:
        res, consumed = _match_block_attr(tstream)
        total += consumed
        if res is None:
            break
        attrs.append(res)
    
    if not attrs:
        tstream.backup(total)
        return None, 0
    
    return Block(name, attrs), total

def parse(buffer):
    tstream = Lexer(buffer)
    blocks: list[Block] = []

    while True:
        try:
            next(tstream)
            tstream.backup(1)
        except StopIteration:
            return blocks
        
        res, _ = _match_empty(tstream)
        if res is not None: continue

        res, _ = _match_block(tstream)
        if res is None:
            curtok = next(tstream)
            msg = f'Line {curtok.start.line} at column {curtok.start.column}: '
            msg += 'unable to parse'
            raise SyntaxError(msg)
        
        blocks.append(res)