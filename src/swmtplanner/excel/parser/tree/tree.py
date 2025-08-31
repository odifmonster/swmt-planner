#!/usr/bin/env python

from ..lexer import TokType, TokStream
from .treetypes import Atom, KWArg, Info, Empty

def _match_tok(toks: TokStream, is_tgt, converter):
    t = next(toks)
    if is_tgt(t):
        return converter(t), 1
    toks.backup()
    return None, 0

def _match_cont(toks: TokStream):
    total = 0
    
    argtups = [
        (lambda tok: tok.kind == TokType.ELLIPSIS, lambda tok: Empty()),
        (lambda tok: tok.kind == TokType.NEWLINE, lambda tok: Empty())
    ]

    items = []
    for argtup in argtups:
        item, consumed = _match_tok(toks, argtup[0], argtup[1])
        total += consumed
        if item is None:
            toks.backup(consumed)
            return None, 0
        items.append(item)

    _, consumed = _match_tok(toks, lambda tok: tok.kind == TokType.INDENT,
                             lambda tok: Empty())
    total += consumed

    return Empty(), total

def _match_comma(toks: TokStream):
    total = 0

    while True:
        cont, consumed = _match_cont(toks)
        if cont is None:
            toks.backup(consumed)
            break
        total += consumed

    comma, consumed = _match_tok(toks, lambda tok: tok.kind == TokType.COMMA,
                                 lambda tok: Empty())
    total += consumed
    if comma is None:
        toks.backup(consumed)
        return None, 0
    
    while True:
        cont, consumed = _match_cont(toks)
        if cont is None:
            toks.backup(consumed)
            break
        total += consumed

    return Empty(), total

def _match_list(toks: TokStream):
    def is_atom(tok):
        return tok.kind in (TokType.NAME, TokType.NUM, TokType.STRING, TokType.FILE)
    def convert_atom(tok):
        return Atom(tok.kind, tok.value)
    
    first, consumed = _match_tok(toks, is_atom, convert_atom)
    if first is None:
        toks.backup(consumed)
        return None, 0
    
    items = [first]
    total = consumed
    while True:
        comma, consumed = _match_comma(toks)
        if comma is None:
            toks.backup(consumed)
            break

        cur_cnsmd = consumed
        item, consumed = _match_tok(toks, is_atom, convert_atom)
        cur_cnsmd += consumed
        if item is None:
            toks.backup(cur_cnsmd)
            break
        total += cur_cnsmd
        items.append(item)

    if len(items) == 1:
        return items[0], total
    return items, total

def _match_line(toks: TokStream):
    total = 0

    argtups = [
        (lambda tok: tok.kind == TokType.NEWLINE, lambda tok: Empty()),
        (lambda tok: tok.kind == TokType.INDENT and len(tok.value) == 4,
         lambda tok: Empty()),
        (lambda tok: tok.kind == TokType.NAME, lambda tok: tok.value),
        (lambda tok: tok.kind == TokType.EQUALS, lambda tok: Empty())
    ]
    items = []

    for argtup in argtups:
        item, consumed = _match_tok(toks, argtup[0], argtup[1])
        total += consumed
        if item is None:
            toks.backup(total)
            return None, 0
        items.append(item)

    matched_list, consumed = _match_list(toks)
    total += consumed
    if matched_list is None:
        toks.backup(total)
        return None, 0
    
    return KWArg(items[2], matched_list), total

def _match_block(toks: TokStream):
    total = 0

    argtups = [
        (lambda tok: tok.kind in (TokType.START, TokType.NEWLINE), lambda tok: Empty()),
        (lambda tok: tok.kind == TokType.NAME, lambda tok: tok.value),
        (lambda tok: tok.kind == TokType.COLON, lambda tok: Empty())
    ]
    items = []

    for argtup in argtups:
        item, consumed = _match_tok(toks, argtup[0], argtup[1])
        total += consumed
        if item is None:
            toks.backup(total)
            return None, 0
        items.append(item)

    lines = []
    while True:
        line, consumed = _match_line(toks)
        if line is None:
            toks.backup(consumed)
            break

        total += consumed
        lines.append(line)

    if not lines:
        toks.backup(total)
        return None, 0
    
    return Info(items[1], lines), total

def _match_empty(toks: TokStream):
    start, _ = _match_tok(toks, lambda tok: tok.kind in (TokType.START, TokType.NEWLINE),
                          lambda tok: Empty())
    if start is None:
        return None, 0
    
    rem, _ = _match_tok(toks, lambda tok: tok.kind == TokType.INDENT, lambda tok: Empty())
    if rem is None:
        return Empty(), 1
    return Empty(), 2

def parse(buffer):
    tstream = TokStream(buffer)
    file = []

    while True:
        end, consumed = _match_tok(tstream,
                                   lambda tok: tok.kind == TokType.END,
                                   lambda tok: Empty())
        if end is not None:
            break
        tstream.backup(consumed)

        block, consumed = _match_block(tstream)
        if block is not None:
            file.append(block)
            continue
        tstream.backup(consumed)

        empty, consumed = _match_empty(tstream)
        if empty is None:
            tstream.backup(consumed)
            tok = next(tstream)
            raise SyntaxError(f'Line {tok.start.line} at column {tok.start.line_offset}' + \
                              ': Unable to parse')
    
    return file