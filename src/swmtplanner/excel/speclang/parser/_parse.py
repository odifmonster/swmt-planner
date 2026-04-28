#!/usr/bin/env python

import functools

from ..tstream import TStream, Token, tokens
from . import trees

def _match_tok(tstream: TStream, tgt: str | frozenset[str],
               converter = None):
    if type(tgt) is frozenset:
        is_tgt = lambda t: t.kind in tgt
    else:
        is_tgt = lambda t: t.kind == tgt

    if converter is None:
        converter = lambda t: trees.Empty(t)

    if tstream.has_ended:
        return None, 0
    
    tok = tstream.advance()
    if is_tgt(tok):
        return converter(tok), 1
    tstream.backup(1)
    return None, 0

@functools.cache
def _get_tok_matcher(tgt: str | frozenset[str],
                     converter = None):
    def wrapper(tstream: TStream):
        return _match_tok(tstream, tgt, converter=converter)
    return wrapper

def _match_all(tstream: TStream, funcs, alt_vals = None):
    if alt_vals is None:
        alt_vals = [None for _ in range(len(funcs))]

    total = 0
    items = []
    for func, alt_val in zip(funcs, alt_vals):
        res, consumed = func(tstream)
        total += consumed
        if res is None and alt_val is None:
            tstream.backup(total)
            return None, 0
        if res is None:
            items.append(alt_val)
        else:
            items.append(res)
    
    return items, total

def _match_one(tstream: TStream, funcs):
    for func in funcs:
        res, consumed = func(tstream)
        if res is not None:
            return res, consumed
    return None, 0

def _get_atom(tok: Token):
    match tok.kind:
        case tokens.INT:
            val = int(tok.raw)
        case tokens.FLOAT:
            val = float(tok.raw)
        case tokens.STRING:
            val = tok.raw[1:-1]
        case tokens.NAME:
            val = tok.raw
        case _:
            raise RuntimeError('FATAL: something unexpected occurred')
    return trees.Atom(trees.AtomType[tok.kind], val, tok)

def _match_atom(tstream: TStream, kind = None):
    if kind is None:
        tgt = frozenset([tokens.INT, tokens.FLOAT, tokens.STRING,
                         tokens.NAME])
    else:
        tgt = kind
    return _match_tok(tstream, tgt, converter=_get_atom)

def _match_group(tstream: TStream):
    items, total = _match_all(
        tstream, [_get_tok_matcher(tokens.LPAREN),
                  _match_exp,
                  _get_tok_matcher(tokens.RPAREN)])
    if items is None:
        return None, 0
    return items[1], total

def _match_access(tstream: TStream):
    owner, total = _match_atom(tstream, kind=tokens.NAME)
    if owner is None:
        return None, 0

    while True:
        items, consumed = _match_all(
            tstream, [_get_tok_matcher(tokens.DOT),
                      lambda s: _match_atom(s, kind=tokens.NAME)])
        
        if items is None:
            break

        total += consumed
        owner = trees.AccessExp(owner, items[0], items[1])
    
    return owner, total

def _match_exps(tstream: TStream):
    exp, total = _match_exp(tstream)
    if exp is None:
        return None, 0
    
    exps = [exp]
    while True:
        items, consumed = _match_all(tstream, [_get_tok_matcher(tokens.COMMA),
                                               _match_exp])
        
        if items is None:
            break

        total += consumed
        exps.append(items[1])
    
    return exps, total

def _match_call(tstream: TStream):
    res, total = _match_all(
        tstream, [lambda s: _match_atom(s, kind=tokens.NAME),
                  _get_tok_matcher(tokens.LPAREN),
                  _match_exps,
                  _get_tok_matcher(tokens.RPAREN)],
                 [None, None, [], None])
    if res is None:
        return None, 0
    
    func = trees.CallExp(res[0], res[2])
    while True:
        items, consumed = _match_all(
            tstream, [_get_tok_matcher(tokens.LPAREN),
                      _match_exps,
                      _get_tok_matcher(tokens.RPAREN)],
            alt_vals=[None, [], None])
        
        if items is None:
            break

        total += consumed
        func = trees.CallExp(func, items[1])
    
    return func, total

def _match_unpack(tstream: TStream):
    star, total = _match_tok(tstream, tokens.STAR)
    if star is not None:
        child, consumed = _match_unpack(tstream)
        if child is None:
            tstream.backup(total)
            return None, 0
        total += consumed
        return trees.UnpackExp(star, child), total
    res, total = _match_one(tstream, [_match_call, _match_access, _match_group,
                                      _match_atom, _match_list])
    return res, total

def _match_prod(tstream: TStream):
    left, total = _match_unpack(tstream)
    if left is None:
        return None, 0
    
    op_map = {
        tokens.STAR: trees.BinopType.MULT, tokens.SLASH: trees.BinopType.DIV,
        tokens.PCT: trees.BinopType.MOD
    }

    while True:
        items, consumed = _match_all(
            tstream, [_get_tok_matcher(frozenset(op_map.keys()),
                                       converter=lambda t: trees.Binop(op_map[t.kind], t)),
                      _match_unpack])
        
        if items is None:
            break

        total += consumed
        left = trees.BinopExp(items[0], left, items[1])
    
    return left, total

def _match_sum(tstream: TStream):
    left, total = _match_prod(tstream)
    if left is None:
        return None, 0
    
    op_map = {
        tokens.PLUS: trees.BinopType.ADD, tokens.MINUS: trees.BinopType.SUB
    }

    while True:
        items, consumed = _match_all(
            tstream, [_get_tok_matcher(frozenset(op_map.keys()),
                                       converter=lambda t: trees.Binop(op_map[t.kind], t)),
                      _match_prod])
        
        if items is None:
            break

        total += consumed
        left = trees.BinopExp(items[0], left, items[1])
    
    return left, total

def _match_pattern(tstream: TStream):
    items, total = _match_all(
        tstream, [lambda s: _match_atom(s, kind=tokens.NAME),
                  _get_tok_matcher(tokens.ARROW),
                  _match_sum])
    if items is not None:
        return trees.PatternExp(items[0], items[1], items[2]), total
    return None, 0

def _match_rng(tstream: TStream):
    items, total = _match_all(
        tstream, [_match_sum, _get_tok_matcher(tokens.TO),
                  _match_sum])
    if items is not None:
        return trees.RngExp(items[0], items[1], items[2]), total
    return None, 0

def _match_list(tstream: TStream):
    items, total = _match_all(
        tstream, [_get_tok_matcher(tokens.LBRACK),
                  _match_exps,
                  _get_tok_matcher(tokens.RBRACK)],
                 [None, [], None])
    if items is not None:
        return trees.ListExp(items[1]), total
    return None, 0

def _match_exp(tstream: TStream):
    return _match_one(tstream, [_match_rng, _match_pattern, _match_sum])

def _match_assign(tstream: TStream):
    items, total = _match_all(
        tstream, [lambda s: _match_atom(s, kind=tokens.NAME),
                  _get_tok_matcher(tokens.EQ), _match_exp])
    if items is not None:
        return trees.AssignStmt(items[0], items[1], items[2]), total
    return None, 0

def _match_simple_stmt(tstream: TStream):
    stmt, total = _match_assign(tstream)
    if stmt is None:
        return None, 0
    
    end, consumed = _match_tok(tstream, tokens.NEWLINE)
    if end is None:
        tstream.backup(total)
        return None, 0
    
    total += consumed
    return stmt, total

def _match_stmts(tstream: TStream):
    stmts = []
    total = 0

    while True:
        stmt, consumed = _match_stmt(tstream)
        if stmt is None:
            break
        total += consumed
        stmts.append(stmt)
    
    return stmts, total

def _match_block(tstream: TStream):
    items, total = _match_all(
        tstream, [_get_tok_matcher(tokens.LBRACK),
                  lambda s: _match_atom(s, kind=tokens.NAME),
                  _get_tok_matcher(tokens.RBRACK),
                  lambda s: _match_atom(s, kind=tokens.NAME),
                  _get_tok_matcher(tokens.COLON),
                  _get_tok_matcher(tokens.NEWLINE),
                  _get_tok_matcher(tokens.INDENT),
                  _match_stmts,
                  _get_tok_matcher(tokens.DEDENT)])
    if items is not None:
        if len(items[7]) == 0:
            tstream.backup(total)
            return None, 0
        return trees.BlockStmt(items[1], items[3], items[7]), total
    return None, 0

def _match_stmt(tstream: TStream):
    return _match_one(tstream, [_match_simple_stmt, _match_block])

def parse(tstream: TStream):
    stmts, _ = _match_stmts(tstream)
    end, _ = _match_tok(tstream, tokens.EOF)
    if end is None:
        bad_tok = tstream.last_token
        msg = f'Line {bad_tok.start.line} at column {bad_tok.start.col}:'
        msg += ' Failed to parse'
        raise SyntaxError(msg)
    return stmts